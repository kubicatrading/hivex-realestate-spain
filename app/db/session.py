import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)

connect_args = {}
if "supabase.co" in db_url or "sslmode" in db_url:
    connect_args["sslmode"] = "require"

try:
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        engine = create_engine(db_url, connect_args=connect_args, echo=False)
    else:
        engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True, echo=False)
        with engine.connect() as conn:
            pass
except Exception:
    db_url = "sqlite:///./hivex_local.db"
    connect_args = {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args, echo=False)
    
    # Disable spatial DDL triggers for SQLite when Spatialite extension is not installed
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
