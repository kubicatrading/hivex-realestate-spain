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

    # Telegram (NUNCA hardcodear el token en código fuente para evitar exposición en GitHub)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = "-1003904392737"
    PLATFORM_BASE_URL: str = "https://hivex-realestate-spain.vercel.app"

    # Opportunity Rules
    MIN_DISCOUNT_THRESHOLD: float = 0.10  # 10% below reference price

    # Supabase & Vercel Settings
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # AI & Speech-to-Text Keys (Optional, fallback built-in engine active if empty)
    GEMINI_API_KEY: str = ""
    GOOGLE_API_KEY: str = ""
    GOOGLE_MAPS_API_KEY: str = "AIzaSyADs9RShXJVDUAO85OBIuwcjzC70V01_Vc"
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    TELEGRAM_AUTHORIZED_USERS: str = "8963408509,cyildirim,1450113787,jsaavedra,1234567"  # Comma-separated list of usernames or telegram user IDs allowed
    
    # DevAgent & GitHub Actions Dispatch
    GITHUB_TOKEN: str = ""
    GITHUB_REPO: str = "kubicatrading/hivex-realestate-spain"

    model_config = ConfigDict(env_file=".env", extra="ignore")

    def model_post_init(self, __context) -> None:
        if not (self.TELEGRAM_BOT_TOKEN or "").strip():
            self.TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not (self.TELEGRAM_CHAT_ID or "").strip():
            self.TELEGRAM_CHAT_ID = "-1003904392737"
        if not (self.DATABASE_URL or "").strip():
            self.DATABASE_URL = "postgresql://postgres.wxoctzvzmkavkmjwtnux:9gc%237vaQQ_U58FZ@aws-0-eu-central-1.pooler.supabase.com:6543/postgres?sslmode=require"
        if not (self.TELEGRAM_AUTHORIZED_USERS or "").strip():
            self.TELEGRAM_AUTHORIZED_USERS = "8963408509,cyildirim,1450113787,jsaavedra,1234567"
        if not (self.GITHUB_REPO or "").strip():
            self.GITHUB_REPO = "kubicatrading/hivex-realestate-spain"

settings = Settings()

