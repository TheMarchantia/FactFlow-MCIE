"""
VPG — Metadata Attachment (Section 7.3, "Metadata Attachment").

Assembles the final Verification Package sent to the reasoning provider.
Pulls `ocr_text` / `speech_transcript` from the real Context Units built by
context_builder.py (Section 6.3) -- deduplicated and joined across every
window -- instead of the two fixed placeholder strings the stub used to
return regardless of what was actually said or shown on screen.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    """Same overlapping-window dedupe context_builder.py applies per-unit,
    applied again here across ALL units -- a caption or spoken line that
    persists across several consecutive (overlapping) windows would
    otherwise show up once per window it falls into."""
    seen = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _text_streams(context_units: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Returns (speech_transcript, ocr_text), each the deduplicated segments
    from every context unit joined into a single string, in window order."""
    speech_segments: List[str] = []
    ocr_segments: List[str] = []
    for unit in context_units:
        speech_segments.extend(unit.get("speech_segments") or [])
        ocr_segments.extend(unit.get("ocr_segments") or [])

    speech_transcript = " ".join(_dedupe_preserve_order(speech_segments))
    ocr_text = " ".join(_dedupe_preserve_order(ocr_segments))
    return speech_transcript, ocr_text


def _location_value(entities: Dict[str, Any]) -> Optional[str]:
    location = entities.get("location")
    return location.get("value") if location else None


def _date_value(entities: Dict[str, Any]) -> Optional[str]:
    date = entities.get("date")
    return date.get("resolved") if date else None


async def run(mcie_out: Dict[str, Any], query: str, ks_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assemble the full Verification Package (Section 7.3).

    `mcie_out` must include `context_units` (Context Builder's output,
    Section 6.3) for `ocr_text`/`speech_transcript` to be real -- see the
    routes.py change alongside this file that merges `cb_out` into
    `mcie_out`. If `context_units` is absent (e.g. an older caller that
    hasn't been updated), both fields fall back to empty strings rather
    than crashing or silently reintroducing the old hardcoded placeholders.
    """
    entities = mcie_out.get("entities") or {}
    context_units = mcie_out.get("context_units") or []
    speech_transcript, ocr_text = _text_streams(context_units)

    return {
        "verification_query": query,
        "claim_type": mcie_out.get("claim_type"),
        "verification_target": mcie_out.get("verification_target"),
        "explicit_claims": [c["text"] for c in mcie_out.get("explicit_claims", [])],
        "implied_claims": mcie_out.get("implied_claims", []),
        "entities": {
            "event": entities.get("event"),
            "location": _location_value(entities),
            "date": _date_value(entities),
        },
        "scene_summary": mcie_out.get("visual_context"),
        "ocr_text": ocr_text,
        "speech_transcript": speech_transcript,
        "priority_keyframes": ks_out.get("priority_keyframes"),
    }