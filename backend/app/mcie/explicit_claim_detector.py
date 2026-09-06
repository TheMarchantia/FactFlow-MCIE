from __future__ import annotations
from typing import Dict, Any, List, Tuple
import re

# --- spaCy is used for named-entity recognition inside the event+entity
# pattern. It's loaded once at import time; if the model isn't installed in
# a given environment we fall back to a lexical-only version of that one
# pattern rather than crashing the whole pipeline (see _has_event_entity_pattern).
try:
    import spacy
    _NLP = spacy.load("en_core_web_sm")
except Exception:  # pragma: no cover - exercised only when the model is missing
    _NLP = None

# Section 6.5.1: "temporal-marker patterns" -- explicit relative/absolute
# time references that make a statement checkable against a specific date.
_TEMPORAL_MARKERS = (
    "yesterday", "today", "tonight", "this morning", "this afternoon",
    "this evening", "last night", "this week", "last week",
)

# Section 6.5.1: "named-entity-plus-event patterns" -- event nouns that,
# combined with a recognized entity (place/org/person), indicate a checkable
# event claim (e.g. "Flood in Mumbai").
_EVENT_NOUNS = (
    "flood", "floods", "flooding", "earthquake", "protest", "protests",
    "fire", "explosion", "riot", "riots", "attack", "storm", "cyclone",
    "landslide", "collapse", "outbreak", "shooting", "crash",
)

# Section 6.5.1: "numeric assertions" -- a number attached to a unit/outcome
# word, e.g. "6.2 magnitude", "50 people killed".
_UNIT_WORDS = (
    "magnitude", "percent", "%", "people", "killed", "dead", "injured",
    "degrees", "degree", "km", "kg", "meters", "metres", "feet", "richter",
    "casualties",
)
_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")


def _has_temporal_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _TEMPORAL_MARKERS)


def _has_numeric_assertion(text: str) -> bool:
    """A bare number isn't a claim; a number next to a unit/outcome word,
    or alongside an event noun (e.g. "the earthquake measured 6.2"), is."""
    if not _NUMBER_PATTERN.search(text):
        return False
    lowered = text.lower()
    has_unit_word = any(unit in lowered for unit in _UNIT_WORDS)
    has_event_word = any(event in lowered for event in _EVENT_NOUNS)
    return has_unit_word or has_event_word


def _has_event_entity_pattern(text: str) -> Tuple[bool, List[str]]:
    """
    Named-entity-plus-event pattern (Section 6.5.1): an event noun
    co-occurring with a location/org/person entity, e.g. "Flood in Mumbai".

    Falls back to a lexical-only check (event noun present, entity check
    skipped) if the spaCy model isn't available in this environment, so the
    detector degrades gracefully rather than failing outright.
    """
    lowered = text.lower()
    found_events = [word for word in _EVENT_NOUNS if word in lowered]
    if not found_events:
        return False, []

    if _NLP is None:
        return True, found_events

    doc = _NLP(text)
    has_entity = any(
        ent.label_ in {"GPE", "LOC", "ORG", "PERSON", "FAC"} for ent in doc.ents
    )
    return has_entity, found_events


def _claim_source(unit: Dict[str, Any]) -> str:
    has_speech = bool(unit.get("speech_segments"))
    has_ocr = bool(unit.get("ocr_segments"))
    if has_speech and has_ocr:
        return "asr+ocr"
    if has_speech:
        return "asr"
    if has_ocr:
        return "ocr"
    return "unknown"


def _detect_claims_in_unit(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    speech_text = " ".join(unit.get("speech_segments", []))
    ocr_text = " ".join(unit.get("ocr_segments", []))
    combined = " ".join(t for t in (speech_text, ocr_text) if t).strip()

    if not combined:
        return []

    numeric = _has_numeric_assertion(combined)
    event_pattern, _event_words = _has_event_entity_pattern(combined)
    temporal = _has_temporal_marker(combined)

    # Confidence here is a fixed, deterministic value per matched pattern --
    # NOT a model self-reported score. The Confidence Estimator (Section 6.9,
    # out of scope for this task) is what combines/adjusts these later.
    if numeric:
        confidence = 0.8
    elif event_pattern and temporal:
        confidence = 0.85
    elif event_pattern:
        confidence = 0.6
    else:
        # No confident, explicitly-stated claim in this unit. This is the
        # correct outcome for context units where the claim only exists at
        # the intersection of text AND visual content (Section 6.3's running
        # example) -- that case is handled by Implied Claim Detection
        # (Section 6.6) and the LLM-assisted layer (Section 6.5.2), neither
        # of which are in scope for this rule-based-only stage.
        return []

    return [{
        "text": combined,
        "source": _claim_source(unit),
        "confidence": confidence,
    }]


async def run(cb_out: Dict[str, Any], vc_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Explicit Claim Detection -- RULE-BASED LAYER ONLY (Section 6.5.1).

    For each Context Unit, runs deterministic pattern matching (numeric
    assertions, event-noun + named-entity co-occurrence, temporal markers)
    against the unit's combined speech + OCR text using spaCy for entity
    recognition. This layer makes no LLM/API calls and is fully
    deterministic and testable.

    The LLM-assisted layer (Section 6.5.2), which handles claims that are
    contextually implied rather than explicitly phrased ("Look what
    happened here"), is intentionally NOT implemented here -- claims this
    rule-based layer doesn't confidently classify are simply omitted rather
    than guessed at.

    `vc_out` (the visual scene description from Visual Context
    Understanding, Section 6.4) is accepted for interface compatibility
    with the rest of the pipeline but is deliberately unused here: per the
    architecture document, only the LLM-assisted layer and Implied Claim
    Detection consult visual context. A Context Unit whose claim only
    exists at the intersection of text and visual content (e.g. the
    document's running "this happened yesterday" + "Mumbai" + flood-footage
    example) will correctly yield no explicit claim from this layer alone.

    Output:
        {"explicit_claims": [{"text", "source", "confidence"}, ...]}

    Because Context Units are overlapping windows (Section 6.3), a single
    signal frequently falls inside two or more consecutive windows, which
    would otherwise surface the identical claim multiple times. The final
    (text, source) pairs are deduplicated here -- this is a windowing
    artifact to correct, not a case of the same claim being independently
    corroborated by different context.
    """
    context_units = cb_out.get("context_units", []) or []

    explicit_claims: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for unit in context_units:
        for claim in _detect_claims_in_unit(unit):
            key = (claim["text"], claim["source"])
            if key in seen:
                continue
            seen.add(key)
            explicit_claims.append(claim)

    return {"explicit_claims": explicit_claims}
