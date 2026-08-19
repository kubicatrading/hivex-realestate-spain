import os
import shutil
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)
connect_args = {}

if "supabase.co" in db_url or "sslmode" in db_url:
    connect_args["sslmode"] = "require"

engine = None

# Intentar conectar con PostgreSQL o la URL provista
if not db_url.startswith("sqlite"):
    try:
        engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True, echo=False)
        with engine.connect() as conn:
            pass
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
            shutil.copyfile(seed_db, tmp_db)
            print("Sincronizada base de datos semilla hivex_local.db en /tmp/hivex_local.db")
        except Exception as err:
            print(f"Error copiando DB semilla: {err}")

    db_path = tmp_db if os.path.exists(tmp_db) else (seed_db if os.path.exists(seed_db) else tmp_db)
    db_url = f"sqlite:///{db_path}"
    connect_args = {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args, echo=False)

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
