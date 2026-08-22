import os
import shutil
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL).strip()

# Direct auto-translation of legacy direct host to active Supabase Pooler host
if "db.wxoctzvzmkavkmjwtnux.supabase.co" in db_url or "5432" in db_url and "supabase" in db_url:
    db_url = "postgresql://postgres.wxoctzvzmkavkmjwtnux:9gc%237vaQQ_U58FZ@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

connect_args = {}
if "supabase" in db_url or "pooler" in db_url or "sslmode" in db_url:
    connect_args["sslmode"] = "require"
connect_args["connect_timeout"] = 4

engine = None
ACTIVE_DB_ENGINE = "Unknown"
DB_STATUS_INFO = {}

# Intentar conectar con PostgreSQL o la URL provista
if not db_url.startswith("sqlite"):
    try:
        engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True, echo=False)
        with engine.connect() as conn:
            pass
        ACTIVE_DB_ENGINE = "PostgreSQL (Supabase Pooler)"
        DB_STATUS_INFO = {
            "engine": "PostgreSQL (Supabase Pooler)",
            "host": "aws-0-eu-central-1.pooler.supabase.com:6543",
            "connected": True
        }
    except Exception as e:
        print(f"Error conectando a PostgreSQL/Supabase ({e}), usando base de datos SQLite local.")
        engine = None

# Fallback a SQLite local persistente o sembrada
if engine is None or db_url.startswith("sqlite"):
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    seed_db = os.path.join(BASE_DIR, "hivex_local.db")
    tmp_db = "/tmp/hivex_local.db"

    if os.path.exists(seed_db):
        try:
            if os.path.exists(tmp_db):
                try:
                    os.remove(tmp_db)
                except Exception:
                    pass
            shutil.copyfile(seed_db, tmp_db)
            db_path = tmp_db
        except Exception:
            db_path = seed_db
    else:
        db_path = seed_db
    db_url = f"sqlite:///{db_path}"
    connect_args = {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args, echo=False)

    ACTIVE_DB_ENGINE = "SQLite (Fallback local)"
    DB_STATUS_INFO = {
        "engine": "SQLite (Fallback local)",
        "host": "local",
        "connected": True
    }

    try:
        from geoalchemy2.admin.dialects import sqlite as geo_sqlite
        geo_sqlite.after_create = lambda *args, **kwargs: None
        geo_sqlite.before_create = lambda *args, **kwargs: None
    except Exception:
        pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
