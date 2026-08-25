import os
import re
import logging
from sqlalchemy import create_engine
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

# URL estricta de PostgreSQL convertida a la interfaz IPv4 de Supabase Pooler
db_url = get_ipv4_db_url(os.getenv("DATABASE_URL", settings.DATABASE_URL))

connect_args = {}
if "postgresql" in db_url:
    if "sslmode" not in db_url:
        connect_args["sslmode"] = "require"
    connect_args["connect_timeout"] = 5

# Motor de Producción PostgreSQL único y exclusivo (NullPool para Vercel Serverless)
engine = create_engine(
    db_url,
    connect_args=connect_args,
    poolclass=NullPool,
    echo=False
)

ACTIVE_DB_ENGINE = "PostgreSQL (Producción Pooler IPv4)"
DB_STATUS_INFO = {
    "engine": "PostgreSQL (Producción Pooler IPv4)",
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
