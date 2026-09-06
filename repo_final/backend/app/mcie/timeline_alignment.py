from __future__ import annotations
from typing import Dict, Any, List


def _merge_transcript(transcript: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize transcript segments into timeline events, keyed off their start time."""
    events: List[Dict[str, Any]] = []
    for seg in transcript:
        start = seg.get("start", 0.0)
        events.append({
            "type": "speech",
            "timestamp": start,
            "end": seg.get("end", start),
            "text": seg.get("text", ""),
        })
    return events


def _merge_ocr(ocr_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize OCR segments into timeline events, keyed off their frame timestamp."""
    events: List[Dict[str, Any]] = []
    for seg in ocr_segments:
        events.append({
            "type": "ocr",
            "timestamp": seg.get("frame_ts", 0.0),
            "text": seg.get("text", ""),
            "bbox": seg.get("bbox"),
        })
    return events


def _merge_keyframes(candidate_keyframes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize candidate keyframes into timeline events, keyed off their timestamp."""
    events: List[Dict[str, Any]] = []
    for kf in candidate_keyframes:
        events.append({
            "type": "keyframe",
            "timestamp": kf.get("timestamp", 0.0),
            "frame_id": kf.get("frame_id"),
            "path": kf.get("path"),
        })
    return events


async def run(preproc_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Timeline Alignment (Section 6.3).

    Speech, on-screen text, and visual content are not produced at the same
    time relative to one another. This stage places all transcript segments,
    OCR segments, and keyframe timestamps from the Section 5.5 preprocessing
    contract onto a single, chronologically-sorted timeline.

    This stage performs normalization and ordering only -- it does NOT group
    signals into windows. Grouping into Context Units is the Context
    Builder's job (context_builder.py, Section 6.3).

    Input (Section 5.5 contract):
        {
          "transcript": [{"text", "start", "end"}, ...],
          "ocr_segments": [{"text", "frame_ts", "bbox"}, ...],
          "candidate_keyframes": [{"frame_id", "timestamp", "path"}, ...]
        }

    Output:
        {
          "aligned_timeline": [
            {"type": "speech" | "ocr" | "keyframe", "timestamp": float, ...},
            ...  # sorted ascending by timestamp
          ]
        }
    """
    transcript = preproc_out.get("transcript", []) or []
    ocr_segments = preproc_out.get("ocr_segments", []) or []
    candidate_keyframes = preproc_out.get("candidate_keyframes", []) or []

    events: List[Dict[str, Any]] = []
    events.extend(_merge_transcript(transcript))
    events.extend(_merge_ocr(ocr_segments))
    events.extend(_merge_keyframes(candidate_keyframes))

    events.sort(key=lambda e: e["timestamp"])

    return {"aligned_timeline": events}
