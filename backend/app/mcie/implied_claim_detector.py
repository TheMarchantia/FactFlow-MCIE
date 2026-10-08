"""
Implied Claim Detection (Section 6.6, "Implied Claim Detection").

Detects factual claims that are implied by the juxtaposition of speech,
on-screen text (OCR), and visual context, or factual statements asserted in
the narration/captions that do not fit the strict rule-based patterns of
explicit_claim_detector.py.

Uses an LLM-assisted reasoning step (Section 6.6) to semantically extract
self-contained, checkable claims.

Configuration (environment variables):
    GEMINI_API_KEY        — required; falls back to empty claims if unset
    FACTFLOW_GEMINI_MODEL — model name (default: gemini-3.5-flash)
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv(
    "FACTFLOW_CLAIM_MODEL",
    os.getenv("FACTFLOW_GEMINI_MODEL", "gemini-flash-lite-latest"),
)
_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_TIMEOUT_SECONDS = 30.0

_SYSTEM_INSTRUCTION = """\
You are FactFlow's Multimodal Claim Intelligence Engine (MCIE).
Your task is Implied & Factual Claim Detection (Section 6.6).
You receive the speech transcript, on-screen text (OCR), and visual scene description from a short video clip.

Identify the primary checkable factual assertions or claims either:
1. Implied by the pairing of speech and visuals (e.g. reused footage implied as current, deictic references like 'look what happened here').
2. Factual statements or assertions made in the narration or on-screen captions about events, science, technology, people, or statistics that should be fact-checked.

Respond with ONLY a valid JSON object in this exact schema:
{
  "implied_claims": [
    {
      "text": "<concise, factual, self-contained checkable claim>",
      "source": "implied"
    }
  ]
}

Rules:
- Extract at most 1 to 3 distinct, high-priority checkable claims.
- If there are no factual or checkable assertions, return {"implied_claims": []}.
- Do NOT generate opinions, commentary, or vague labels. State clear propositions that can be fact-checked as True, False, or Misleading.
- Respond with raw JSON only. No markdown formatting.
"""


def _extract_text_signals(cb_out: Dict[str, Any]) -> tuple[str, str]:
    """Aggregate speech segments and OCR segments across all context units."""
    units = cb_out.get("context_units") or []
    speech_lines: List[str] = []
    ocr_lines: List[str] = []

    for unit in units:
        for seg in unit.get("speech_segments") or []:
            if seg and seg not in speech_lines:
                speech_lines.append(seg)
        for seg in unit.get("ocr_segments") or []:
            if seg and seg not in ocr_lines:
                ocr_lines.append(seg)

    return " ".join(speech_lines).strip(), " ".join(ocr_lines).strip()


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse JSON object from the model response."""
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict) and "implied_claims" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    # Try matching code fences
    for pattern in (r"```json\s*\n(.*?)\n\s*```", r"```\s*\n(.*?)\n\s*```"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(1))
                if isinstance(obj, dict) and "implied_claims" in obj:
                    return obj
            except json.JSONDecodeError:
                pass

    # Greedy brace match
    m = re.search(r"\{.*\"implied_claims\".*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    return None


async def run(cb_out: Dict[str, Any], vc_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Detect implied and multimodal claims (Section 6.6).

    Synthesizes speech, on-screen text, and visual descriptions from
    the Context Builder and Visual Context Understanding stages into
    checkable propositions.

    Output:
        {
          "implied_claims": [
            {"text": "...", "source": "implied"},
            ...
          ]
        }
    """
    speech_text, ocr_text = _extract_text_signals(cb_out)
    visual_context = vc_out.get("visual_context") or ""

    # If there is no usable input across any modality, return immediately
    if not speech_text and not ocr_text and (not visual_context or visual_context == "Video footage."):
        return {"implied_claims": []}

    api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.info("GEMINI_API_KEY unset; implied claim detection returning empty claims.")
        return {"implied_claims": []}

    user_prompt_sections = []
    if speech_text:
        user_prompt_sections.append(f"SPEECH TRANSCRIPT:\n{speech_text}")
    if ocr_text:
        user_prompt_sections.append(f"ON-SCREEN TEXT (OCR):\n{ocr_text}")
    if visual_context:
        user_prompt_sections.append(f"VISUAL SCENE:\n{visual_context}")

    user_prompt = "\n\n".join(user_prompt_sections)

    import httpx

    model = os.getenv("FACTFLOW_CLAIM_MODEL", os.getenv("FACTFLOW_GEMINI_MODEL", GEMINI_MODEL))
    url = f"{_API_BASE}/{model}:generateContent"
    params = {"key": api_key}
    headers = {"Content-Type": "application/json"}
    body = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, params=params, headers=headers, json=body)
            if resp.status_code != 200:
                logger.warning(
                    "Gemini claim detection returned HTTP %d: %.200s",
                    resp.status_code,
                    resp.text,
                )
                return {"implied_claims": []}

            res_json = resp.json()
            candidates = res_json.get("candidates", [])
            if not candidates:
                return {"implied_claims": []}

            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts).strip()
            parsed = _extract_json(text)

            if parsed and isinstance(parsed.get("implied_claims"), list):
                valid_claims: List[Dict[str, str]] = []
                for item in parsed["implied_claims"]:
                    if isinstance(item, dict) and item.get("text"):
                        valid_claims.append({
                            "text": str(item["text"]).strip(),
                            "source": str(item.get("source", "implied")),
                        })
                    elif isinstance(item, str) and item.strip():
                        valid_claims.append({
                            "text": item.strip(),
                            "source": "implied",
                        })
                return {"implied_claims": valid_claims}
    except Exception as exc:
        logger.warning("Implied claim detection failed: %r", exc)

    return {"implied_claims": []}
