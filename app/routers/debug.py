"""
Debug router — for diagnosing face recognition issues.
REMOVE or PROTECT with auth before production!
"""

import logging
import numpy as np
from fastapi import APIRouter, File, UploadFile, HTTPException, status, Form
from typing import Optional

from app.services.face_service import face_service
from app.services.firebase_service import firebase_service
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/analyze-photo",
    summary="[DEBUG] Analyze a photo — see embedding quality and detection details",
)
async def analyze_photo(
    photo: UploadFile = File(...),
):
    """
    Upload any photo and see:
    - Was face detected?
    - Detection confidence score
    - Embedding stats (norm, min, max, mean)
    - Model being used
    This helps diagnose why matching is failing.
    """
    face_service._ensure_loaded()

    photo_bytes = await photo.read()

    import cv2
    nparr = np.frombuffer(photo_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        return {"error": "Could not decode image"}

    h, w = img.shape[:2]
    faces = face_service._app.get(img)

    if not faces:
        return {
            "model": settings.INSIGHTFACE_MODEL,
            "image_size": f"{w}x{h}",
            "faces_detected": 0,
            "error": "No face detected in this image",
            "tip": "Ensure: good lighting, face fully visible, not blurry, facing camera"
        }

    result = []
    for i, face in enumerate(faces):
        emb = face.embedding.astype(np.float32)
        norm = np.linalg.norm(emb)
        emb_normalized = emb / norm if norm > 0 else emb

        result.append({
            "face_index": i,
            "detection_score": round(float(face.det_score), 4),
            "bbox": [round(float(x), 1) for x in face.bbox],
            "embedding_norm": round(float(norm), 4),
            "embedding_mean": round(float(np.mean(emb_normalized)), 6),
            "embedding_std": round(float(np.std(emb_normalized)), 6),
            "embedding_min": round(float(np.min(emb_normalized)), 4),
            "embedding_max": round(float(np.max(emb_normalized)), 4),
            "quality": "GOOD" if face.det_score > 0.7 else "MEDIUM" if face.det_score > 0.5 else "LOW",
        })

    return {
        "model_used": settings.INSIGHTFACE_MODEL,
        "image_size": f"{w}x{h}",
        "faces_detected": len(faces),
        "faces": result,
        "tip": "detection_score > 0.7 = good quality. Lower = poor image."
    }


@router.post(
    "/compare-two-photos",
    summary="[DEBUG] Compare two photos directly — see exact similarity score",
)
async def compare_two_photos(
    photo1: UploadFile = File(..., description="First photo (e.g., registration photo)"),
    photo2: UploadFile = File(..., description="Second photo (e.g., live capture)"),
):
    """
    Upload 2 photos of the same person and see the exact similarity.
    This bypasses Firestore and compares directly — pure model accuracy test.
    """
    face_service._ensure_loaded()

    bytes1 = await photo1.read()
    bytes2 = await photo2.read()

    emb1, msg1 = face_service.extract_embedding(bytes1)
    emb2, msg2 = face_service.extract_embedding(bytes2)

    if emb1 is None:
        return {"error": f"Photo 1 failed: {msg1}"}
    if emb2 is None:
        return {"error": f"Photo 2 failed: {msg2}"}

    similarity = float(np.dot(emb1, emb2))
    label = face_service.get_confidence_label(similarity)

    interpretation = ""
    if similarity >= 0.72:
        interpretation = "SAME PERSON — very confident"
    elif similarity >= 0.60:
        interpretation = "LIKELY SAME PERSON"
    elif similarity >= 0.50:
        interpretation = "POSSIBLY SAME PERSON — borderline"
    elif similarity >= 0.35:
        interpretation = "UNCERTAIN — model struggling (check image quality)"
    else:
        interpretation = "DIFFERENT PERSONS (or severe lighting/angle difference)"

    return {
        "model_used": settings.INSIGHTFACE_MODEL,
        "similarity_score": round(similarity, 4),
        "similarity_percent": f"{similarity * 100:.1f}%",
        "confidence_label": label,
        "interpretation": interpretation,
        "current_threshold": settings.FACE_MATCH_THRESHOLD,
        "would_match": similarity >= settings.FACE_MATCH_THRESHOLD,
        "photo1_status": msg1,
        "photo2_status": msg2,
        "tip": (
            "If same person scores < 0.60, check: "
            "lighting, face angle, blur, glasses, or image resolution"
        ),
    }


@router.post(
    "/compare-with-stored",
    summary="[DEBUG] Compare live photo against stored Firestore embedding",
)
async def compare_with_stored(
    photo: UploadFile = File(...),
    patient_uid: str = Form(...),
):
    """
    Compare a live photo with the embedding stored in Firestore for a patient.
    Shows the raw similarity without any threshold decision.
    Useful to check if stored embedding is stale/from wrong model.
    """
    face_service._ensure_loaded()
    firebase_service.initialize()

    photo_bytes = await photo.read()
    emb_live, msg = face_service.extract_embedding(photo_bytes)

    if emb_live is None:
        return {"error": f"Live photo embedding failed: {msg}"}

    # Get stored embedding from Firestore
    profile = firebase_service.get_patient_profile(patient_uid)
    if not profile:
        return {"error": f"No patient found with UID: {patient_uid}"}

    raw_embedding = profile.get("face_embedding")
    if raw_embedding is None:
        return {"error": "Patient has no face_embedding stored in Firestore. Re-upload photos."}

    # Convert stored embedding to numpy
    if hasattr(raw_embedding, '__iter__'):
        emb_stored = np.array(list(raw_embedding), dtype=np.float32)
    else:
        return {"error": f"Unexpected embedding type: {type(raw_embedding)}"}

    # Normalize stored embedding
    norm = np.linalg.norm(emb_stored)
    if norm > 0:
        emb_stored = emb_stored / norm

    similarity = float(np.dot(emb_live, emb_stored))
    label = face_service.get_confidence_label(similarity)

    return {
        "patient_uid": patient_uid,
        "model_used": settings.INSIGHTFACE_MODEL,
        "similarity_score": round(similarity, 4),
        "similarity_percent": f"{similarity * 100:.1f}%",
        "confidence_label": label,
        "would_match": similarity >= settings.FACE_MATCH_THRESHOLD,
        "stored_embedding_dim": len(emb_stored),
        "stored_embedding_norm_original": round(float(norm), 4),
        "diagnosis": (
            "LOW SCORE likely means stored embedding is from OLD MODEL (buffalo_sc). "
            "Re-upload patient photos to regenerate with buffalo_l."
        ) if similarity < 0.50 else "Score looks reasonable.",
        "action": (
            "Call POST /patient/upload-photos again for this patient"
        ) if similarity < 0.50 else "No action needed.",
    }


@router.get(
    "/model-info",
    summary="[DEBUG] See which model is loaded and configuration",
)
async def model_info():
    """See current model config — useful to verify buffalo_l is active."""
    return {
        "model_name": settings.INSIGHTFACE_MODEL,
        "model_loaded": face_service.is_loaded,
        "detection_size": settings.INSIGHTFACE_DET_SIZE,
        "match_threshold": settings.FACE_MATCH_THRESHOLD,
        "embedding_dimensions": 512,
        "expected_accuracy": "99.83%" if settings.INSIGHTFACE_MODEL == "buffalo_l" else "99.70%",
        "expected_same_person_similarity": ">= 0.60 for good images, >= 0.50 for poor images",
        "warning": (
            "If patients registered with buffalo_sc and now using buffalo_l, "
            "ALL patient embeddings must be regenerated. "
            "Call /patient/upload-photos again for each patient."
        ),
    }
