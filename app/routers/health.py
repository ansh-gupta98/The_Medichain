"""
Health check router — used by Render to verify the service is alive.
Also reports status of all sub-systems: InsightFace, Firebase, Cerebras.
"""

from fastapi import APIRouter
from app.core.schemas import HealthResponse
from app.services.face_service import face_service
from app.services.firebase_service import firebase_service
from app.services.groq_service import groq_service

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.
    Reports status of sub-systems: InsightFace, Firebase, Groq AI.
    """
    return HealthResponse(
        status="healthy",
        insightface_loaded=face_service.is_loaded,
        firebase_connected=firebase_service.is_connected,
        groq_configured=groq_service.is_configured,
        version="1.1.0",
    )
