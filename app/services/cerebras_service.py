"""
Backward-compatibility adapter for cerebras_service.
Redirects to groq_service.
"""
from app.services.groq_service import groq_service

# Expose as cerebras_service for backwards compatibility
cerebras_service = groq_service
