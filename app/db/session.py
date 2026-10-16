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


CANONICAL_SUPABASE_POOLER_URL = (
    "postgresql://postgres.wxoctzvzmkavkmjwtnux:9gc%237vaQQ_U58FZ"
    "@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require"
)


def init_database_engine(raw_url: str = None, force_prod: bool = None):
    """
    Inicializa el motor de base de datos.
    REGLA INQUEBRANTABLE: En entorno de producción está PROHIBIDO consultar SQLite en ningún caso.
    Si falla la conexión a Supabase PostgreSQL en producción, lanza RuntimeError inmediatamente
    antes que devolver datos de una base de datos local SQLite.
    """
    is_prod = is_production_environment() if force_prod is None else force_prod
    canon_url = get_ipv4_db_url(CANONICAL_SUPABASE_POOLER_URL)

    if raw_url is not None:
        candidate_urls = [get_ipv4_db_url(raw_url)]
    else:
        env_url = get_ipv4_db_url(os.getenv("DATABASE_URL", ""))
        candidate_urls = []
        if is_prod:
            # En producción (Vercel), priorizar el Pooler IPv4 canónico verificado de Supabase
            # para evitar bloqueos si existe una variable DATABASE_URL antigua en el panel de Vercel
            candidate_urls.append(canon_url)
            if env_url and env_url.startswith("postgresql") and "sqlite" not in env_url.lower() and env_url not in candidate_urls:
                candidate_urls.append(env_url)
        else:
            if env_url and env_url.startswith("postgresql") and "sqlite" not in env_url.lower():
                candidate_urls.append(env_url)
            if canon_url and canon_url not in candidate_urls:
                candidate_urls.append(canon_url)
            if not candidate_urls and env_url:
                candidate_urls.append(env_url)

    resolved_url = candidate_urls[0] if candidate_urls else ""

    if is_prod and ("sqlite" in resolved_url.lower() or not resolved_url.startswith("postgresql")):
        error_msg = (
            "CRÍTICO [PRODUCCIÓN]: PROHIBIDO consultar SQLite en el entorno de PRODUCCIÓN. "
            "DATABASE_URL debe apuntar obligatoriamente a Supabase PostgreSQL."
        )
        logger.critical(error_msg)
        raise RuntimeError(error_msg)

    last_conn_error = None
    for candidate_url in candidate_urls:
        if not candidate_url.startswith("postgresql") or "sqlite" in candidate_url.lower():
            continue
        conn_args = {}
        if "sslmode" not in candidate_url:
            conn_args["sslmode"] = "require"
        conn_args["connect_timeout"] = 5

        try:
            pg_engine = create_engine(
                candidate_url,
                connect_args=conn_args,
                poolclass=NullPool,
                echo=False
            )
            last_err = None
            attempts = 1 if "127.0.0.1" in candidate_url else 2
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
                "host": candidate_url.split("@")[-1].split("/")[0] if "@" in candidate_url else "remote",
                "connected": True
            }
            return pg_engine, candidate_url, active_engine_name, status_info
        except Exception as e_conn:
            last_conn_error = e_conn
            logger.warning(f"Intento de conexión PostgreSQL fallido ({candidate_url.split('@')[-1] if '@' in candidate_url else 'db'}): {e_conn}")

    if last_conn_error is None:
        last_conn_error = ValueError("DATABASE_URL no apunta a una instancia PostgreSQL/Supabase válida.")

    if is_prod:
        error_msg = (
            f"CRÍTICO [PRODUCCIÓN]: Fallo de conexión a Supabase PostgreSQL ({last_conn_error}). "
            f"PROHIBIDO el fallback a SQLite en el entorno de PRODUCCIÓN."
        )
        logger.critical(error_msg)
        raise RuntimeError(error_msg) from last_conn_error

    _root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _local_db_path = os.path.join(_root_dir, "hivex_local.db")
    logger.warning(f"PostgreSQL no alcanzable en desarrollo local ({last_conn_error}). Usando réplica SQLite local: sqlite:///{_local_db_path}")
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


try:
    engine, db_url, ACTIVE_DB_ENGINE, DB_STATUS_INFO = init_database_engine()
except Exception as _boot_err:
    logger.error(f"Error en conexión inicial de arranque a Supabase PostgreSQL: {_boot_err}")
    db_url = CANONICAL_SUPABASE_POOLER_URL
    engine = create_engine(
        db_url,
        poolclass=NullPool,
        echo=False,
        connect_args={"connect_timeout": 5},
    )
    ACTIVE_DB_ENGINE = "PostgreSQL (Supabase Cloud - Lazy Pool)"
    DB_STATUS_INFO = {
        "engine": ACTIVE_DB_ENGINE,
        "host": "aws-1-eu-west-1.pooler.supabase.com",
        "connected": False,
        "boot_error": str(_boot_err),
    }


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


if not is_production_environment():
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


