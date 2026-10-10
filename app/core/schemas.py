"""
Pydantic schemas — request / response models for all API endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
import json


# ─────────────────────────────────────────────────────────────────────────────
# Shared / Common
# ─────────────────────────────────────────────────────────────────────────────

class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


# ─────────────────────────────────────────────────────────────────────────────
# Patient — Registration & Photo Upload
# ─────────────────────────────────────────────────────────────────────────────

class PatientRegisterRequest(BaseModel):
    patient_uid: str = Field(..., description="Firebase Auth UID of the patient")
    name: str = Field(..., min_length=2, max_length=100)
    age: int = Field(..., ge=0, le=150)
    blood_group: str = Field(..., description="e.g. A+, B-, O+, AB+")
    allergies: List[str] = Field(default=[], description="List of known allergies")
    emergency_contact: Optional[str] = None


class PatientRegisterResponse(BaseModel):
    success: bool
    patient_uid: str
    message: str


class EmbeddingUploadResponse(BaseModel):
    success: bool
    patient_uid: str
    photos_processed: int
    photos_failed: int
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Doctor — Face Identification
# ─────────────────────────────────────────────────────────────────────────────

class MedicalRecord(BaseModel):
    record_id: str
    date: Optional[str] = None
    hospital: Optional[str] = None
    doctor_name: Optional[str] = None
    diagnosis: Optional[str] = None
    prescription: Optional[str] = None
    report_urls: List[str] = []
    notes: Optional[str] = None


class PatientMedicalData(BaseModel):
    patient_uid: str
    name: str
    age: Optional[int] = None
    blood_group: Optional[str] = None
    allergies: List[str] = []
    emergency_contact: Optional[str] = None
    medical_records: List[MedicalRecord] = []
    embedding_updated_at: Optional[str] = None


class IdentifyResponse(BaseModel):
    success: bool
    matched: bool
    confidence_score: float = Field(
        ...,
        description="Cosine similarity score 0.0–1.0. Higher = more confident."
    )
    confidence_label: str = Field(
        ...,
        description="Human-readable label: HIGH / MEDIUM / LOW / NO_MATCH"
    )
    patient_data: Optional[PatientMedicalData] = None
    ai_summary: Optional[str] = Field(
        None,
        description="AI-generated clinical summary for the doctor (Gemini/Groq)"
    )
    doctor_query_hint: Optional[str] = Field(
        None,
        description="Hint: use POST /doctor/query-patient to ask specific questions"
    )
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Patient Document Upload & OCR Extraction
# ─────────────────────────────────────────────────────────────────────────────

class MedicineItem(BaseModel):
    name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None


class LabResultItem(BaseModel):
    test_name: str
    result_value: str
    reference_range: Optional[str] = None
    status: Optional[str] = None  # NORMAL, HIGH, LOW, CRITICAL


class MedicalDocumentExtractResponse(BaseModel):
    success: bool
    patient_uid: str
    record_id: str
    document_type: str
    hospital_or_clinic: Optional[str] = None
    doctor_name: Optional[str] = None
    date: Optional[str] = None
    diagnosis: Optional[str] = None
    prescription: Optional[str] = None
    medicines: List[MedicineItem] = []
    lab_results: List[LabResultItem] = []
    total_amount: Optional[str] = None
    summary: str
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    insightface_loaded: bool
    firebase_connected: bool
    groq_configured: bool = True
    cerebras_configured: Optional[bool] = None
    version: str = "1.1.0"


# ─────────────────────────────────────────────────────────────────────────────
# Doctor — Walk-in Enrollment & RAG Query
# ─────────────────────────────────────────────────────────────────────────────

def parse_allergies(value) -> List[str]:
    """Parse allergies from JSON string OR comma string OR list."""
    if isinstance(value, list):
        return [str(a).strip() for a in value if a]
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        # Try JSON array first
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(a).strip() for a in parsed if a]
        except (json.JSONDecodeError, ValueError):
            pass
        # Fall back to comma-separated
        return [a.strip() for a in value.split(",") if a.strip()]
    return []


class DoctorPatientCreateResponse(BaseModel):
    success: bool
    patient_uid: str
    photos_processed: int = 0
    photos_failed: int = 0
    record_id: Optional[str] = None
    matched_existing: bool = Field(
        False,
        description="True if face matched an existing patient (duplicate prevented)",
    )
    message: str


class DoctorQueryRequest(BaseModel):
    patient_uid: str = Field(..., description="Patient UID to query")
    question: str = Field(
        ..., min_length=3, max_length=500, description="Doctor's question"
    )
    doctor_uid: Optional[str] = None


class DoctorQueryResponse(BaseModel):
    success: bool
    patient_uid: str
    question: str
    answer: str
    model_used: str = "gemini-fallback-groq"
    message: str
