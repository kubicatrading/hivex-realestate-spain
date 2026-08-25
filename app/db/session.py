import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

# Locate local SQLite seed database
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
seed_db = os.path.join(BASE_DIR, "hivex_local.db")
if not os.path.exists(seed_db):
    seed_db = os.path.join(os.getcwd(), "hivex_local.db")
if not os.path.exists(seed_db):
    seed_db = "/var/task/hivex_local.db"

db_url = os.getenv("DATABASE_URL", "").strip()

# Fast, zero-blocking engine initialization
if db_url and "postgresql" in db_url and os.getenv("FORCE_POSTGRES", "").lower() == "true":
    engine = create_engine(db_url, connect_args={"sslmode": "require", "connect_timeout": 2}, poolclass=NullPool, echo=False)
    ACTIVE_DB_ENGINE = "PostgreSQL"
    DB_STATUS_INFO = {"engine": "PostgreSQL", "host": "remote", "connected": True}
else:
    sqlite_url = f"sqlite:///{seed_db}"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, echo=False)
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
