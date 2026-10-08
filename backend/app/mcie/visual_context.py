"""
Visual Context Understanding (Section 6.4, "Visual Context Understanding").

Interprets representative video keyframes using Gemini Vision to generate
factual, open-vocabulary scene descriptions. These descriptions provide the
visual grounding used by Explicit Claim Detection, Implied Claim Detection,
and the downstream Verification Package Generator.

Configuration (environment variables):
    GEMINI_API_KEY         — required for live vision calls; falls back to
                             graceful placeholder if not set
    FACTFLOW_VISION_MODEL  — vision model name (default: gemini-3.6-flash)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
VISION_MODEL = os.getenv(
    "FACTFLOW_VISION_MODEL",
    os.getenv("FACTFLOW_GEMINI_MODEL", "gemini-flash-lite-latest"),
)
_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_TIMEOUT_SECONDS = 45.0

# Section 6.4 specifies selecting only the most representative frame
# (or top-2 if spanning scene changes) to control latency and API quota.
MAX_FRAMES_TO_DESCRIBE = 1

_PROMPT = (
    "Describe the visual scene in this video keyframe in 1-2 concise, objective "
    "sentences for factual verification. Focus on the main subject, setting, "
    "visible objects, actions, and any identifiable landmarks or environment. "
    "Do not speculate or add meta-commentary."
)


def _load_and_encode_image(image_path: str | Path) -> Optional[str]:
    """Read an image file and return its base64-encoded string."""
    try:
        p = Path(image_path).expanduser().resolve()
        if not p.is_file() or p.stat().st_size == 0:
            return None
        data = p.read_bytes()
        return base64.b64encode(data).decode("utf-8")
    except Exception as exc:
        logger.warning("Failed to read image %s: %r", image_path, exc)
        return None


async def _describe_single_frame(
    frame_path: str,
    frame_id: str,
    client: Any,
) -> Optional[Dict[str, str]]:
    """Send a single keyframe to Gemini Vision and return its description."""
    b64_data = _load_and_encode_image(frame_path)
    if not b64_data:
        return None

    api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None

    model = os.getenv("FACTFLOW_VISION_MODEL", os.getenv("FACTFLOW_GEMINI_MODEL", VISION_MODEL))
    url = f"{_API_BASE}/{model}:generateContent"
    params = {"key": api_key}
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": _PROMPT},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": b64_data,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024,
        },
    }

    try:
        resp = await client.post(url, params=params, headers=headers, json=body)
        if resp.status_code != 200:
            logger.warning(
                "Gemini Vision call for frame %s returned HTTP %d: %.200s",
                frame_id,
                resp.status_code,
                resp.text,
            )
            return None

        res_json = resp.json()
        candidates = res_json.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        description = "".join(part.get("text", "") for part in parts).strip()
        if description:
            return {"frame_id": frame_id, "description": description}
    except Exception as exc:
        logger.warning("Gemini Vision call failed for frame %s: %r", frame_id, exc)

    return None


def _select_representative_keyframes(
    candidate_keyframes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Select representative keyframes.

    Per Section 6.4, picks the most representative frame(s) to avoid
    redundant costly vision calls on near-duplicate frames.
    """
    valid = [
        kf for kf in candidate_keyframes
        if kf.get("path") and Path(kf["path"]).is_file()
    ]
    if not valid:
        return []

    if len(valid) <= MAX_FRAMES_TO_DESCRIBE:
        return valid

    # Pick representative frame near the middle (e.g. index len//2)
    step = len(valid) / MAX_FRAMES_TO_DESCRIBE
    indices = [int(i * step) for i in range(MAX_FRAMES_TO_DESCRIBE)]
    return [valid[i] for i in indices]


async def run(
    cb_out: Dict[str, Any],
    preproc_out: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Visual Context Understanding (Section 6.4).

    Inspects representative keyframes from the preprocessing stage using
    Gemini Vision, generating structured per-frame scene descriptions and
    an aggregated visual context summary.

    Gracefully falls back when GEMINI_API_KEY is unset, no keyframes exist,
    or during tests where preproc_out is omitted.

    Output:
        {
            "visual_descriptions": [
                {"frame_id": "kf_01", "description": "..."},
                ...
            ],
            "visual_context": "Aggregated summary of visual scene."
        }
    """
    candidate_keyframes = []
    if preproc_out:
        candidate_keyframes = preproc_out.get("candidate_keyframes", []) or []

    representative_frames = _select_representative_keyframes(candidate_keyframes)

    api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")

    # If no keyframes or API key is missing, return a graceful neutral description
    if not representative_frames or not api_key:
        if not api_key and representative_frames:
            logger.info("GEMINI_API_KEY unset; visual context running in placeholder mode.")
        return {
            "visual_descriptions": [
                {
                    "frame_id": kf.get("frame_id", f"kf_{i+1:02d}"),
                    "description": "Video keyframe footage.",
                }
                for i, kf in enumerate(representative_frames)
            ] or [
                {
                    "frame_id": "kf_01",
                    "description": "Video footage.",
                }
            ],
            "visual_context": "Video footage.",
        }

    import httpx

    visual_descriptions: List[Dict[str, str]] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        for kf in representative_frames:
            desc = await _describe_single_frame(
                frame_path=kf["path"],
                frame_id=kf["frame_id"],
                client=client,
            )
            if desc and desc.get("description"):
                visual_descriptions.append(desc)

    if not visual_descriptions:
        return {
            "visual_descriptions": [
                {"frame_id": "kf_01", "description": "Video footage."}
            ],
            "visual_context": "Video footage.",
        }

    # Aggregate descriptions into a unified visual context summary
    aggregated_context = " ".join(item["description"] for item in visual_descriptions)

    return {
        "visual_descriptions": visual_descriptions,
        "visual_context": aggregated_context,
    }
