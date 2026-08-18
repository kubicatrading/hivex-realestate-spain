import os
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict

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
    DATABASE_URL: str = "postgresql://postgres:hivex1234%23@db.wxoctzvzmkavkmjwtnux.supabase.co:5432/postgres"

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Opportunity Rules
    MIN_DISCOUNT_THRESHOLD: float = 0.10  # 10% below reference price

    # Supabase & Vercel Settings
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    model_config = ConfigDict(env_file=".env", extra="ignore")

settings = Settings()
