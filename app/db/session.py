import os
import shutil
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL).strip()
is_prod_env = bool(os.getenv("VERCEL") or os.getenv("ENV") == "production")

# En producción Vercel o si la URL apunta a Supabase, usar el host PgBouncer Pooler oficial
if is_prod_env or "supabase" in db_url:
    db_url = "postgresql://postgres.wxoctzvzmkavkmjwtnux:9gc%237vaQQ_U58FZ@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

connect_args = {}
if "supabase" in db_url or "pooler" in db_url or "sslmode" in db_url:
    connect_args["sslmode"] = "require"
connect_args["connect_timeout"] = 10

ACTIVE_DB_ENGINE = "PostgreSQL (Supabase Pooler)" if not db_url.startswith("sqlite") else "SQLite (Desarrollo local)"
DB_STATUS_INFO = {
    "engine": ACTIVE_DB_ENGINE,
    "host": "aws-0-eu-central-1.pooler.supabase.com:6543" if not db_url.startswith("sqlite") else "local",
    "connected": True
}

# En desarrollo local (not is_prod_env), si Supabase no es accesible desde esta máquina, usar SQLite local
if not is_prod_env:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    seed_db = os.path.join(BASE_DIR, "hivex_local.db")
    if os.path.exists(seed_db):
        try:
            test_engine = create_engine(db_url, connect_args=connect_args, poolclass=NullPool)
            with test_engine.connect() as conn:
                pass
        except Exception:
            db_url = f"sqlite:///{seed_db}"
            connect_args = {"check_same_thread": False}
            ACTIVE_DB_ENGINE = "SQLite (Desarrollo local)"
            DB_STATUS_INFO = {"engine": "SQLite (Desarrollo local)", "host": "local", "connected": True}

# Crear el motor SQLAlchemy principal con NullPool para Vercel Serverless
if db_url.startswith("sqlite"):
    engine = create_engine(db_url, connect_args=connect_args, echo=False)
else:
    engine = create_engine(db_url, connect_args=connect_args, poolclass=NullPool, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
