import os
import certifi
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict

# Ensure SSL certificate environment variables point to valid certificate bundles
if "SSL_CERT_FILE" in os.environ and not os.path.exists(os.environ["SSL_CERT_FILE"]):
    os.environ["SSL_CERT_FILE"] = certifi.where()
elif "SSL_CERT_FILE" not in os.environ and os.path.exists(certifi.where()):
    os.environ["SSL_CERT_FILE"] = certifi.where()

if "SSL_CERT_DIR" in os.environ and not os.path.exists(os.environ["SSL_CERT_DIR"]):
    del os.environ["SSL_CERT_DIR"]

class Settings(BaseSettings):
    PROJECT_NAME: str = "HIVEX Real Estate Spain Monitoring Engine"
    ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    
    # Database
    POSTGRES_USER: str = "hivex_user"
    POSTGRES_PASSWORD: str = "hivex_password"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "hivex_realestate"
    DATABASE_URL: str = "postgresql://postgres.wxoctzvzmkavkmjwtnux:9gc%237vaQQ_U58FZ@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require"

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Opportunity Rules
    MIN_DISCOUNT_THRESHOLD: float = 0.10  # 10% below reference price

    # Supabase & Vercel Settings
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Google Maps API Key for Street View Static Facade Photos
    GOOGLE_MAPS_API_KEY: str = ""

    model_config = ConfigDict(env_file=".env", extra="ignore")

settings = Settings()
