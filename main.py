"""
MediChain — FastAPI Backend
Entry point: loads InsightFace model once at startup for maximum speed.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import patient, doctor, health, debug
from app.services.face_service import face_service
from app.services.firebase_service import firebase_service
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: only initialize lightweight services.
    InsightFace model lazy-loads on first request to avoid OOM on startup.
    """
    import traceback
    print("[MediChain] Lifespan startup BEGIN", flush=True)

    # Firebase — lightweight, just reads credentials
    try:
        firebase_service.initialize()
        print("[MediChain] Firebase connected OK", flush=True)
    except Exception:
        print("[MediChain] Firebase init failed (non-fatal):", flush=True)
        traceback.print_exc()

    # InsightFace: DO NOT load at startup — causes OOM on Railway 512MB free tier.
    # The model lazy-loads on the first /patient/register or /doctor/identify request.
    print("[MediChain] InsightFace will lazy-load on first request", flush=True)

    print("[MediChain] Lifespan startup DONE — app is READY", flush=True)
    yield
    print("[MediChain] Shutting down", flush=True)



app = FastAPI(
    title="MediChain API",
    description=(
        "AI-powered medical identity backend. "
        "Face recognition via InsightFace ArcFace R100, "
        "patient data from Firebase Firestore, "
        "AI summaries via Cerebras LLaMA."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow the Kotlin / Flutter frontend + any local dev
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health.router, tags=["Health"])
app.include_router(patient.router, prefix="/patient", tags=["Patient"])
app.include_router(doctor.router, prefix="/doctor", tags=["Doctor"])
app.include_router(debug.router, prefix="/debug", tags=["Debug — Remove in Production"])


@app.get("/", tags=["Root"])
async def root():
    return {
        "project": "MediChain",
        "status": "running",
        "docs": "/docs",
        "version": "1.0.0",
    }
