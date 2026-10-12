"""
Health check router — used by Render to verify the service is alive.
Also reports status of all sub-systems: InsightFace, Firebase, LLM Gateway.
"""

from fastapi import APIRouter
from app.core.schemas import HealthResponse
from app.services.face_service import face_service
from app.services.firebase_service import firebase_service
from app.services.llm_service import llm_service

router = APIRouter()


@router.api_route("/health", methods=["GET", "HEAD"], response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.
    Reports status of sub-systems: InsightFace, Firebase, LLM Gateway (Gemini/Groq).
    """
    return HealthResponse(
        status="healthy",
        insightface_loaded=face_service.is_loaded,
        firebase_connected=firebase_service.is_connected,
        groq_configured=llm_service.is_configured,
        version="1.2.0",
    )
