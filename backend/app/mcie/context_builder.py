import re
from typing import Dict, Any, List, Optional

# Section 6.3 defaults: 4-second window width, 2-second stride. Configurable
# here rather than hardcoded inline so a future tuning pass doesn't have to
# hunt through the windowing loop for magic numbers.
WINDOW_WIDTH_SEC: float = 4.0
WINDOW_STRIDE_SEC: float = 2.0

# Hard cap on the number of windows generated, purely as a safety net against
# a pathological/malformed timeline (e.g. a single wildly out-of-range
# timestamp) turning into a runaway loop.
_MAX_WINDOWS = 10_000

# Social media UI noise tokens commonly caught by OCR on Reels / Shorts / TikTok
_UI_NOISE_TOKENS = {
    "subscribe", "subscribed", "subscriber", "subscribers",
    "share", "shared", "remix", "remixed",
    "like", "likes", "liked", "dislike", "dislikes",
    "comment", "comments", "commented",
    "save", "saved", "follow", "following",
    "shorts", "subscriptions", "views", "viewers",
    "reels", "tiktok", "instagram", "youtube",
    "for you", "fyp", "tap to view", "swipe up", "link in bio",
}

_UI_NOISE_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d+)?[kmb]?\s*(?:likes?|views?|shares?|comments?|subscribers?)|"
    r"subscribe|share|remix|save|follow(?:\s+for\s+more)?|shorts|subscriptions)$",
    re.IGNORECASE,
)

# Android top status bar, clock, battery, and recording overlay chrome
_STATUS_CHROME_PATTERN = re.compile(
    r"^(?:"
    r"\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?|"   # 11:34, 00:04, 2:25, 4:59 pm
    r"[od]?\s*rec|"                             # REC, D REC, O REC
    r"rec|"                                     # REC
    r"\d{1,3}%|"                                # 0%, 85%, 100%
    r"[o0]?\s*\d+\s*aqi|"                       # O105AQI, 105 AQI
    r"[0-9]+(?:\.[0-9]+)?\s*(?:k|m|g)?b/s|"    # 12.5 kb/s
    r"\d+:\d+\s*/\s*\d+:\d+|"                  # 00:04 / 04:59
    r"[1-5]g|lte|wifi|volte|"                   # 5G, 4G, LTE, WiFi, VoLTE
    r"gold\s*[-+]?\d+(?:\.\d+)?%?"             # GOLD -0.78%
    r")$",
    re.IGNORECASE,
)


def _is_screen_boundary_chrome(bbox: Optional[List[float]], text: str) -> bool:
    """Detect if an OCR bounding box is located in the device status bar or bottom navigation bar."""
    if not bbox or len(bbox) != 4:
        return False
    _x_min, y_min, _x_max, y_max = bbox
    clean = re.sub(r"[^\w%:/.-]", "", text).strip().lower()
    has_status_hint = bool(_STATUS_CHROME_PATTERN.match(clean) or clean in _UI_NOISE_TOKENS or any(c.isdigit() for c in clean))

    # Normalized coordinates (0.0 - 1.0)
    if 0.0 <= y_max <= 1.0:
        if (y_max <= 0.065 or y_min >= 0.94) and has_status_hint:
            return True
    # Pixel coordinates on tall screens
    elif (y_max <= 120 or y_min >= 2250) and has_status_hint:
        return True
    return False


def _has_status_chrome_density(text: str) -> bool:
    """Detect lines that are predominantly Android status bar tokens."""
    tokens = text.strip().split()
    if not tokens:
        return False
    status_matches = 0
    for tok in tokens:
        clean_tok = re.sub(r"[^\w%:/.-]", "", tok).lower()
        if not clean_tok:
            continue
        if _STATUS_CHROME_PATTERN.match(clean_tok) or clean_tok in {
            "google", "rec", "aqi", "gold", "am", "pm", "dhavarpada", "sur"
        }:
            status_matches += 1
    return (status_matches / len(tokens)) >= 0.45


def _is_ui_noise(text: str, bbox: Optional[List[float]] = None) -> bool:
    clean = re.sub(r"[^\w\s%:/.-]", "", text).strip().lower()
    if not clean:
        return True
    if _is_screen_boundary_chrome(bbox, text):
        return True
    if clean in _UI_NOISE_TOKENS:
        return True
    if _UI_NOISE_PATTERN.match(clean):
        return True
    if _STATUS_CHROME_PATTERN.match(clean):
        return True
    if _has_status_chrome_density(text):
        return True
    return False


def _clean_token(t: str) -> str:
    return re.sub(r"[^\w]", "", t).lower()


def _merge_overlap(prev_text: str, next_text: str) -> Optional[str]:
    p_strip = prev_text.strip()
    n_strip = next_text.strip()
    p_lower = p_strip.lower()
    n_lower = n_strip.lower()

    if not p_strip or not n_strip:
        return p_strip or n_strip

    # Substring containment (e.g. progressive subtitles)
    if n_lower in p_lower:
        return p_strip
    if p_lower in n_lower:
        return n_strip

    w1 = p_strip.split()
    w2 = n_strip.split()
    if not w1 or not w2:
        return None

    w1_clean = [_clean_token(w) for w in w1]
    w2_clean = [_clean_token(w) for w in w2]

    max_k = min(len(w1), len(w2))
    for k in range(max_k, 0, -1):
        if w1_clean[-k:] == w2_clean[:k]:
            remaining_w2 = w2[k:]
            if remaining_w2:
                return f"{p_strip} {' '.join(remaining_w2)}"
            return p_strip

    return None


def _should_join_fragments(prev_text: str, next_text: str, ts_diff: float) -> bool:
    if ts_diff > 1.8:
        return False
    if prev_text.rstrip().endswith((".", "!", "?", ";", ":")):
        return False
    w1 = prev_text.strip().split()
    w2 = next_text.strip().split()
    if len(w1) <= 4 and len(w2) <= 4:
        return True
    if w2 and (w2[0].islower() or w2[0].lower() in {
        "in", "on", "at", "to", "for", "with", "by", "from", "and", "but", "or", "is", "was", "are", "were", "that", "which"
    }):
        return True
    return False


def _same_vertical_zone(b1: Optional[List[float]], b2: Optional[List[float]]) -> bool:
    if not b1 or not b2 or len(b1) != 4 or len(b2) != 4:
        return True
    y_min1, y_max1 = b1[1], b1[3]
    y_min2, y_max2 = b2[1], b2[3]

    overlap = min(y_max1, y_max2) - max(y_min1, y_min2)
    h1 = max(1.0, y_max1 - y_min1)
    h2 = max(1.0, y_max2 - y_min2)

    if overlap > 0:
        return True
    c1 = (y_min1 + y_max1) / 2.0
    c2 = (y_min2 + y_max2) / 2.0
    return abs(c1 - c2) <= max(h1, h2) * 1.5


def _stitch_ocr_events(raw_events: List[Dict[str, Any]]) -> List[str]:
    valid_events = []
    for ev in raw_events:
        text = ev.get("text", "").strip()
        bbox = ev.get("bbox")
        if not text or _is_ui_noise(text, bbox):
            continue
        valid_events.append(ev)

    if not valid_events:
        return []

    valid_events.sort(key=lambda x: x.get("timestamp", 0.0))

    stitched: List[Dict[str, Any]] = []
    for ev in valid_events:
        curr_text = ev["text"].strip()
        curr_ts = ev.get("timestamp", 0.0)
        curr_bbox = ev.get("bbox")

        merged = False
        for prev in reversed(stitched):
            if not _same_vertical_zone(prev.get("bbox"), curr_bbox):
                continue
            ts_diff = abs(curr_ts - prev["timestamp"])
            overlap_res = _merge_overlap(prev["text"], curr_text)
            if overlap_res is not None:
                prev["text"] = overlap_res
                prev["timestamp"] = curr_ts
                if curr_bbox:
                    prev["bbox"] = curr_bbox
                merged = True
                break

            if _should_join_fragments(prev["text"], curr_text, ts_diff):
                prev["text"] = f"{prev['text']} {curr_text}"
                prev["timestamp"] = curr_ts
                if curr_bbox:
                    prev["bbox"] = curr_bbox
                merged = True
                break

        if not merged:
            stitched.append({
                "text": curr_text,
                "timestamp": curr_ts,
                "bbox": curr_bbox,
            })

    # Substring pruning & deduplication preserving order
    candidates = [item["text"].strip() for item in stitched if item["text"].strip()]
    final_texts: List[str] = []
    for i, c in enumerate(candidates):
        c_lower = c.lower()
        if any(i != j and c_lower in candidates[j].lower() for j in range(len(candidates))):
            continue
        if c not in final_texts:
            final_texts.append(c)

    return final_texts


def _dedupe_preserve_order(items: List[str]) -> List[str]:
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
    each window. Subtitle text fragments across consecutive frames are
    intelligently stitched to form full sentences, and social media UI noise
    is filtered.
    """
    events: List[Dict[str, Any]] = ta_out.get("aligned_timeline", []) or []

    if not events:
        return {"context_units": []}

    timestamps = [e.get("timestamp", 0.0) for e in events]
    min_ts = min(timestamps)
    max_ts = max(timestamps)

    current_start = max(0.0, min_ts - WINDOW_WIDTH_SEC / 2)
    context_units: List[Dict[str, Any]] = []
    windows_built = 0

    while current_start <= max_ts and windows_built < _MAX_WINDOWS:
        current_end = current_start + WINDOW_WIDTH_SEC
        windows_built += 1

        speech_segments: List[str] = []
        raw_ocr_events: List[Dict[str, Any]] = []
        keyframe_refs: List[str] = []

        for event in events:
            ts = event.get("timestamp", 0.0)
            if not (current_start <= ts < current_end):
                continue

            event_type = event.get("type")
            if event_type == "speech" and event.get("text"):
                speech_segments.append(event["text"])
            elif event_type == "ocr" and event.get("text"):
                raw_ocr_events.append(event)
            elif event_type == "keyframe" and event.get("frame_id"):
                keyframe_refs.append(event["frame_id"])

        speech_segments = _dedupe_preserve_order(speech_segments)
        ocr_segments = _stitch_ocr_events(raw_ocr_events)
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
