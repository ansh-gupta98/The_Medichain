"""
Doctor router — the core identification pipeline.

POST /doctor/identify
  1. Receive a live photo from the doctor's app
  2. Extract ArcFace embedding
  3. Firestore KNN vector search → find nearest patient
  4. Threshold check (reject if similarity too low)
  5. Fetch full patient profile + medical records
  6. Generate Cerebras AI clinical summary
  7. Return everything to the doctor in < 5 seconds

POST /doctor/add-record
  Allows the doctor to add a new medical record for a patient
  after identification.
"""

import logging
import uuid
import json
from datetime import date

from fastapi import APIRouter, File, UploadFile, HTTPException, Form, status, Body
from typing import Optional, Dict, Any, List

from app.core.schemas import (
    IdentifyResponse,
    PatientMedicalData,
    MedicalRecord,
    APIResponse,
    DoctorPatientCreateResponse,
    DoctorQueryRequest,
    DoctorQueryResponse,
    parse_allergies,
)
from app.services.face_service import face_service
from app.services.firebase_service import firebase_service
from app.services.llm_service import llm_service
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# POST /doctor/identify  ← The main endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/identify",
    response_model=IdentifyResponse,
    summary="Identify patient from live photo",
    description="""
**Core MediChain endpoint.**

The doctor captures a live photo of the patient.
This endpoint:
1. Extracts a 512-D ArcFace R100 embedding from the photo
2. Runs Firestore KNN Vector Search to find the closest match
3. If similarity ≥ threshold (default 0.50), fetches the patient's full medical data
4. Generates a Cerebras AI clinical summary for quick doctor review
5. Returns everything in a single response

**Expected response time:** 1–3 seconds on Render standard tier.
    """,
)
async def identify_patient(
    photo: UploadFile = File(
        ...,
        description="Live photo of patient (JPEG/PNG/WEBP). Single clear face required.",
    ),
    doctor_uid: Optional[str] = Form(
        None,
        description="Firebase UID of the doctor making the request (for audit logging).",
    ),
    include_ai_summary: bool = Form(
        True,
        description="Set false to skip Cerebras AI summary (faster response).",
    ),
):
    # ── Validate photo type ───────────────────────────────────────────────────
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if photo.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{photo.content_type}'. Use JPEG, PNG, or WEBP.",
        )

    # ── Step 1: Read photo bytes ──────────────────────────────────────────────
    photo_bytes = await photo.read()
    logger.info(
        f"Identify request from doctor '{doctor_uid}' — "
        f"photo size: {len(photo_bytes) / 1024:.1f} KB"
    )

    # ── Step 2: Extract ArcFace embedding ────────────────────────────────────
    query_embedding, msg = face_service.extract_embedding(photo_bytes)

    if query_embedding is None:
        return IdentifyResponse(
            success=False,
            matched=False,
            confidence_score=0.0,
            confidence_label="NO_MATCH",
            patient_data=None,
            ai_summary=None,
            message=f"Face extraction failed: {msg}. Ensure the photo shows a clear, single face.",
        )

    # ── Step 3: Firestore KNN Vector Search ───────────────────────────────────
    try:
        firebase_service.initialize()
        results = firebase_service.find_nearest_patient(query_embedding, top_k=1)
    except Exception as e:
        logger.error(f"Firestore KNN search error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database search failed: {str(e)}",
        )

    if not results:
        return IdentifyResponse(
            success=True,
            matched=False,
            confidence_score=0.0,
            confidence_label="NO_MATCH",
            patient_data=None,
            ai_summary=None,
            message="No patients registered in the system yet.",
        )

    patient_uid, similarity, raw_data = results[0]
    confidence_label = face_service.get_confidence_label(similarity)

    logger.info(
        f"KNN match: patient_uid={patient_uid}, "
        f"similarity={similarity:.4f}, label={confidence_label}"
    )

    # ── Step 4: Threshold check ───────────────────────────────────────────────
    # Similarity threshold: reject matches below 0.50 to prevent false positives
    # Medical context — we set a conservative threshold
    match_threshold = 1.0 - settings.FACE_MATCH_THRESHOLD  # convert distance→similarity

    if similarity < match_threshold:
        return IdentifyResponse(
            success=True,
            matched=False,
            confidence_score=round(similarity, 4),
            confidence_label="NO_MATCH",
            patient_data=None,
            ai_summary=None,
            message=(
                f"No confident match found (similarity={similarity:.2%}). "
                "The patient may not be registered in MediChain."
            ),
        )

    # ── Step 5: Fetch full patient profile + medical records ─────────────────
    try:
        profile = firebase_service.get_patient_profile(patient_uid)
        if not profile:
            logger.warning(f"Patient {patient_uid} has embedding but no profile doc!")
            profile = {}

        records_raw = firebase_service.get_medical_records(patient_uid)
    except Exception as e:
        logger.error(f"Patient data fetch error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch patient data: {str(e)}",
        )

    # ── Build structured patient data ────────────────────────────────────────
    medical_records = [
        MedicalRecord(
            record_id=rec.get("record_id", ""),
            date=str(rec.get("date", "")) if rec.get("date") else None,
            hospital=rec.get("hospital"),
            doctor_name=rec.get("doctor_name") or rec.get("doctor"),
            diagnosis=rec.get("diagnosis"),
            prescription=rec.get("prescription"),
            report_urls=rec.get("report_urls", []),
            notes=rec.get("notes"),
        )
        for rec in records_raw
    ]

    patient_data = PatientMedicalData(
        patient_uid=patient_uid,
        name=profile.get("name", "Unknown"),
        age=profile.get("age"),
        blood_group=profile.get("blood_group"),
        allergies=profile.get("allergies", []),
        emergency_contact=profile.get("emergency_contact"),
        medical_records=medical_records,
        embedding_updated_at=profile.get("embedding_updated_at"),
    )

    # ── Step 6: LLM AI clinical summary ──────────────────────────────────────
    ai_summary = None
    if include_ai_summary:
        try:
            ai_summary = llm_service.generate_medical_summary(profile, records_raw)
        except Exception as e:
            logger.warning(f"LLM summary failed (non-critical): {e}")
            ai_summary = "AI summary temporarily unavailable."

    # ── Step 7: Return response ───────────────────────────────────────────────
    return IdentifyResponse(
        success=True,
        matched=True,
        confidence_score=round(similarity, 4),
        confidence_label=confidence_label,
        patient_data=patient_data,
        ai_summary=ai_summary,
        doctor_query_hint=(
            "Use POST /doctor/query-patient with this patient_uid "
            "to ask specific questions about their records."
        ),
        message=f"Patient identified successfully with {similarity:.1%} confidence.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /doctor/add-record
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/add-record",
    response_model=APIResponse,
    summary="Add a medical record for a patient (post-consultation)",
    description=(
        "Allows a doctor to add a new medical record after identifying the patient. "
        "Record is stored in patients/{uid}/medical_records sub-collection."
    ),
)
async def add_medical_record(
    patient_uid: str = Body(..., embed=True),
    date: Optional[str] = Body(None, embed=True),
    hospital: Optional[str] = Body(None, embed=True),
    doctor_name: Optional[str] = Body(None, embed=True),
    diagnosis: Optional[str] = Body(None, embed=True),
    prescription: Optional[str] = Body(None, embed=True),
    report_urls: Optional[list] = Body(default=[], embed=True),
    notes: Optional[str] = Body(None, embed=True),
):
    try:
        firebase_service.initialize()

        record_data = {
            "date": date,
            "hospital": hospital,
            "doctor_name": doctor_name,
            "diagnosis": diagnosis,
            "prescription": prescription,
            "report_urls": report_urls or [],
            "notes": notes,
        }
        # Remove None values
        record_data = {k: v for k, v in record_data.items() if v is not None}

        record_id = firebase_service.add_medical_record(patient_uid, record_data)

        return APIResponse(
            success=True,
            message=f"Medical record added successfully.",
            data={"record_id": record_id, "patient_uid": patient_uid},
        )
    except Exception as e:
        logger.error(f"Add record error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add record: {str(e)}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST /doctor/register-patient — Walk-in patient enrollment by doctor
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/register-patient",
    response_model=DoctorPatientCreateResponse,
    summary="Doctor enrolls a walk-in patient (with optional photos + medical record)",
)
async def doctor_register_patient(
    # Demographics
    name: str = Form(..., min_length=2, max_length=100),
    age: int = Form(..., ge=0, le=150),
    blood_group: str = Form(...),
    allergies: str = Form(default="[]", description="JSON array or comma-separated string"),
    emergency_contact: Optional[str] = Form(None),
    # Medical record (optional)
    hospital: Optional[str] = Form(None),
    doctor_name: Optional[str] = Form(None),
    diagnosis: Optional[str] = Form(None),
    prescription: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    # Identity
    doctor_uid: Optional[str] = Form(None),
    patient_uid: Optional[str] = Form(None, description="Custom UID; auto-generated if absent"),
    # Photos (0..10, optional)
    photos: List[UploadFile] = File(default=[]),
):
    """
    Walk-in enrollment: doctor can register a new patient at the hospital.
    - 0–10 photos accepted
    - Automatic duplicate face detection (returns existing patient if matched)
    - Optional immediate medical record creation
    - Full audit trail in doctor_queries collection
    """
    firebase_service.initialize()
    parsed_allergies = parse_allergies(allergies)

    # ── Filter and validate photos ───────────────────────────────────────────
    # Detect if any non-empty photos were uploaded
    non_empty_photos = [p for p in photos if p.filename and len(p.filename.strip()) > 0]
    photo_bytes_list = []

    if non_empty_photos:
        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        for photo in non_empty_photos:
            if photo.content_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail=f"File '{photo.filename}' has unsupported type '{photo.content_type}'. Allowed: JPEG, PNG, WEBP.",
                )

        # Enforce minimum 3 photos and maximum 10 photos for face enrollment
        if len(non_empty_photos) < 3 or len(non_empty_photos) > 10:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Face registration requires between 3 and 10 photos for high-accuracy recognition. "
                    f"Received {len(non_empty_photos)} photo(s). Please provide at least 3 photos."
                ),
            )

        for photo in non_empty_photos:
            content = await photo.read()
            if len(content) > 0:
                photo_bytes_list.append(content)

    matched_existing = False
    final_uid = patient_uid or f"walkin-{uuid.uuid4().hex[:12]}"

    # ── Duplicate face check BEFORE creating new patient ─────────────────────
    if photo_bytes_list:
        try:
            # Use first valid photo for quick duplicate check
            check_emb, _ = face_service.extract_embedding(photo_bytes_list[0])
            if check_emb is not None:
                dup_results = firebase_service.find_nearest_patient(check_emb, top_k=1)
                if dup_results:
                    dup_uid, dup_sim, _ = dup_results[0]
                    match_thr = 1.0 - settings.FACE_MATCH_THRESHOLD
                    if dup_sim >= match_thr:
                        logger.info(
                            f"Duplicate face detected: existing={dup_uid}, sim={dup_sim:.3f}"
                        )
                        # Add record to existing patient if medical data provided
                        record_id = None
                        if any([diagnosis, prescription, notes, hospital]):
                            record_data = {
                                "date": str(date.today()),
                                "hospital": hospital,
                                "doctor_name": doctor_name,
                                "diagnosis": diagnosis,
                                "prescription": prescription,
                                "notes": notes,
                                "uploaded_by": "doctor",
                            }
                            record_data = {k: v for k, v in record_data.items() if v}
                            record_id = firebase_service.add_medical_record(
                                dup_uid, record_data
                            )
                        return DoctorPatientCreateResponse(
                            success=True,
                            patient_uid=dup_uid,
                            photos_processed=0,
                            record_id=record_id,
                            matched_existing=True,
                            message=(
                                f"Existing patient matched with {dup_sim:.1%} confidence. "
                                "Record added to existing profile."
                            ),
                        )
        except Exception as e:
            logger.warning(f"Duplicate check failed (non-critical): {e}")

    # ── Create / update patient profile ──────────────────────────────────────
    profile_data = {
        "name": name,
        "age": age,
        "blood_group": blood_group,
        "allergies": parsed_allergies,
        "emergency_contact": emergency_contact,
        "created_by": "doctor",
    }
    profile_data = {k: v for k, v in profile_data.items() if v is not None}
    firebase_service.upsert_patient_profile(final_uid, profile_data)

    # ── Process photos → embedding ────────────────────────────────────────────
    photos_ok = 0
    photos_failed = 0
    if photo_bytes_list:
        try:
            avg_emb, photos_ok, photos_failed = face_service.compute_average_embedding(
                photo_bytes_list
            )
            if avg_emb is not None:
                firebase_service.store_patient_embedding(final_uid, avg_emb.tolist())
                logger.info(f"Embedding stored for {final_uid}: {photos_ok} photos")
        except Exception as e:
            logger.error(f"Embedding error for {final_uid}: {e}")

    # ── Add medical record if data provided ──────────────────────────────────
    record_id = None
    if any([diagnosis, prescription, notes, hospital]):
        record_data = {
            "date": str(date.today()),
            "hospital": hospital,
            "doctor_name": doctor_name,
            "diagnosis": diagnosis,
            "prescription": prescription,
            "notes": notes,
            "uploaded_by": "doctor",
        }
        record_data = {k: v for k, v in record_data.items() if v}
        record_id = firebase_service.add_medical_record(final_uid, record_data)

    # ── Audit log ────────────────────────────────────────────────────────────
    try:
        firebase_service.write_audit_log(
            settings.DOCTOR_QUERIES_COLLECTION,
            {
                "doctor_uid": doctor_uid or "unknown",
                "patient_uid": final_uid,
                "action": "create",
                "photos_count": photos_ok,
                "has_medical_record": record_id is not None,
            },
        )
    except Exception as e:
        logger.warning(f"Audit log write failed (non-critical): {e}")

    return DoctorPatientCreateResponse(
        success=True,
        patient_uid=final_uid,
        photos_processed=photos_ok,
        photos_failed=photos_failed,
        record_id=record_id,
        matched_existing=False,
        message=(
            f"Patient registered successfully. "
            f"Photos: {photos_ok} processed. "
            + (f"Record ID: {record_id}" if record_id else "No medical record added.")
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /doctor/query-patient — Strict RAG Q&A from patient data
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/query-patient",
    response_model=DoctorQueryResponse,
    summary="Doctor asks a specific question about patient data (strict RAG)",
)
async def query_patient(
    request: DoctorQueryRequest,
):
    """
    Strict RAG endpoint — LLM ONLY answers from stored patient records.
    Zero hallucination policy: if data not in records, LLM says so.
    """
    firebase_service.initialize()

    profile = firebase_service.get_patient_profile(request.patient_uid)
    if not profile:
        raise HTTPException(
            status_code=404,
            detail=f"Patient {request.patient_uid} not found in MediChain.",
        )

    records = firebase_service.get_medical_records(request.patient_uid)

    # Audit log for query
    try:
        firebase_service.write_audit_log(
            settings.DOCTOR_QUERIES_COLLECTION,
            {
                "doctor_uid": request.doctor_uid or "unknown",
                "patient_uid": request.patient_uid,
                "action": "query",
                "question": request.question[:200],
            },
        )
    except Exception as e:
        logger.warning(f"Audit log failed: {e}")

    try:
        answer = llm_service.query_patient_data(profile, records, request.question)
    except Exception as e:
        logger.error(f"LLM query error: {e}")
        raise HTTPException(
            status_code=503,
            detail="AI query service temporarily unavailable. Try again shortly.",
        )

    return DoctorQueryResponse(
        success=True,
        patient_uid=request.patient_uid,
        question=request.question,
        answer=answer,
        model_used=f"{settings.GEMINI_MODEL} → fallback: {settings.LLM_FALLBACK_MODEL}",
        message="Answer based strictly on patient records.",
    )
