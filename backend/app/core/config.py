from pydantic_settings import BaseSettings
from typing import List
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    PROJECT_NAME: str = "Real-Time Fraud Detection System"
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "fraud_detection_db"
    MODEL_NAME: str = "all-MiniLM-L6-v2"

    # Extension auth — set in .env before deploying
    API_KEY: str = "dev-key-change-in-production"
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "null",  # file:// pages (test-form opened directly in browser)
    ]

    # Dashboard admin credentials — set in .env before deploying
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD_HASH: str = "$2b$12$02wzWjcbSLjesWzheYTMY.6sGgzouMuugWkL/FQkbUirt.AJ2hDJy"  # "admin123"

    # JWT settings
    JWT_SECRET: str = "jwt-secret-change-in-production"
    JWT_EXPIRE_MINUTES: int = 480  # 8-hour officer shift

    # Risk thresholds — configurable by admin (FR-20, BR-2)
    HIGH_RISK_THRESHOLD: float = 85.0
    MEDIUM_RISK_THRESHOLD: float = 60.0

    # Bot detection threshold — CPS above this is flagged as robotic
    BOT_CPS_THRESHOLD: float = 35.0

    # Device velocity limits — max submissions per device within rolling window
    DEVICE_MAX_ATTEMPTS:   int = 3    # block after this many submissions
    DEVICE_WINDOW_MINUTES: int = 60   # rolling window in minutes

    # LLM API keys — for auto-decision on middle-ground cases
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str    = ""

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()

if settings.API_KEY == "dev-key-change-in-production":
    logger.warning("SECURITY: API_KEY is using the default value. Set API_KEY in .env before deploying.")
if settings.JWT_SECRET == "jwt-secret-change-in-production":
    logger.warning("SECURITY: JWT_SECRET is using the default value. Set JWT_SECRET in .env before deploying.")
