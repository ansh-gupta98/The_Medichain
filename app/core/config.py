"""
Application configuration via environment variables.
All secrets loaded from .env — never hardcoded.
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # ── FastAPI ──────────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_ORIGINS: List[str] = ["*"]

    # ── InsightFace ───────────────────────────────────────────────────────────
    # buffalo_l  = ArcFace R100 — 99.83% accuracy — BEST (use on Railway)
    # buffalo_sc = ArcFace R50  — 99.70% accuracy — lighter (Render free only)
    INSIGHTFACE_MODEL: str = "buffalo_l"
    INSIGHTFACE_DET_SIZE: int = 480
    # ArcFace R100 threshold: similarity >= 0.50 = valid match
    # Conservative for medical use — prevents false positives
    FACE_MATCH_THRESHOLD: float = 0.50

    # ── Firebase ──────────────────────────────────────────────────────────────
    # Path to service-account JSON downloaded from Firebase console
    FIREBASE_CREDENTIALS_PATH: str = "firebase_credentials.json"
    FIRESTORE_PATIENTS_COLLECTION: str = "patients"

    # ── Groq AI (Ultra-fast LLM Summaries & Vision OCR) ───────────────────────
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_VISION_MODEL: str = "llama-3.2-11b-vision-preview"

    # Optional legacy fallback
    CEREBRAS_API_KEY: str = ""
    CEREBRAS_MODEL: str = "llama3.1-70b"

    # ── Storage ───────────────────────────────────────────────────────────────
    # Temporary directory for uploaded photos (cleaned after processing)
    TEMP_UPLOAD_DIR: str = "/tmp/medichain_uploads"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
