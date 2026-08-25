import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from app.core.config import settings

# URL de la base de datos PostgreSQL de producción
db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL).strip()

connect_args = {}

if "postgresql" in db_url:
    if "sslmode" not in db_url:
        connect_args["sslmode"] = "require"
    connect_args["connect_timeout"] = 10
    
    # Motor PostgreSQL oficial de Producción con NullPool para Vercel Serverless
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
else:
    # Solo en desarrollo local explícito sin PostgreSQL
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    seed_db = os.path.join(BASE_DIR, "hivex_local.db")
    if not os.path.exists(seed_db):
        seed_db = os.path.join(os.getcwd(), "hivex_local.db")
    
    sqlite_url = f"sqlite:///{seed_db}"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, echo=False)
    ACTIVE_DB_ENGINE = "SQLite (Desarrollo Local)"
    DB_STATUS_INFO = {"engine": "SQLite (Desarrollo Local)", "host": "local", "connected": True}

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
