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


def _extract_numbers(text: str) -> List[str]:
    return _NUMBER_PATTERN.findall(text)


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
            # spaCy's DATE/TIME span may or may not be one of our known
            # relative markers; only markers we recognize get resolved.
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

    # Lexical fallback / supplement: always run the temporal-marker and
    # event-noun scans, same as explicit_claim_detector.py's keyword-list
    # style, since spaCy's DATE ents don't reliably catch things like
    # "this morning" and never catch our EVENT_NOUNS at all.
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


async def run(ecd_out: Dict[str, Any], icd_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract entities from claims (Section 6.7).

    Runs spaCy NER (with a lexical fallback when the model isn't available)
    over every claim in ecd_out["explicit_claims"], then merges the results:
    list-valued fields (people/organizations/numbers) are unioned across all
    claims, and single-value fields (event/location/date) take the first
    non-null value found, in claim order. implied_claims (icd_out) is
    currently always empty upstream, so it isn't consulted yet; once
    implied_claim_detector.py is real this should fold its {"text": ...}
    entries in the same way as explicit claims.
    """
    claims = ecd_out.get("explicit_claims") or []

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