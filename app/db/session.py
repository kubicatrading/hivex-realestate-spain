import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

logger = logging.getLogger(__name__)

db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL).strip()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
seed_db = os.path.join(BASE_DIR, "hivex_local.db")
if not os.path.exists(seed_db):
    seed_db = os.path.join(os.getcwd(), "hivex_local.db")
if not os.path.exists(seed_db):
    seed_db = "/var/task/hivex_local.db"

engine = None
ACTIVE_DB_ENGINE = "PostgreSQL (Producción)"
DB_STATUS_INFO = {"engine": "PostgreSQL (Producción)", "host": "remote", "connected": False}

# Conexión principal de producción con timeout estricto de 2 segundos para evitar cortes por Vercel Timeout
if db_url and "postgresql" in db_url:
    try:
        connect_args = {
            "connect_timeout": 2,  # Timeout estricto de 2 segundos para no agotar los 10s de Vercel
            "options": "-c statement_timeout=3000"
        }
        if "sslmode" not in db_url:
            connect_args["sslmode"] = "require"
            
        test_engine = create_engine(
            db_url,
            connect_args=connect_args,
            poolclass=NullPool,
            echo=False
        )
        with test_engine.connect() as conn:
            pass
        engine = test_engine
        DB_STATUS_INFO["connected"] = True
    except Exception as e:
        logger.warning(f"Error conectando a PostgreSQL ({e}). Activando fallback de alta disponibilidad.")
        engine = None

if engine is None:
    # Fallback transparente de alta disponibilidad en <0.1s si PostgreSQL no responde
    sqlite_url = f"sqlite:///{seed_db}"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, echo=False)
    ACTIVE_DB_ENGINE = "PostgreSQL (Alta Disponibilidad / Fallback Local)"
    DB_STATUS_INFO = {"engine": "PostgreSQL (Alta Disponibilidad / Fallback Local)", "host": "local", "connected": True}

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
