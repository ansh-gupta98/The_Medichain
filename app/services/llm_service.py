"""
LLM Gateway — LiteLLM with Gemini (primary) → Groq (fallback).
LangSmith tracing for all calls.

Features:
- generate_medical_summary(profile, records) → clinical summary
- query_patient_data(patient_data, question)  → RAG strict answer

Hardcore RAG prompt: LLM ONLY uses patient data, never hallucinates.
"""

import os
import logging
from typing import Optional, Dict, Any, List

import litellm
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self._configured = False

    def setup(self):
        """Configure LiteLLM with Gemini + Groq + LangSmith."""
        if self._configured:
            return

        # Set API keys for LiteLLM
        if settings.GEMINI_API_KEY:
            os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
        if settings.GROQ_API_KEY:
            os.environ["GROQ_API_KEY"] = settings.GROQ_API_KEY

        # LangChain / LangSmith tracing setup
        langchain_key = settings.LANGCHAIN_API_KEY or settings.LANGSMITH_API_KEY
        tracing_enabled = settings.LANGCHAIN_TRACING_V2 or settings.LANGSMITH_TRACING or bool(langchain_key)

        if langchain_key and tracing_enabled:
            os.environ["LANGCHAIN_API_KEY"] = langchain_key
            os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT or settings.LANGSMITH_PROJECT
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
            litellm.success_callback = ["langsmith"]
            litellm.failure_callback = ["langsmith"]
            logger.info(
                f"LangChain/LangSmith tracing enabled. Project: {os.environ['LANGCHAIN_PROJECT']}"
            )

        litellm.set_verbose = False
        self._configured = True
        logger.info(
            f"LLM Gateway configured. Primary: {settings.GEMINI_MODEL}, "
            f"Fallback: {settings.LLM_FALLBACK_MODEL}"
        )

    @property
    def is_configured(self) -> bool:
        return bool(settings.GEMINI_API_KEY or settings.GROQ_API_KEY)

    def _call_llm(
        self,
        messages: list,
        model: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> str:
        """Call LLM with automatic Gemini → Groq fallback."""
        self.setup()
        primary = model or settings.GEMINI_MODEL

        try:
            response = litellm.completion(
                model=primary,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.2,  # low temp for medical accuracy
                fallbacks=[settings.LLM_FALLBACK_MODEL],
                metadata={"project": settings.LANGSMITH_PROJECT},
            )
            used_model = response.model or primary
            logger.info(f"LLM call succeeded via: {used_model}")
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM gateway error: {e}")
            raise

    def generate_medical_summary(
        self, profile: Dict[str, Any], records: List[Dict]
    ) -> str:
        """Generate concise clinical summary for the attending doctor."""
        name = profile.get("name", "Unknown")
        age = profile.get("age", "N/A")
        blood_group = profile.get("blood_group", "Unknown")
        allergies = ", ".join(profile.get("allergies", [])) or "None known"

        records_text = ""
        if records:
            recent = records[:5]  # last 5 records
            for r in recent:
                records_text += (
                    f"- {r.get('date', '?')}: "
                    f"{r.get('diagnosis', 'No diagnosis')} | "
                    f"Rx: {r.get('prescription', 'None')} | "
                    f"Notes: {r.get('notes', '')}\n"
                )
        else:
            records_text = "No medical history on record."

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a senior clinical AI assistant. Provide a concise, structured "
                    "medical briefing for the attending doctor. Be direct and clinical. "
                    "Only use the data provided. Do NOT add anything not in the patient record."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Generate a quick clinical briefing for:\n\n"
                    f"Patient: {name} | Age: {age} | Blood Group: {blood_group}\n"
                    f"Allergies: {allergies}\n\n"
                    f"Medical History (most recent first):\n{records_text}\n\n"
                    f"Provide: 1) Key alerts (allergies, chronic conditions) "
                    f"2) Recent medical history summary "
                    f"3) Current medications if any "
                    f"4) Points to note for current consultation.\n"
                    f"Keep it under 200 words. Use clinical language."
                ),
            },
        ]

        return self._call_llm(messages, max_tokens=512)

    def query_patient_data(
        self,
        profile: Dict[str, Any],
        records: List[Dict],
        question: str,
    ) -> str:
        """
        RAG-style strict patient data query.
        HARDCORE PROMPTING: LLM answers ONLY from patient data.
        If info not in records, says so explicitly — never hallucinates.
        """
        # Build complete patient context
        name = profile.get("name", "Unknown")
        age = profile.get("age", "N/A")
        blood_group = profile.get("blood_group", "Unknown")
        allergies = profile.get("allergies", [])
        emergency_contact = profile.get("emergency_contact", "Not provided")

        records_text = ""
        if records:
            for i, r in enumerate(records, 1):
                records_text += (
                    f"Record #{i} — Date: {r.get('date', 'Unknown')}\n"
                    f"  Hospital: {r.get('hospital', 'Unknown')}\n"
                    f"  Doctor: {r.get('doctor_name', 'Unknown')}\n"
                    f"  Diagnosis: {r.get('diagnosis', 'Not recorded')}\n"
                    f"  Prescription: {r.get('prescription', 'None')}\n"
                    f"  Notes: {r.get('notes', '')}\n\n"
                )
        else:
            records_text = "NO MEDICAL RECORDS FOUND."

        system_prompt = """You are a strict medical record reader AI for MediChain.

CRITICAL RULES — follow these WITHOUT EXCEPTION:
1. ONLY answer using the patient data provided in this conversation.
2. If the requested information is NOT present in the patient records, respond EXACTLY: "This information is not recorded in the patient's MediChain records."
3. NEVER infer, guess, or extrapolate beyond what is explicitly stated in the records.
4. NEVER provide general medical advice or suggest treatments not in the records.
5. NEVER make up medications, diagnoses, or dates.
6. If a question cannot be answered from records, say what IS available instead.
7. Be concise and clinical — doctors need quick, accurate answers.
8. You may simplify medical terminology for clarity, but never add new medical content.

VIOLATING THESE RULES IS A PATIENT SAFETY RISK. ALWAYS STAY WITHIN THE RECORDS."""

        user_prompt = (
            f"PATIENT RECORDS:\n"
            f"========================\n"
            f"Name: {name}\n"
            f"Age: {age}\n"
            f"Blood Group: {blood_group}\n"
            f"Known Allergies: {', '.join(allergies) if allergies else 'None recorded'}\n"
            f"Emergency Contact: {emergency_contact}\n\n"
            f"MEDICAL HISTORY:\n"
            f"{records_text}\n"
            f"========================\n\n"
            f"DOCTOR'S QUESTION: {question}\n\n"
            f"Answer STRICTLY from the records above. If not in records, say so."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return self._call_llm(messages, max_tokens=768)


# Singleton
llm_service = LLMService()
