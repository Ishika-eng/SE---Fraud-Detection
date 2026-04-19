from pydantic_settings import BaseSettings
from typing import List
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    PROJECT_NAME: str = "Real-Time Fraud Detection System"
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "fraud_detection_db"
    MODEL_NAME: str = "all-MiniLM-L6-v2"
    # Set this in .env — never leave the default in production
    API_KEY: str = "dev-key-change-in-production"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()

if settings.API_KEY == "dev-key-change-in-production":
    logger.warning("SECURITY: API_KEY is using the default development value. Set API_KEY in .env before deploying.")
