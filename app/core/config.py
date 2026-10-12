"""
Application configuration via environment variables.
All secrets loaded from .env or Railway environment — never hardcoded.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",  # Allow extra Railway / deployment environment variables without crashing
    )

    # ── FastAPI / Server ─────────────────────────────────────────────────────
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_ORIGINS: List[str] = ["*"]
    MEDICHAIN_HOST: str = "0.0.0.0"
    MEDICHAIN_QR_SECRET: str = "medichain-qr-secret-key"

    # buffalo_sc = ArcFace R50/MBF — ~150MB RAM (Safe for Render 512MB Free tier)
    # buffalo_l  = ArcFace R100    — ~600MB RAM (Use on Railway 8GB / Koyeb)
    INSIGHTFACE_MODEL: str = "buffalo_sc"
    INSIGHTFACE_DET_SIZE: int = 320
    INSIGHTFACE_HOME: str = "/root/.insightface"
    FACE_MATCH_THRESHOLD: float = 0.45

    # ── Firebase ──────────────────────────────────────────────────────────────
    FIREBASE_CREDENTIALS_PATH: str = "firebase_credentials.json"
    FIREBASE_CREDENTIALS_JSON: str = ""
    FIRESTORE_PATIENTS_COLLECTION: str = "patients"

    # ── Groq AI (Vision OCR & Fallback) ───────────────────────────────────────
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "qwen/qwen3.8-27b"
    GROQ_VISION_MODEL: str = "qwen/qwen3.8-27b"

    # ── LLM Gateway (LiteLLM) ─────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini/gemini-1.5-flash"
    GEMINI_PRO_MODEL: str = "gemini/gemini-1.5-pro"
    LLM_FALLBACK_MODEL: str = "groq/qwen/qwen3.8-27b"

    # ── LangChain & LangSmith Observability ───────────────────────────────────
    # Standard LangChain environment variables
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "medichain"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"

    # Backward-compatible alias
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "medichain"
    LANGSMITH_TRACING: bool = False

    # ── Doctor Audit ─────────────────────────────────────────────────────────
    DOCTOR_QUERIES_COLLECTION: str = "doctor_queries"

    # ── Storage ───────────────────────────────────────────────────────────────
    TEMP_UPLOAD_DIR: str = "/tmp/medichain_uploads"


settings = Settings()
