import os
import re
import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

logger = logging.getLogger(__name__)

def get_ipv4_db_url(raw_url: str) -> str:
    """
    1. Convierte esquemas heredados 'postgres://' a 'postgresql://' para compatibilidad con SQLAlchemy 1.4+.
    2. Escapa caracteres especiales como '#' en la contraseña por '%23'.
    3. Transforma URLs directas de Supabase (IPv6) a la URL del Pooler de Supabase (IPv4)
       para evitar el error 'Cannot assign requested address' en Vercel Serverless.
    """
    if not raw_url:
        return ""
    clean_url = raw_url.strip()

    if clean_url.startswith("postgres://"):
        clean_url = clean_url.replace("postgres://", "postgresql://", 1)

    # Escapar '#' en la parte de usuario:contraseña si no está escapado
    if "@" in clean_url:
        user_pass, host_part = clean_url.rsplit("@", 1)
        if "#" in user_pass:
            user_pass = user_pass.replace("#", "%23")
        clean_url = f"{user_pass}@{host_part}"

    if "supabase.co" in clean_url and "pooler" not in clean_url:
        match = re.search(r'db\.([a-z0-9]+)\.supabase\.co', clean_url)
        if match:
            ref = match.group(1)
            if f"://postgres.{ref}:" not in clean_url:
                clean_url = clean_url.replace("://postgres:", f"://postgres.{ref}:")
            clean_url = re.sub(r'db\.[a-z0-9]+\.supabase\.co:?\d*', 'aws-0-eu-central-1.pooler.supabase.com:6543', clean_url)
    return clean_url

def is_production_environment(env: dict = None) -> bool:
    """
    Detecta de forma estricta si la aplicación se está ejecutando en el entorno de producción.
    En producción está TERMINANTEMENTE PROHIBIDO usar o caer en fallback a SQLite.
    """
    source_env = os.environ if env is None else env
    if source_env.get("VERCEL") or source_env.get("VERCEL_ENV"):
        return True
    for env_var in ("ENV", "ENVIRONMENT", "HIVEX_ENV", "APP_ENV", "RAILWAY_ENVIRONMENT"):
        val = (source_env.get(env_var) or "").strip().lower()
        if val in ("prod", "production"):
            return True
    if source_env.get("RENDER"):
        return True
    return False


def init_database_engine(raw_url: str = None, force_prod: bool = None):
    """
    Inicializa el motor de base de datos.
    REGLA INQUEBRANTABLE: En entorno de producción está PROHIBIDO consultar SQLite en ningún caso.
    Si falla la conexión a Supabase PostgreSQL en producción, lanza RuntimeError inmediatamente
    antes que devolver datos de una base de datos local SQLite.
    """
    is_prod = is_production_environment() if force_prod is None else force_prod
    effective_raw_url = raw_url if raw_url is not None else os.getenv("DATABASE_URL", getattr(settings, "DATABASE_URL", ""))
    resolved_url = get_ipv4_db_url(effective_raw_url)

    if is_prod and ("sqlite" in resolved_url.lower() or not resolved_url.startswith("postgresql")):
        error_msg = (
            "CRÍTICO [PRODUCCIÓN]: PROHIBIDO consultar SQLite en el entorno de PRODUCCIÓN. "
            "DATABASE_URL debe apuntar obligatoriamente a Supabase PostgreSQL."
        )
        logger.critical(error_msg)
        raise RuntimeError(error_msg)

    conn_args = {}
    if "postgresql" in resolved_url:
        if "sslmode" not in resolved_url:
            conn_args["sslmode"] = "require"
        conn_args["connect_timeout"] = 5 if is_prod and "127.0.0.1" in resolved_url else 15

    try:
        if "postgresql" in resolved_url:
            pg_engine = create_engine(
                resolved_url,
                connect_args=conn_args,
                poolclass=NullPool,
                echo=False
            )
            # Test connection immediately with retry for serverless cold starts
            last_err = None
            attempts = 1 if "127.0.0.1" in resolved_url else 3
            for _attempt in range(attempts):
                try:
                    with pg_engine.connect() as conn:
                        last_err = None
                        break
                except Exception as _e:
                    last_err = _e
            if last_err is not None:
                raise last_err
            active_engine_name = "PostgreSQL (Producción Pooler IPv4)"
            status_info = {
                "engine": active_engine_name,
                "host": resolved_url.split("@")[-1].split("/")[0] if "@" in resolved_url else "remote",
                "connected": True
            }
            return pg_engine, resolved_url, active_engine_name, status_info
        else:
            raise ValueError("DATABASE_URL no apunta a una instancia PostgreSQL/Supabase válida.")
    except Exception as e_conn:
        if is_prod:
            error_msg = (
                f"CRÍTICO [PRODUCCIÓN]: Fallo de conexión a Supabase PostgreSQL ({e_conn}). "
                f"PROHIBIDO el fallback a SQLite en el entorno de PRODUCCIÓN."
            )
            logger.critical(error_msg)
            raise RuntimeError(error_msg) from e_conn

        _root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        _local_db_path = os.path.join(_root_dir, "hivex_local.db")
        logger.warning(f"PostgreSQL no alcanzable en desarrollo local ({e_conn}). Usando réplica SQLite local: sqlite:///{_local_db_path}")
        sqlite_url = f"sqlite:///{_local_db_path}"
        sqlite_engine = create_engine(
            sqlite_url,
            connect_args={"check_same_thread": False},
            echo=False
        )
        active_engine_name = "SQLite (Réplica Local de Supabase - Solo Desarrollo)"
        status_info = {
            "engine": active_engine_name,
            "host": "localhost",
            "connected": True
        }
        return sqlite_engine, sqlite_url, active_engine_name, status_info


engine, db_url, ACTIVE_DB_ENGINE, DB_STATUS_INFO = init_database_engine()


def run_db_migrations(target_engine):
    """Garantiza de forma idempotente que las columnas de rentabilidad y yield existan en SQLite y PostgreSQL."""
    try:
        inspector = inspect(target_engine)
        if "opportunities" in inspector.get_table_names():
            existing_columns = {col["name"] for col in inspector.get_columns("opportunities")}
            new_cols = [
                ("rental_yield", "FLOAT DEFAULT 0.0"),
                ("estimated_monthly_rent", "FLOAT DEFAULT 0.0"),
                ("yield_score", "FLOAT DEFAULT 0.0"),
                ("yield_color", "VARCHAR(20) DEFAULT 'rojo'"),
                ("btl_score", "FLOAT DEFAULT NULL")
            ]
            with target_engine.connect() as conn:
                for col_name, col_type in new_cols:
                    if col_name not in existing_columns:
                        try:
                            conn.execute(text(f"ALTER TABLE opportunities ADD COLUMN {col_name} {col_type};"))
                            conn.commit()
                        except Exception:
                            pass
    except Exception:
        pass


run_db_migrations(engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    if is_production_environment() and (
        getattr(engine.dialect, "name", "") == "sqlite" or "sqlite" in str(db_url).lower()
    ):
        raise RuntimeError(
            "PROHIBIDO consultar SQLite en el entorno de PRODUCCIÓN."
        )
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def sync_supabase_to_local_sqlite(sqlite_target_path: str = None) -> dict:
    """
    Sincroniza 1:1 todas las tablas de Supabase PostgreSQL hacia el archivo local `hivex_local.db`
    para garantizar que la réplica local de desarrollo sea idéntica a Supabase sin registros huérfanos,
    caducos ni oportunidades no-market sin foto de Street View.
    """
    from app.db import models  # noqa: F401
    pg_engine, _, _, _ = init_database_engine(force_prod=True)
    _root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    target_path = sqlite_target_path or os.path.join(_root_dir, "hivex_local.db")
    tmp_path = f"{target_path}.sync.tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    sq_engine = create_engine(f"sqlite:///{tmp_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=sq_engine)

    pg_inspector = inspect(pg_engine)
    pg_tables = set(pg_inspector.get_table_names())
    counts = {}

    with pg_engine.connect() as pg_conn, sq_engine.begin() as sq_conn:
        sq_conn.execute(text("PRAGMA foreign_keys = OFF;"))
        for table in Base.metadata.sorted_tables:
            if table.name not in pg_tables:
                continue
            rows = pg_conn.execute(table.select()).mappings().all()
            if rows:
                payloads = []
                for r in rows:
                    d = dict(r)
                    for k, v in list(d.items()):
                        if hasattr(v, "desc"):
                            d[k] = str(v)
                    payloads.append(d)
                sq_conn.execute(table.insert(), payloads)
            counts[table.name] = len(rows)
        sq_conn.execute(text("PRAGMA foreign_keys = ON;"))

    sq_engine.dispose()
    pg_engine.dispose()
    os.replace(tmp_path, target_path)
    return counts


