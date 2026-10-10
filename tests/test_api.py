"""
Quick integration tests — run with:
    pytest tests/ -v

These tests use httpx.AsyncClient to hit the FastAPI app without a real server.
Firebase and Cerebras calls are mocked so tests run offline.
"""

import io
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

# Patch services before importing the app
with patch("app.services.face_service.FaceService.load_model"):
    from main import app


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tiny_jpeg():
    """1x1 white JPEG for upload tests (real image bytes)."""
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "insightface_loaded" in data
    assert "firebase_connected" in data


@pytest.mark.asyncio
async def test_root():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["project"] == "MediChain"


# ─────────────────────────────────────────────────────────────────────────────
# Patient registration
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patient_register():
    with patch("app.services.firebase_service.firebase_service.initialize"), \
         patch("app.services.firebase_service.firebase_service.upsert_patient_profile"):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/patient/register",
                json={
                    "patient_uid": "test_uid_001",
                    "name": "Rahul Sharma",
                    "age": 30,
                    "blood_group": "B+",
                    "allergies": ["Penicillin"],
                    "emergency_contact": "9876543210",
                },
            )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["patient_uid"] == "test_uid_001"


# ─────────────────────────────────────────────────────────────────────────────
# Photo upload — too few photos
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_photos_too_few(tiny_jpeg):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/patient/upload-photos",
            data={"patient_uid": "test_uid_001"},
            files=[
                ("photos", ("p1.jpg", tiny_jpeg, "image/jpeg")),
                ("photos", ("p2.jpg", tiny_jpeg, "image/jpeg")),
            ],
        )
    assert response.status_code == 422
    assert "Minimum 3 photos" in response.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Doctor identify — no face in photo
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_identify_no_face(tiny_jpeg):
    with patch(
        "app.services.face_service.face_service.extract_embedding",
        return_value=(None, "No face detected in the image."),
    ):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/doctor/identify",
                files=[("photo", ("live.jpg", tiny_jpeg, "image/jpeg"))],
                data={"doctor_uid": "doc_001", "include_ai_summary": "false"},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is False
    assert data["confidence_label"] == "NO_MATCH"


# ─────────────────────────────────────────────────────────────────────────────
# FaceService unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_cosine_similarity_identical():
    from app.services.face_service import FaceService
    a = np.array([1.0, 0.0, 0.0])
    assert FaceService.cosine_similarity(a, a) == pytest.approx(1.0, abs=1e-5)


def test_cosine_similarity_orthogonal():
    from app.services.face_service import FaceService
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert FaceService.cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-5)


def test_confidence_label():
    from app.services.face_service import FaceService
    assert FaceService.get_confidence_label(0.90) == "HIGH"
    assert FaceService.get_confidence_label(0.70) == "MEDIUM"
    assert FaceService.get_confidence_label(0.55) == "LOW"
    assert FaceService.get_confidence_label(0.30) == "NO_MATCH"


# ─────────────────────────────────────────────────────────────────────────────
# Doctor register-patient — new walk-in enrollment endpoint
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_doctor_register_too_few_photos(tiny_jpeg):
    """Doctor enrolls a walk-in patient with only 1 photo — rejected (min 3 required)."""
    with patch("app.services.firebase_service.firebase_service.initialize"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/doctor/register-patient",
                data={
                    "name": "Priya Sharma",
                    "age": "28",
                    "blood_group": "O+",
                    "allergies": '["Penicillin"]',
                },
                files=[("photos", ("face.jpg", tiny_jpeg, "image/jpeg"))],
            )

    assert response.status_code == 422
    assert "requires between 3 and 10 photos" in response.json()["detail"]


@pytest.mark.asyncio
async def test_doctor_register_3_photos(tiny_jpeg):
    """Doctor enrolls a walk-in patient with 3 photos — all processed."""
    import numpy as np

    dummy_emb = np.zeros(512, dtype=np.float32)

    with patch("app.services.firebase_service.firebase_service.initialize"), \
         patch("app.services.firebase_service.firebase_service.upsert_patient_profile"), \
         patch("app.services.firebase_service.firebase_service.store_patient_embedding"), \
         patch("app.services.firebase_service.firebase_service.find_nearest_patient", return_value=[]), \
         patch("app.services.firebase_service.firebase_service.write_audit_log", return_value="log_001"), \
         patch(
             "app.services.face_service.face_service.extract_embedding",
             return_value=(dummy_emb, "ok"),
         ), \
         patch(
             "app.services.face_service.face_service.compute_average_embedding",
             return_value=(dummy_emb, 3, 0),
         ):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/doctor/register-patient",
                data={
                    "name": "Arjun Mehta",
                    "age": "45",
                    "blood_group": "A+",
                    "allergies": "Sulfa, Aspirin",
                },
                files=[
                    ("photos", ("p1.jpg", tiny_jpeg, "image/jpeg")),
                    ("photos", ("p2.jpg", tiny_jpeg, "image/jpeg")),
                    ("photos", ("p3.jpg", tiny_jpeg, "image/jpeg")),
                ],
            )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["photos_processed"] == 3
    assert data["matched_existing"] is False


@pytest.mark.asyncio
async def test_doctor_register_duplicate_face_returns_existing(tiny_jpeg):
    """
    When duplicate face is detected, endpoint should return the existing patient UID
    with matched_existing=True — no new patient created.
    """
    import numpy as np

    dummy_emb = np.zeros(512, dtype=np.float32)
    existing_uid = "existing-patient-abc"

    with patch("app.services.firebase_service.firebase_service.initialize"), \
         patch("app.services.firebase_service.firebase_service.add_medical_record", return_value="rec_dup"), \
         patch("app.services.firebase_service.firebase_service.write_audit_log", return_value="log_001"), \
         patch(
             "app.services.face_service.face_service.extract_embedding",
             return_value=(dummy_emb, "ok"),
         ), \
         patch(
             "app.services.firebase_service.firebase_service.find_nearest_patient",
             return_value=[(existing_uid, 0.92, {"name": "Existing Patient"})],
         ):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/doctor/register-patient",
                data={
                    "name": "New Patient Same Face",
                    "age": "30",
                    "blood_group": "B+",
                    "diagnosis": "Fever",
                    "hospital": "City Hospital",
                },
                files=[
                    ("photos", ("p1.jpg", tiny_jpeg, "image/jpeg")),
                    ("photos", ("p2.jpg", tiny_jpeg, "image/jpeg")),
                    ("photos", ("p3.jpg", tiny_jpeg, "image/jpeg")),
                ],
            )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["matched_existing"] is True
    assert data["patient_uid"] == existing_uid
    assert data["record_id"] == "rec_dup"


@pytest.mark.asyncio
async def test_doctor_register_no_photos_profile_only():
    """Doctor registers a walk-in patient with no photos — profile only, no embedding."""
    with patch("app.services.firebase_service.firebase_service.initialize"), \
         patch("app.services.firebase_service.firebase_service.upsert_patient_profile"), \
         patch("app.services.firebase_service.firebase_service.write_audit_log", return_value="log_001"):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/doctor/register-patient",
                data={
                    "name": "Kavya Reddy",
                    "age": "22",
                    "blood_group": "AB-",
                    "allergies": "[]",
                },
                # No photos — empty
            )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["photos_processed"] == 0
    assert data["matched_existing"] is False
    assert data["record_id"] is None


@pytest.mark.asyncio
async def test_doctor_register_with_medical_history(tiny_jpeg):
    """Doctor registers patient and immediately attaches a medical record."""
    import numpy as np

    dummy_emb = np.zeros(512, dtype=np.float32)

    with patch("app.services.firebase_service.firebase_service.initialize"), \
         patch("app.services.firebase_service.firebase_service.upsert_patient_profile"), \
         patch("app.services.firebase_service.firebase_service.store_patient_embedding"), \
         patch("app.services.firebase_service.firebase_service.find_nearest_patient", return_value=[]), \
         patch("app.services.firebase_service.firebase_service.add_medical_record", return_value="rec_history_01"), \
         patch("app.services.firebase_service.firebase_service.write_audit_log", return_value="log_001"), \
         patch(
             "app.services.face_service.face_service.extract_embedding",
             return_value=(dummy_emb, "ok"),
         ), \
         patch(
             "app.services.face_service.face_service.compute_average_embedding",
             return_value=(dummy_emb, 3, 0),
         ):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/doctor/register-patient",
                data={
                    "name": "Ravi Kumar",
                    "age": "55",
                    "blood_group": "O-",
                    "allergies": "Ibuprofen",
                    "hospital": "AIIMS Delhi",
                    "doctor_name": "Dr. Anita Singh",
                    "diagnosis": "Type 2 Diabetes",
                    "prescription": "Metformin 500mg twice daily",
                    "notes": "Monitor HbA1c every 3 months",
                },
                files=[
                    ("photos", ("p1.jpg", tiny_jpeg, "image/jpeg")),
                    ("photos", ("p2.jpg", tiny_jpeg, "image/jpeg")),
                    ("photos", ("p3.jpg", tiny_jpeg, "image/jpeg")),
                ],
            )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["photos_processed"] == 3
    assert data["record_id"] == "rec_history_01"
    assert "Ravi Kumar" not in data  # record_id in response, not name


# ─────────────────────────────────────────────────────────────────────────────
# Doctor query-patient — strict RAG endpoint
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_doctor_query_patient_strict_rag():
    """Query endpoint returns LLM answer strictly from patient records."""
    mock_profile = {
        "name": "Priya Sharma",
        "age": 28,
        "blood_group": "O+",
        "allergies": ["Penicillin"],
        "emergency_contact": "9876543210",
    }
    mock_records = [
        {
            "record_id": "rec_001",
            "date": "2024-01-15",
            "hospital": "Apollo Hospital",
            "doctor_name": "Dr. Mehta",
            "diagnosis": "Hypertension",
            "prescription": "Amlodipine 5mg daily",
            "notes": "BP controlled, follow-up in 1 month",
        }
    ]

    with patch("app.services.firebase_service.firebase_service.initialize"), \
         patch(
             "app.services.firebase_service.firebase_service.get_patient_profile",
             return_value=mock_profile,
         ), \
         patch(
             "app.services.firebase_service.firebase_service.get_medical_records",
             return_value=mock_records,
         ), \
         patch("app.services.firebase_service.firebase_service.write_audit_log", return_value="log_q"), \
         patch(
             "app.services.llm_service.llm_service.query_patient_data",
             return_value="Patient is prescribed Amlodipine 5mg daily for hypertension.",
         ):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/doctor/query-patient",
                json={
                    "patient_uid": "patient_priya_001",
                    "question": "What medication is the patient currently taking?",
                    "doctor_uid": "doc_001",
                },
            )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["success"] is True
    assert data["patient_uid"] == "patient_priya_001"
    assert "Amlodipine" in data["answer"]
    assert data["question"] == "What medication is the patient currently taking?"


@pytest.mark.asyncio
async def test_doctor_query_patient_not_found():
    """Query endpoint returns 404 when patient UID doesn't exist."""
    with patch("app.services.firebase_service.firebase_service.initialize"), \
         patch(
             "app.services.firebase_service.firebase_service.get_patient_profile",
             return_value=None,
         ):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/doctor/query-patient",
                json={
                    "patient_uid": "nonexistent_uid_xyz",
                    "question": "What are the patient's allergies?",
                },
            )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
