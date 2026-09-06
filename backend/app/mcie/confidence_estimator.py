"""
MCIE — Confidence Estimator (Section 6.9, "Confidence Estimator").

Produces the numeric confidence attached to a clip's structured claim
using the explicit, inspectable algorithm specified in Section 6.9, rather
than an LLM's self-reported (and poorly calibrated) confidence score:

    1. Start from a base confidence of 1.0 for the Context Unit.
    2. Cross-modal agreement check: if two modalities disagree on a field
       (e.g. speech implies "Mumbai" while OCR text reads "Delhi"), apply
       a fixed penalty to that field's confidence and flag it contested.
    3. Source-count bonus: if a field is corroborated by two or more
       modalities independently, apply a small positive adjustment.
    4. Detection-path penalty: claims detected via the LLM-assisted or
       implied-claim path start from a slightly lower base confidence than
       claims detected via the deterministic explicit rule-based layer.

The architecture doc specifies these four steps but not exact numeric
weights -- IMPLIED_PATH_BASE_PENALTY, CROSS_MODAL_DISAGREEMENT_PENALTY, and
SOURCE_COUNT_BONUS below are reasonable starting values, deliberately kept
as named module-level constants so they can be tuned during evaluation
(Section 15.2) without touching the algorithm itself.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

# --- spaCy is used for location NER in the cross-modal agreement check
# (step 2). Same try/except-at-import-time pattern as the rest of MCIE; if
# the model isn't installed, location agreement/disagreement simply can't
# be detected (see _locations_in_text) and that field contributes neither
# a penalty nor a bonus, rather than crashing the estimator.
try:
    import spacy
    _NLP = spacy.load("en_core_web_sm")
except Exception:  # pragma: no cover - exercised only when the model is missing
    _NLP = None

_LOCATION_LABELS = {"GPE", "LOC", "FAC"}

_TEMPORAL_MARKERS = (
    "yesterday", "today", "tonight", "this morning", "this afternoon",
    "this evening", "last night", "this week", "last week",
)

BASE_CONFIDENCE = 1.0

# Step 4: "slightly lower" base for implied/LLM-assisted-only detections.
# Not numerically specified in the doc.
IMPLIED_PATH_BASE_PENALTY = 0.15

# Step 2: fixed per-field penalty when two modalities disagree.
CROSS_MODAL_DISAGREEMENT_PENALTY = 0.25

# Step 3: small per-field bonus when two or more modalities agree.
SOURCE_COUNT_BONUS = 0.05


def _locations_in_text(text: str) -> Set[str]:
    if not text or _NLP is None:
        return set()
    doc = _NLP(text)
    return {ent.text for ent in doc.ents if ent.label_ in _LOCATION_LABELS}


def _temporal_markers_in_text(text: str) -> Set[str]:
    if not text:
        return set()
    lowered = text.lower()
    return {marker for marker in _TEMPORAL_MARKERS if marker in lowered}


def _check_field_agreement(speech_values: Set[str], ocr_values: Set[str]) -> Optional[bool]:
    """
    True if both modalities mention this field and share at least one
    value (corroborated); False if both mention it and share none
    (contested); None if fewer than two modalities said anything about
    this field at all -- nothing to corroborate or contest either way.
    """
    if not speech_values or not ocr_values:
        return None
    return bool(speech_values & ocr_values)


def _cross_modal_check(context_units: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """
    Scans every Context Unit's speech text vs. OCR text independently for
    location and temporal-marker (date) signals, pooled across the whole
    clip, and checks whether the two modalities agree wherever both have
    something to say. A field lands in at most one of the two returned
    lists.

    Returns (contested_fields, corroborated_fields).
    """
    speech_locations: Set[str] = set()
    ocr_locations: Set[str] = set()
    speech_dates: Set[str] = set()
    ocr_dates: Set[str] = set()

    for unit in context_units:
        speech_text = " ".join(unit.get("speech_segments") or [])
        ocr_text = " ".join(unit.get("ocr_segments") or [])
        speech_locations |= _locations_in_text(speech_text)
        ocr_locations |= _locations_in_text(ocr_text)
        speech_dates |= _temporal_markers_in_text(speech_text)
        ocr_dates |= _temporal_markers_in_text(ocr_text)

    contested: List[str] = []
    corroborated: List[str] = []

    location_agreement = _check_field_agreement(speech_locations, ocr_locations)
    if location_agreement is True:
        corroborated.append("location")
    elif location_agreement is False:
        contested.append("location")

    date_agreement = _check_field_agreement(speech_dates, ocr_dates)
    if date_agreement is True:
        corroborated.append("date")
    elif date_agreement is False:
        contested.append("date")

    return contested, corroborated


def _detection_path(ecd_out: Dict[str, Any], icd_out: Dict[str, Any]) -> str:
    """
    "explicit" if any claim came from the deterministic rule-based layer
    (Section 6.5.1); "implied_only" if the only claim(s) available came
    from the LLM-assisted / implied-claim path (Section 6.5.2 / 6.6);
    "none" if there's no detected claim at all.
    """
    if ecd_out.get("explicit_claims"):
        return "explicit"
    if icd_out.get("implied_claims"):
        return "implied_only"
    return "none"


async def run(cb_out: Dict[str, Any], ecd_out: Dict[str, Any], icd_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Estimate confidence for this clip's structured claim (Section 6.9).

    `cb_out` (Context Builder output, Section 6.3) is required for step 2/3:
    the cross-modal agreement check needs each Context Unit's speech and
    OCR text kept separate, which the already-merged claim text in
    ecd_out no longer preserves once a unit's signals are combined into
    one claim string.
    """
    context_units = cb_out.get("context_units") or []

    detection_path = _detection_path(ecd_out, icd_out)
    if detection_path == "none":
        # Nothing was detected at all -- there is no claim to be
        # confident or unconfident about.
        return {
            "confidence": 0.0,
            "factors": {
                "detection_path": detection_path,
                "detection_path_penalty": 0.0,
                "contested_fields": [],
                "corroborated_fields": [],
                "cross_modal_penalty": 0.0,
                "source_count_bonus": 0.0,
            },
        }

    detection_path_penalty = -IMPLIED_PATH_BASE_PENALTY if detection_path == "implied_only" else 0.0
    base = BASE_CONFIDENCE + detection_path_penalty

    contested_fields, corroborated_fields = _cross_modal_check(context_units)
    cross_modal_penalty = -CROSS_MODAL_DISAGREEMENT_PENALTY * len(contested_fields)
    source_count_bonus = SOURCE_COUNT_BONUS * len(corroborated_fields)

    confidence = max(0.0, min(1.0, base + cross_modal_penalty + source_count_bonus))

    return {
        "confidence": confidence,
        "factors": {
            "detection_path": detection_path,
            "detection_path_penalty": detection_path_penalty,
            "contested_fields": contested_fields,
            "corroborated_fields": corroborated_fields,
            "cross_modal_penalty": cross_modal_penalty,
            "source_count_bonus": source_count_bonus,
        },
    }