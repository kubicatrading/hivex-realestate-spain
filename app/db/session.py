import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

logger = logging.getLogger(__name__)

# URL de conexión estricta a la base de datos PostgreSQL de Producción
db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL).strip()

connect_args = {}
if "postgresql" in db_url:
    if "sslmode" not in db_url:
        connect_args["sslmode"] = "require"
    connect_args["connect_timeout"] = 10

# Motor de Producción PostgreSQL único y exclusivo (NullPool para Vercel Serverless)
engine = create_engine(
    db_url,
    connect_args=connect_args,
    poolclass=NullPool,
    echo=False
)

ACTIVE_DB_ENGINE = "PostgreSQL (Producción)"
DB_STATUS_INFO = {
    "engine": "PostgreSQL (Producción)",
    "host": db_url.split("@")[-1].split("/")[0] if "@" in db_url else "remote",
    "connected": True
}

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
