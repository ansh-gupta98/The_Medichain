"""
Patient router — handles patient registration and photo/embedding upload.

Endpoints:
  POST /patient/register      — Save patient profile to Firestore
  POST /patient/upload-photos — Accept 3–10 photos, generate averaged
                                ArcFace embedding, store in Firestore
  GET  /patient/{uid}         — Retrieve patient profile
"""

import logging
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, File, UploadFile, HTTPException, Form, status
from fastapi.responses import JSONResponse

from app.core.schemas import (
    PatientRegisterRequest,
    PatientRegisterResponse,
    EmbeddingUploadResponse,
    APIResponse,
    MedicalDocumentExtractResponse,
    MedicineItem,
    LabResultItem,
)
from app.services.face_service import face_service
from app.services.firebase_service import firebase_service
from app.services.groq_service import groq_service
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# POST /patient/register
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=PatientRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new patient profile",
    description=(
        "Creates or updates a patient document in Firestore with basic "
        "profile information. Call this BEFORE uploading photos."
    ),
)
async def register_patient(request: PatientRegisterRequest):
    try:
        firebase_service.initialize()

        profile_data = {
            "name": request.name,
            "age": request.age,
            "blood_group": request.blood_group,
            "allergies": request.allergies,
            "emergency_contact": request.emergency_contact,
        }

        firebase_service.upsert_patient_profile(request.patient_uid, profile_data)

        return PatientRegisterResponse(
            success=True,
            patient_uid=request.patient_uid,
            message=f"Patient '{request.name}' registered successfully.",
        )

    except Exception as e:
        logger.error(f"Patient registration error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST /patient/upload-photos
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/upload-photos",
    response_model=EmbeddingUploadResponse,
    summary="Upload 3–10 photos to generate face embedding",
    description=(
        "Accepts 3 to 10 face photos (JPEG/PNG/WEBP). "
        "Extracts ArcFace R100 embeddings from each, averages them "
        "for a robust representation, and stores the result in Firestore "
        "as a 512-dimensional vector. "
        "The patient must be registered first via /patient/register."
    ),
)
async def upload_patient_photos(
    patient_uid: str = Form(..., description="Firebase Auth UID of the patient"),
    photos: List[UploadFile] = File(
        ...,
        description="3 to 10 face photos (JPEG/PNG/WEBP). More = more accurate.",
    ),
):
    # ── Validation ────────────────────────────────────────────────────────────
    if len(photos) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Minimum 3 photos required. Got {len(photos)}.",
        )
    if len(photos) > 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum 10 photos allowed. Got {len(photos)}.",
        )

    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    for photo in photos:
        if photo.content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"File '{photo.filename}' has unsupported type '{photo.content_type}'. "
                    f"Allowed: JPEG, PNG, WEBP."
                ),
            )

    # ── Read all photo bytes ──────────────────────────────────────────────────
    image_bytes_list = []
    for photo in photos:
        content = await photo.read()
        image_bytes_list.append(content)

    # ── Generate averaged ArcFace embedding ───────────────────────────────────
    logger.info(
        f"Generating embedding for patient {patient_uid} "
        f"from {len(image_bytes_list)} photos..."
    )
    avg_embedding, success_count, fail_count = face_service.compute_average_embedding(
        image_bytes_list
    )

    if avg_embedding is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Could not detect a face in any of the {len(photos)} uploaded photos. "
                "Ensure photos are clear, well-lit, and show a single face."
            ),
        )

    if success_count < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Only {success_count} out of {len(photos)} photos had a detectable face. "
                "At least 3 valid face photos are required."
            ),
        )

    # ── Store in Firestore ────────────────────────────────────────────────────
    try:
        firebase_service.initialize()
        firebase_service.store_patient_embedding(patient_uid, avg_embedding)
    except Exception as e:
        logger.error(f"Firestore embedding storage error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store embedding: {str(e)}",
        )

    logger.info(
        f"Embedding stored for {patient_uid}: "
        f"{success_count} succeeded, {fail_count} failed."
    )

    return EmbeddingUploadResponse(
        success=True,
        patient_uid=patient_uid,
        photos_processed=success_count,
        photos_failed=fail_count,
        message=(
            f"Face embedding created from {success_count} photo(s) "
            f"and stored successfully. "
            + (f"{fail_count} photo(s) were skipped (no face detected)." if fail_count else "")
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /patient/{uid}
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{patient_uid}",
    response_model=APIResponse,
    summary="Get patient profile by UID",
)
async def get_patient(patient_uid: str):
    try:
        firebase_service.initialize()
        profile = firebase_service.get_patient_profile(patient_uid)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No patient found with UID: {patient_uid}",
            )
        # Remove embedding from response (not useful to clients, very large)
        profile.pop("face_embedding", None)

        return APIResponse(success=True, message="Patient found.", data=profile)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get patient error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST /patient/upload-document (Medical Bills, Prescriptions, Lab Reports OCR)
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/upload-document",
    response_model=MedicalDocumentExtractResponse,
    summary="Upload medical bill, prescription, or lab report for AI OCR extraction",
    description=(
        "Patients can upload images of past medical bills, pharmacy receipts, "
        "handwritten/printed doctor prescriptions, or diagnostic laboratory reports. "
        "Groq Vision AI extracts medicines, dosages, test results, diagnoses, and financial totals, "
        "and saves the structured record to the patient's Firestore medical history."
    ),
)
async def upload_medical_document(
    patient_uid: str = Form(..., description="Firebase Auth UID of the patient"),
    document: UploadFile = File(
        ...,
        description="Photo or scan of medical bill, prescription, or lab report (JPEG/PNG/WEBP)",
    ),
    document_type: str = Form(
        "auto",
        description="Hint: 'auto', 'medical_bill', 'prescription', or 'lab_report'",
    ),
    notes: Optional[str] = Form(
        None,
        description="Optional additional notes from patient",
    ),
):
    # ── Validate file type ────────────────────────────────────────────────────
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if document.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"File '{document.filename}' has unsupported type '{document.content_type}'. "
                f"Allowed types: JPEG, PNG, WEBP."
            ),
        )

    # ── Verify patient exists ─────────────────────────────────────────────────
    firebase_service.initialize()
    profile = firebase_service.get_patient_profile(patient_uid)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient not found with UID: {patient_uid}. Register profile first.",
        )

    # ── Read image bytes ──────────────────────────────────────────────────────
    doc_bytes = await document.read()
    if len(doc_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )

    # ── Extract structured data via Groq Vision OCR ───────────────────────────
    logger.info(
        f"Extracting medical document for patient {patient_uid} "
        f"({len(doc_bytes)/1024:.1f} KB, type: {document_type})..."
    )
    extracted = groq_service.extract_medical_document(
        image_bytes=doc_bytes,
        mime_type=document.content_type,
        document_type_hint=document_type,
    )

    doc_date = extracted.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    facility = extracted.get("hospital_or_clinic") or "Medical Document Upload"

    # ── Build record payload for Firestore ────────────────────────────────────
    record_payload = {
        "date": doc_date,
        "hospital": facility,
        "hospital_or_clinic": extracted.get("hospital_or_clinic"),
        "doctor_name": extracted.get("doctor_name"),
        "document_type": extracted.get("document_type", "medical_record"),
        "diagnosis": extracted.get("diagnosis") or "Medical record extracted via OCR",
        "prescription": extracted.get("prescription") or "",
        "medicines": extracted.get("medicines", []),
        "lab_results": extracted.get("lab_results", []),
        "total_amount": extracted.get("total_amount"),
        "summary": extracted.get("summary", ""),
        "raw_text": extracted.get("raw_text", ""),
        "notes": notes or extracted.get("summary", ""),
        "uploaded_by": "patient",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    record_id = firebase_service.add_medical_record(patient_uid, record_payload)
    logger.info(f"Medical document saved with record_id: {record_id}")

    # ── Update patient profile if new diagnosis or active medicines found ─────
    profile_updates = {}
    if extracted.get("diagnosis") and extracted["diagnosis"] != "None":
        existing_diagnoses = profile.get("diagnoses", "")
        new_diag = extracted["diagnosis"]
        if new_diag.lower() not in existing_diagnoses.lower():
            profile_updates["diagnoses"] = (
                f"{existing_diagnoses}; {new_diag}".strip("; ")
                if existing_diagnoses
                else new_diag
            )

    if profile_updates:
        firebase_service.upsert_patient_profile(patient_uid, profile_updates)

    # ── Build response ────────────────────────────────────────────────────────
    medicines_list = [
        MedicineItem(
            name=m.get("name", "Unknown"),
            dosage=m.get("dosage"),
            frequency=m.get("frequency"),
            duration=m.get("duration"),
        )
        for m in extracted.get("medicines", [])
        if isinstance(m, dict) and m.get("name")
    ]

    lab_results_list = [
        LabResultItem(
            test_name=lab.get("test_name", "Lab Test"),
            result_value=str(lab.get("result_value", "")),
            reference_range=lab.get("reference_range"),
            status=lab.get("status"),
        )
        for lab in extracted.get("lab_results", [])
        if isinstance(lab, dict) and lab.get("test_name")
    ]

    return MedicalDocumentExtractResponse(
        success=True,
        patient_uid=patient_uid,
        record_id=record_id,
        document_type=extracted.get("document_type", "medical_record"),
        hospital_or_clinic=extracted.get("hospital_or_clinic"),
        doctor_name=extracted.get("doctor_name"),
        date=doc_date,
        diagnosis=extracted.get("diagnosis"),
        prescription=extracted.get("prescription"),
        medicines=medicines_list,
        lab_results=lab_results_list,
        total_amount=extracted.get("total_amount"),
        summary=extracted.get("summary", "Document processed successfully."),
        message="Medical document analyzed, OCR extracted, and saved to medical records successfully.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /patient/{patient_uid}/records
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{patient_uid}/records",
    response_model=APIResponse,
    summary="Get all medical records, bills, prescriptions, and lab reports for patient",
)
async def get_patient_records(patient_uid: str):
    try:
        firebase_service.initialize()
        records = firebase_service.get_medical_records(patient_uid)
        return APIResponse(
            success=True,
            message=f"Retrieved {len(records)} medical record(s).",
            data=records,
        )
    except Exception as e:
        logger.error(f"Get patient records error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

