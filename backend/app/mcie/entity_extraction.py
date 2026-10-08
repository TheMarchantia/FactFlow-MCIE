"""
MCIE — Entity Extraction (Section 6.7, "Entity Extraction").

Pulls locations, dates, people, organizations, event nouns, and numbers out
of the claims produced upstream by explicit_claim_detector.py (Section 6.5.1)
and, once populated, implied_claim_detector.py. Downstream (VPG /
metadata_attachment.py, Section 6.8+) reads `entities.location.value` and
`entities.date.resolved` directly, so those two nested fields must keep
their exact shape.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# --- spaCy is used for named-entity recognition (people/orgs/locations/dates).
# It's loaded once at import time; if the model isn't installed in a given
# environment we fall back to a lexical-only path (temporal markers + event
# nouns + regex numbers) rather than crashing the whole pipeline, matching
# explicit_claim_detector.py's pattern.
try:
    import spacy
    _NLP = spacy.load("en_core_web_sm")
except Exception:  # pragma: no cover - exercised only when the model is missing
    _NLP = None

_TEMPORAL_MARKERS = (
    "yesterday", "today", "tonight", "this morning", "this afternoon",
    "this evening", "last night", "this week", "last week",
)

_EVENT_NOUNS = (
    "flood", "floods", "flooding", "earthquake", "protest", "protests",
    "fire", "explosion", "riot", "riots", "attack", "storm", "cyclone",
    "landslide", "collapse", "outbreak", "shooting", "crash",
)

_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")

_LOCATION_LABELS = {"GPE", "LOC", "FAC"}
_DATE_LABELS = {"DATE", "TIME"}

# Relative-marker -> day offset from the reference "now". Only the markers
# we can unambiguously map to a single calendar day are resolved here;
# vaguer ones (e.g. "this week") are left with resolved=None.
_RELATIVE_DAY_OFFSETS = {
    "yesterday": -1,
    "today": 0,
    "tonight": 0,
    "this morning": 0,
    "this afternoon": 0,
    "this evening": 0,
    "last night": -1,
}


def _find_event(text: str) -> Optional[str]:
    lowered = text.lower()
    for word in _EVENT_NOUNS:
        if word in lowered:
            return word
    return None


def _find_temporal_marker(text: str) -> Optional[str]:
    lowered = text.lower()
    for marker in _TEMPORAL_MARKERS:
        if marker in lowered:
            return marker
    return None


def _resolve_relative_date(marker: str) -> Optional[str]:
    # NOTE: this function only receives ecd_out/icd_out, not the clip's
    # actual upload timestamp, so we resolve relative to "now" (UTC) rather
    # than the moment the clip was captured. A more correct version would
    # thread the clip's real `uploaded_at` through routes.py -> run() in a
    # future pass.
    offset = _RELATIVE_DAY_OFFSETS.get(marker)
    if offset is None:
        return None
    resolved_dt = datetime.now(timezone.utc) + timedelta(days=offset)
    return resolved_dt.date().isoformat()


# Regex to match standalone clock times (11:34, 4:59, 00:04) so they are not treated as factual figures
_CLOCK_PATTERN = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?\b", re.IGNORECASE)
_RESOLUTION_PATTERN = re.compile(r"\b\d{3,4}p\b", re.IGNORECASE)
_SUBSTANTIVE_NUMBER_PATTERN = re.compile(
    r"\b\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:billion|billions|million|millions|trillion|percent|%|dollars?|usd|deaths?|killed|people))?\b",
    re.IGNORECASE,
)


def _extract_numbers(text: str) -> List[str]:
    # 1. Mask out clocks and video resolution labels
    cleaned = _CLOCK_PATTERN.sub(" ", text)
    cleaned = _RESOLUTION_PATTERN.sub(" ", cleaned)

    matches = _SUBSTANTIVE_NUMBER_PATTERN.findall(cleaned)
    results: List[str] = []
    for m in matches:
        m_str = m.strip()
        if not m_str:
            continue
        # Skip lone small digits (e.g. '0', '4', '6') that are usually UI remnants unless accompanied by units
        if m_str.isdigit() and len(m_str) == 1:
            continue
        results.append(m_str)
    return results


def _extract_with_spacy(text: str) -> Tuple[
    Optional[str], List[str], List[str], Optional[Tuple[str, Optional[str]]]
]:
    """Returns (location_value, people, organizations, (date_value, date_resolved))."""
    doc = _NLP(text)

    location_value: Optional[str] = None
    people: List[str] = []
    organizations: List[str] = []
    date_pair: Optional[Tuple[str, Optional[str]]] = None

    for ent in doc.ents:
        if location_value is None and ent.label_ in _LOCATION_LABELS:
            location_value = ent.text
        elif ent.label_ == "PERSON":
            people.append(ent.text)
        elif ent.label_ == "ORG":
            organizations.append(ent.text)
        elif date_pair is None and ent.label_ in _DATE_LABELS:
            marker = _find_temporal_marker(ent.text) or ent.text.lower()
            date_pair = (marker, _resolve_relative_date(marker))

    return location_value, people, organizations, date_pair


def _extract_claim_entities(text: str) -> Dict[str, Any]:
    """Extract the per-claim entity fields (before cross-claim aggregation)."""
    people: List[str] = []
    organizations: List[str] = []
    location_value: Optional[str] = None
    date_pair: Optional[Tuple[str, Optional[str]]] = None

    if _NLP is not None:
        location_value, people, organizations, date_pair = _extract_with_spacy(text)

    if date_pair is None:
        marker = _find_temporal_marker(text)
        if marker is not None:
            date_pair = (f"relative:{marker}", _resolve_relative_date(marker))

    event = _find_event(text)
    numbers = _extract_numbers(text)

    return {
        "event": event,
        "location": {"value": location_value, "source": None} if location_value else None,
        "date": (
            {"value": date_pair[0], "resolved": date_pair[1], "source": None}
            if date_pair is not None
            else None
        ),
        "people": people,
        "organizations": organizations,
        "numbers": numbers,
    }


async def run(
    ecd_out: Dict[str, Any],
    icd_out: Dict[str, Any],
    primary_claim: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Extract entities from claims (Section 6.7).

    Runs spaCy NER (with a lexical fallback when the model isn't available).
    If a primary_claim is provided (from Claim Arbitrator), its entities take
    highest priority to ensure downstream queries focus cleanly on the verified target.
    """
    claims: List[Dict[str, Any]] = []
    if primary_claim and primary_claim.get("text"):
        claims.append(primary_claim)

    for c in (ecd_out.get("explicit_claims") or []):
        if c not in claims:
            claims.append(c)
    for c in (icd_out.get("implied_claims") or []):
        if c not in claims:
            claims.append(c)

    event: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    date: Optional[Dict[str, Any]] = None
    people: List[str] = []
    organizations: List[str] = []
    numbers: List[str] = []

    for claim in claims:
        text = claim.get("text", "")
        source = claim.get("source", "unknown")
        if not text:
            continue

        extracted = _extract_claim_entities(text)

        if event is None and extracted["event"] is not None:
            event = extracted["event"]

        if location is None and extracted["location"] is not None:
            location = {"value": extracted["location"]["value"], "source": source}

        if date is None and extracted["date"] is not None:
            date = {
                "value": extracted["date"]["value"],
                "resolved": extracted["date"]["resolved"],
                "source": source,
            }

        people.extend(extracted["people"])
        organizations.extend(extracted["organizations"])
        numbers.extend(extracted["numbers"])

    # Union while preserving first-seen order (dict.fromkeys dedupes).
    people = list(dict.fromkeys(people))
    organizations = list(dict.fromkeys(organizations))
    numbers = list(dict.fromkeys(numbers))

    return {
        "entities": {
            "event": event,
            "location": location,
            "date": date,
            "people": people,
            "organizations": organizations,
            "numbers": numbers,
        }
    }