"""
GroqService — AI-powered clinical summary generator & Multimodal Medical Document OCR.

Uses:
1. Groq LLaMA 3.3 70B (versatile) for ultra-fast clinical summaries (< 1s).
2. Groq LLaMA 3.2 11B Vision for multimodal OCR extraction from medical bills,
   doctor prescriptions, and diagnostic lab reports.
"""

import base64
import json
import logging
import os
import re
from typing import Dict, Any, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger(__name__)


class GroqService:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = settings.GROQ_API_KEY or os.environ.get("GROQ_API_KEY") or settings.CEREBRAS_API_KEY
            if not api_key:
                raise ValueError(
                    "GROQ_API_KEY is not set. Get your free key from https://console.groq.com/"
                )
            from groq import Groq
            self._client = Groq(api_key=api_key)
        return self._client

    @property
    def is_configured(self) -> bool:
        return bool(settings.GROQ_API_KEY or os.environ.get("GROQ_API_KEY") or settings.CEREBRAS_API_KEY)

    # ─────────────────────────────────────────────────────────────────────────
    # Clinical Summary Generator for Doctor Triage
    # ─────────────────────────────────────────────────────────────────────────

    def _build_summary_prompt(
        self,
        patient_profile: Dict[str, Any],
        medical_records: List[Dict[str, Any]],
    ) -> str:
        name = patient_profile.get("name", "Unknown")
        age = patient_profile.get("age", "Unknown")
        blood_group = patient_profile.get("blood_group", "Unknown")
        allergies = patient_profile.get("allergies", [])
        emergency_contact = patient_profile.get("emergency_contact", "Not provided")
        allergies_str = ", ".join(allergies) if allergies else "None known"

        records_text = ""
        if medical_records:
            for i, rec in enumerate(medical_records[:8], 1):
                records_text += (
                    f"\n  Record {i}:"
                    f"\n    Date: {rec.get('date', 'Unknown')}"
                    f"\n    Facility: {rec.get('hospital', rec.get('hospital_or_clinic', 'Unknown'))}"
                    f"\n    Type: {rec.get('document_type', 'Clinical Visit')}"
                    f"\n    Diagnosis: {rec.get('diagnosis', 'Not specified')}"
                    f"\n    Prescription/Meds: {rec.get('prescription', 'None')}"
                    f"\n    Lab Findings: {json.dumps(rec.get('lab_results', [])) if rec.get('lab_results') else 'N/A'}"
                    f"\n    Notes: {rec.get('notes', '')}"
                )
        else:
            records_text = "\n  No previous records found."

        return f"""You are an elite clinical assistant AI helping a doctor quickly understand an incoming patient's medical history.

PATIENT PROFILE:
- Name: {name}
- Age: {age}
- Blood Group: {blood_group}
- Known Allergies: {allergies_str}
- Emergency Contact: {emergency_contact}

PAST MEDICAL HISTORY & EXTRACTED RECORDS (most recent first):
{records_text}

TASK:
Generate an urgent clinical triage summary (max 150 words) for the doctor:
1. Critical Warnings: Allergies or high-risk contraindications
2. Active Conditions & Diagnoses
3. Current Ongoing Medications (from past prescriptions/bills)
4. Key Recent Lab Abnormalities (if any)
5. Attending Advice for Immediate Treatment

Format as clear bullet points. Direct, clinical, and factual. Do not hallucinate or include greetings."""

    def generate_medical_summary(
        self,
        patient_profile: Dict[str, Any],
        medical_records: List[Dict[str, Any]],
    ) -> str:
        """
        Generate clinical summary using Groq LLaMA 3.3 70B.
        """
        if not self.is_configured:
            return self._fallback_summary(patient_profile, medical_records)

        try:
            client = self._get_client()
            prompt = self._build_summary_prompt(patient_profile, medical_records)

            response = client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional clinical assistant. "
                            "Always respond with concise, structured bullet points. "
                            "Never exceed 150 words."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=350,
                temperature=0.2,
            )

            summary = response.choices[0].message.content.strip()
            logger.info("Groq medical summary generated successfully.")
            return summary

        except Exception as e:
            logger.error(f"Groq API summary error: {e}")
            return self._fallback_summary(patient_profile, medical_records)

    # ─────────────────────────────────────────────────────────────────────────
    # Multimodal OCR & Document Extraction (Bills, Prescriptions, Lab Reports)
    # ─────────────────────────────────────────────────────────────────────────

    def extract_medical_document(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        document_type_hint: str = "auto",
    ) -> Dict[str, Any]:
        """
        Extract structured medical data, medicines, and lab results from an image
        using Groq Vision (llama-3.2-11b-vision-preview).

        Returns:
            Dict matching structured medical record schema with extracted medicines,
            dosages, lab results, diagnosis, and summary.
        """
        if not self.is_configured:
            return self._fallback_document_extract(document_type_hint)

        try:
            client = self._get_client()

            # Encode image to base64 data URL
            base64_img = base64.b64encode(image_bytes).decode("utf-8")
            data_url = f"data:{mime_type};base64,{base64_img}"

            system_instruction = (
                "You are an expert medical OCR and clinical document parser. "
                "Analyze the provided medical document (which may be a pharmacy bill, hospital invoice, "
                "handwritten or printed doctor prescription, or diagnostic laboratory test report). "
                "Extract all available clinical information with high precision. "
                "You MUST return ONLY a valid JSON object without any Markdown fences or backticks."
            )

            user_prompt = f"""Examine this medical document image carefully and extract all relevant data.
Document Type Hint: {document_type_hint}

Return a valid JSON object strictly matching this schema:
{{
  "document_type": "prescription" | "medical_bill" | "lab_report" | "discharge_summary" | "other",
  "hospital_or_clinic": "Hospital, clinic, or pharmacy name, or null",
  "doctor_name": "Doctor name or null",
  "date": "Date found on document (YYYY-MM-DD or as written), or null",
  "diagnosis": "Diagnosed condition, illness, or primary finding, or null",
  "prescription": "Brief summary of prescribed medicines and regimens",
  "medicines": [
    {{
      "name": "Medicine name (e.g. Metformin, Paracetamol)",
      "dosage": "Strength/dosage (e.g. 500mg, 5ml)",
      "frequency": "How often (e.g. twice daily, 1-0-1, SOS)",
      "duration": "Duration (e.g. 5 days, 1 month, or null)"
    }}
  ],
  "lab_results": [
    {{
      "test_name": "Name of lab test (e.g. HbA1c, Platelet Count, Serum Creatinine)",
      "result_value": "Numerical result with unit (e.g. 14.2 g/dL, 130 mg/dL)",
      "reference_range": "Normal biological range (e.g. 12-16 g/dL)",
      "status": "NORMAL" | "HIGH" | "LOW" | "CRITICAL"
    }}
  ],
  "total_amount": "Total financial amount if this is a bill/invoice, or null",
  "summary": "2-3 sentence concise clinical summary of this document",
  "raw_text": "Complete transcribed text from the document"
}}"""

            response = client.chat.completions.create(
                model=settings.GROQ_VISION_MODEL,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                        ],
                    },
                ],
                temperature=0.1,
                max_tokens=1200,
            )

            content = response.choices[0].message.content.strip()
            # Clean markdown code blocks if model wrapped it in ```json ... ```
            content_cleaned = re.sub(r"^```json\s*", "", content, flags=re.MULTILINE)
            content_cleaned = re.sub(r"^```\s*", "", content_cleaned, flags=re.MULTILINE)
            content_cleaned = content_cleaned.strip("` \n\r")

            parsed = json.loads(content_cleaned)
            logger.info("Successfully extracted medical document via Groq Vision OCR.")
            return parsed

        except Exception as e:
            logger.error(f"Groq Vision extraction error: {e}")
            return self._fallback_document_extract(document_type_hint, str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # Fallback Methods
    # ─────────────────────────────────────────────────────────────────────────

    def _fallback_summary(
        self,
        patient_profile: Dict[str, Any],
        medical_records: List[Dict[str, Any]],
    ) -> str:
        name = patient_profile.get("name", "Unknown")
        blood_group = patient_profile.get("blood_group", "Unknown")
        allergies = patient_profile.get("allergies", [])
        allergies_str = ", ".join(allergies) if allergies else "None known"
        record_count = len(medical_records)

        recent_diagnosis = ""
        if medical_records:
            latest = medical_records[0]
            recent_diagnosis = (
                f"• Most recent diagnosis: {latest.get('diagnosis', 'N/A')} "
                f"({latest.get('date', 'date unknown')})"
            )

        return (
            f"📋 Basic Medical Summary for {name}:\n"
            f"• Blood Group: {blood_group}\n"
            f"• Known Allergies: {allergies_str}\n"
            f"• Total Medical Records: {record_count}\n"
            f"{recent_diagnosis}\n"
            f"\n⚠️ Groq API key not configured or unavailable."
        )

    def _fallback_document_extract(
        self, document_type_hint: str = "auto", error_msg: str = "Groq Vision unavailable"
    ) -> Dict[str, Any]:
        return {
            "document_type": document_type_hint if document_type_hint != "auto" else "medical_record",
            "hospital_or_clinic": "Uploaded Medical Document",
            "doctor_name": None,
            "date": None,
            "diagnosis": "Medical document uploaded by patient",
            "prescription": "Manual review required",
            "medicines": [],
            "lab_results": [],
            "total_amount": None,
            "summary": f"Document uploaded successfully. AI OCR status: {error_msg}.",
            "raw_text": "",
        }


# Singleton instance
groq_service = GroqService()
