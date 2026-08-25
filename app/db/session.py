import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

# Locate local SQLite seed database
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
seed_db = os.path.join(BASE_DIR, "hivex_local.db")
if not os.path.exists(seed_db):
    seed_db = os.path.join(os.getcwd(), "hivex_local.db")
if not os.path.exists(seed_db):
    seed_db = "/var/task/hivex_local.db"

db_url = os.getenv("DATABASE_URL", "").strip()

engine = None
ACTIVE_DB_ENGINE = "SQLite (Local DB)"
DB_STATUS_INFO = {"engine": "SQLite (Local DB)", "host": "local", "connected": True}

# Attempt remote PostgreSQL connection if DATABASE_URL is explicitly set
if db_url and "postgresql" in db_url:
    try:
        connect_args = {"connect_timeout": 3}
        if "sslmode" in db_url or "supabase" in db_url:
            connect_args["sslmode"] = "require"
        test_engine = create_engine(db_url, connect_args=connect_args, poolclass=NullPool)
        with test_engine.connect() as conn:
            pass
        engine = test_engine
        ACTIVE_DB_ENGINE = "PostgreSQL"
        DB_STATUS_INFO = {"engine": "PostgreSQL", "host": "remote", "connected": True}
    except Exception as e:
        engine = None

if engine is None:
    # Reliable local SQLite fallback
    db_url = f"sqlite:///{seed_db}"
    connect_args = {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args, echo=False)
    ACTIVE_DB_ENGINE = "SQLite (Local DB)"
    DB_STATUS_INFO = {"engine": "SQLite (Local DB)", "host": "local", "connected": True}

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
