"""
Reasoning Provider — Gemini Client (Section 8, "External Reasoning Provider").

Sends the Verification Package assembled by VPG to Google's Gemini model
via the REST API with Google Search grounding enabled, then parses the
structured verdict response.

Uses httpx (already a project dependency) to call the Gemini REST API
directly, avoiding the protobuf version conflict between the
google-generativeai SDK and PaddlePaddle.

Configuration (environment variables):
    GEMINI_API_KEY            — required; without it every clip gets INCONCLUSIVE
    FACTFLOW_GEMINI_MODEL     — model name (default: gemini-2.0-flash)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("FACTFLOW_GEMINI_MODEL", "gemini-flash-lite-latest")

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_VALID_VERDICTS = frozenset({"TRUE", "FALSE", "MISLEADING", "INCONCLUSIVE"})
_MAX_ATTEMPTS = 2
_TIMEOUT_SECONDS = 60

# ── system instruction ───────────────────────────────────────────────

_SYSTEM_INSTRUCTION = """\
You are FactFlow's reasoning engine. You verify claims extracted from short
video clips by searching the web for corroborating or contradicting evidence.

You will receive a Verification Package with a query, extracted claims,
entities, on-screen text, speech transcript, and a scene summary.

Respond with ONLY a valid JSON object — no markdown fences, no commentary
outside the JSON — in this exact schema:

{
    "verdict": "TRUE" | "FALSE" | "MISLEADING" | "INCONCLUSIVE",
    "confidence": <integer 0-100>,
    "short_summary": "<concise 2-3 sentence summary for the quick preview card>",
    "detailed_summary": "<detailed paragraph explaining the context, evidence found, and why the verdict was reached>",
    "summary": "<2-3 sentence explanation>",
    "sources": [{"name": "<source>", "url": "<URL>"}, ...]
}

Verdict definitions:
  TRUE          — claim is accurate and corroborated by reliable sources.
  FALSE         — claim is factually incorrect per reliable sources.
  MISLEADING    — content is real but presented out of context (wrong date,
                  location, or attribution).
  INCONCLUSIVE  — insufficient evidence to determine accuracy.

Rules:
  - confidence is an integer 0-100.
  - Include 1-5 sources with real, verifiable URLs.
  - Prefer official news outlets, government data, and fact-checkers.
  - If evidence is insufficient, return INCONCLUSIVE with low confidence.
"""

_INCONCLUSIVE_FALLBACK: Dict[str, Any] = {
    "verdict": "INCONCLUSIVE",
    "confidence": 0,
    "summary": "The reasoning provider could not produce a verdict.",
    "short_summary": "The reasoning provider could not produce a verdict.",
    "detailed_summary": "The reasoning provider was unable to verify the claim with sufficient evidence from online sources.",
    "sources": [],
}


# ── prompt construction ──────────────────────────────────────────────

def _build_user_prompt(vp: Dict[str, Any]) -> str:
    """Assemble a structured prompt from the Verification Package fields."""
    sections: List[str] = []

    query = vp.get("verification_query", "")
    if query:
        sections.append(f"VERIFICATION QUERY:\n{query}")

    explicit = vp.get("explicit_claims") or []
    if explicit:
        lines = "\n".join(f"  - {c}" for c in explicit)
        sections.append(f"EXPLICIT CLAIMS:\n{lines}")

    implied = vp.get("implied_claims") or []
    if implied:
        imp_texts = [c["text"] if isinstance(c, dict) else str(c) for c in implied]
        lines = "\n".join(f"  - {c}" for c in imp_texts)
        sections.append(f"EXTRACTED / IMPLIED CLAIMS:\n{lines}")

    entities = vp.get("entities") or {}
    ent_lines: List[str] = []
    for key in ("event", "location", "date"):
        val = entities.get(key)
        if val:
            ent_lines.append(f"  {key.title()}: {val}")
    if ent_lines:
        sections.append("ENTITIES:\n" + "\n".join(ent_lines))

    for label, field in [
        ("VISUAL SCENE DESCRIPTION", "scene_summary"),
        ("ON-SCREEN TEXT (OCR)", "ocr_text"),
        ("SPEECH TRANSCRIPT", "speech_transcript"),
    ]:
        value = vp.get(field)
        if value:
            sections.append(f"{label}:\n{value}")

    ct = vp.get("claim_type")
    vt = vp.get("verification_target")
    if ct:
        sections.append(f"CLAIM TYPE: {ct}")
    if vt:
        sections.append(f"VERIFICATION TARGET: {vt}")

    return "\n\n".join(sections)


# ── response parsing ─────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of a JSON verdict from Gemini's response text."""
    # 1. Direct parse
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict) and "verdict" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    # 2. Markdown code fences (```json ... ``` or ``` ... ```)
    for pattern in (r"```json\s*\n(.*?)\n\s*```", r"```\s*\n(.*?)\n\s*```"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(1))
                if isinstance(obj, dict) and "verdict" in obj:
                    return obj
            except json.JSONDecodeError:
                pass

    # 3. Greedy brace match around the "verdict" key
    m = re.search(r"\{.*\"verdict\".*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    return None


def _normalise(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalise a parsed verdict dict to the Section 8.3 schema."""
    verdict = str(raw.get("verdict", "")).upper().strip()
    if verdict not in _VALID_VERDICTS:
        verdict = "INCONCLUSIVE"

    try:
        confidence = int(float(raw.get("confidence", 50)))
        confidence = max(0, min(100, confidence))
    except (TypeError, ValueError):
        confidence = 50

    summary = str(raw.get("summary", "")).strip()
    short_summary = str(raw.get("short_summary", "")).strip()
    detailed_summary = str(raw.get("detailed_summary", "")).strip()

    if not summary:
        summary = short_summary or detailed_summary or "No summary available."
    if not short_summary:
        sentences = re.split(r'(?<=[.!?])\s+', summary)
        short_summary = " ".join(sentences[:3]) if sentences else summary
    if not detailed_summary:
        detailed_summary = summary

    sources: List[Dict[str, str]] = []
    for s in (raw.get("sources") or [])[:5]:
        if isinstance(s, dict):
            name = s.get("name") or s.get("title") or s.get("source") or s.get("site") or "Source"
            url = s.get("url") or s.get("uri") or s.get("link") or ""
            if url:
                sources.append({"name": str(name).strip(), "url": str(url).strip()})

    return {
        "verdict": verdict,
        "confidence": confidence,
        "summary": summary,
        "short_summary": short_summary,
        "detailed_summary": detailed_summary,
        "sources": sources,
    }


# ── Gemini REST API call ─────────────────────────────────────────────

def _build_request_body(prompt: str, use_search: bool = False) -> Dict[str, Any]:
    """Build the Gemini REST API generateContent request body."""
    body: Dict[str, Any] = {
        "systemInstruction": {
            "parts": [{"text": _SYSTEM_INSTRUCTION}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }

    if use_search:
        body["tools"] = [{
            "googleSearchRetrieval": {
                "dynamicRetrievalConfig": {
                    "mode": "MODE_DYNAMIC",
                    "dynamicThreshold": 0.5
                }
            }
        }]

    return body


def _extract_response_text(response_json: Dict[str, Any]) -> str:
    """Pull the model's text from the REST API response."""
    try:
        candidates = response_json.get("candidates", [])
        if not candidates:
            return ""
        candidate = candidates[0]
        if candidate.get("finishReason") == "MALFORMED_FUNCTION_CALL":
            logger.warning("Gemini finished with MALFORMED_FUNCTION_CALL.")
            return ""
        parts = candidate.get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts)
    except (IndexError, KeyError, TypeError):
        return ""


async def _call_gemini(prompt: str) -> str:
    """
    Call the Gemini REST API via httpx.
    
    For a free-tier college project, we skip Google Search grounding 
    to avoid HTTP 429 Quota Exceeded errors and rapid-retry RPM blocks.
    We rely solely on gemini-3.8-flash's internal knowledge base.
    """
    import httpx
    import os

    api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("FACTFLOW_GEMINI_MODEL", GEMINI_MODEL)
    url = f"{_API_BASE}/{model}:generateContent"
    params = {"key": api_key}
    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        # 100% Free Tier safe: Ungrounded generation only
        logger.debug("Calling Gemini with plain generation (no tools) for Free Tier compatibility.")
        body = _build_request_body(prompt, use_search=False)
        response = await client.post(url, params=params, headers=headers, json=body)
        
        if response.status_code != 200:
            error_detail = response.text[:500]
            logger.error("Gemini API returned HTTP %d: %s", response.status_code, error_detail)
            raise RuntimeError(f"Gemini API HTTP {response.status_code}: {error_detail}")

        text = _extract_response_text(response.json())
        return text


# ── main entry point ─────────────────────────────────────────────────

async def get_verdict(verification_package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send the Verification Package to Gemini (Section 8) and return a
    normalised verdict dict.

    Falls back to INCONCLUSIVE when the API key is not set, the model is
    unreachable, or the response cannot be parsed after retries.
    """
    import os
    api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY is not set — returning INCONCLUSIVE.")
        return {
            **_INCONCLUSIVE_FALLBACK,
            "summary": (
                "GEMINI_API_KEY is not configured. Set the environment "
                "variable to enable real fact-checking."
            ),
        }

    user_prompt = _build_user_prompt(verification_package)

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        prompt = user_prompt
        if attempt > 1:
            prompt += (
                "\n\nIMPORTANT: Your previous response was not valid JSON. "
                "Respond with ONLY a raw JSON object, nothing else."
            )

        try:
            text = await _call_gemini(prompt)
        except Exception as exc:
            logger.warning("Gemini API call failed (attempt %d): %s", attempt, exc)
            continue

        if not text:
            logger.warning("Gemini returned empty response (attempt %d).", attempt)
            continue

        parsed = _extract_json(text)
        if parsed is None:
            logger.warning(
                "Could not parse Gemini response (attempt %d): %.500s",
                attempt, text,
            )
            continue

        return _normalise(parsed)

    logger.error(
        "All %d Gemini attempts failed — returning INCONCLUSIVE.",
        _MAX_ATTEMPTS,
    )
    return _INCONCLUSIVE_FALLBACK
