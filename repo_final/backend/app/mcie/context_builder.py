from __future__ import annotations
from typing import Dict, Any, List

# Section 6.3 defaults: 4-second window width, 2-second stride. Configurable
# here rather than hardcoded inline so a future tuning pass doesn't have to
# hunt through the windowing loop for magic numbers.
WINDOW_WIDTH_SEC: float = 4.0
WINDOW_STRIDE_SEC: float = 2.0

# Hard cap on the number of windows generated, purely as a safety net against
# a pathological/malformed timeline (e.g. a single wildly out-of-range
# timestamp) turning into a runaway loop.
_MAX_WINDOWS = 10_000


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    """
    Remove exact-duplicate strings while preserving first-seen order.

    This is what implements Section 6.3's requirement that a persistent
    on-screen caption spanning several overlapping windows is not treated
    as multiple independent signals within a single Context Unit -- if the
    same OCR text (or, less commonly, the same transcript line) appears
    more than once inside one window, it is folded down to a single entry.
    """
    seen = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


async def run(ta_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Context Builder (Section 6.3).

    Divides the aligned timeline produced by Timeline Alignment into
    overlapping Context Units of width WINDOW_WIDTH_SEC with a stride of
    WINDOW_STRIDE_SEC, grouping every signal whose timestamp falls inside
    each window. A persistent caption/text that appears in more than one
    overlapping window is deduplicated per unit rather than counted as a
    fresh signal each time.

    Input:
        {"aligned_timeline": [{"type", "timestamp", ...}, ...]}  (from
        timeline_alignment.run)

    Output:
        {
          "context_units": [
            {
              "window_start": float,
              "window_end": float,
              "speech_segments": [str, ...],
              "ocr_segments": [str, ...],
              "keyframe_refs": [str, ...]
            },
            ...
          ]
        }

    Windows with no signals at all are omitted from the output -- an empty
    Context Unit carries no information for downstream claim detection.
    """
    events: List[Dict[str, Any]] = ta_out.get("aligned_timeline", []) or []

    if not events:
        return {"context_units": []}

    timestamps = [e.get("timestamp", 0.0) for e in events]
    min_ts = min(timestamps)
    max_ts = max(timestamps)

    # Start the first window so it fully covers the earliest signal, rather
    # than starting exactly at min_ts (which would leave anything slightly
    # before the window's centre outside every window).
    current_start = max(0.0, min_ts - WINDOW_WIDTH_SEC / 2)

    context_units: List[Dict[str, Any]] = []
    windows_built = 0

    while current_start <= max_ts and windows_built < _MAX_WINDOWS:
        current_end = current_start + WINDOW_WIDTH_SEC
        windows_built += 1

        speech_segments: List[str] = []
        ocr_segments: List[str] = []
        keyframe_refs: List[str] = []

        for event in events:
            ts = event.get("timestamp", 0.0)
            if not (current_start <= ts < current_end):
                continue

            event_type = event.get("type")
            if event_type == "speech" and event.get("text"):
                speech_segments.append(event["text"])
            elif event_type == "ocr" and event.get("text"):
                ocr_segments.append(event["text"])
            elif event_type == "keyframe" and event.get("frame_id"):
                keyframe_refs.append(event["frame_id"])

        speech_segments = _dedupe_preserve_order(speech_segments)
        ocr_segments = _dedupe_preserve_order(ocr_segments)
        keyframe_refs = _dedupe_preserve_order(keyframe_refs)

        if speech_segments or ocr_segments or keyframe_refs:
            context_units.append({
                "window_start": current_start,
                "window_end": current_end,
                "speech_segments": speech_segments,
                "ocr_segments": ocr_segments,
                "keyframe_refs": keyframe_refs,
            })

        current_start += WINDOW_STRIDE_SEC

    return {"context_units": context_units}
