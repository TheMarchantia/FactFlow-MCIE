"""
VPG — Query Generation (Section 7.1, "Query Generation").

Builds the natural-language verification_query that gets sent to the
reasoning provider (reasoning/gemini_client.py), by template-filling on the
real claim_type + verification_target selected by
mcie/verification_target_selector.py (Section 6.8) and the real entities
from mcie/entity_extraction.py (Section 6.7) -- instead of returning one
fixed sentence regardless of what the clip actually contains.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


def _location_str(entities: Dict[str, Any]) -> str:
    location = entities.get("location")
    if location and location.get("value"):
        return location["value"]
    return "the claimed location"


def _date_str(entities: Dict[str, Any]) -> str:
    date = entities.get("date")
    if date:
        if date.get("resolved"):
            return date["resolved"]
        if date.get("value"):
            return date["value"]
    return "the claimed date"


def _event_str(entities: Dict[str, Any]) -> str:
    return entities.get("event") or "the claimed event"


def _event_date_query(entities: Dict[str, Any], claim_text: Optional[str]) -> str:
    event = entities.get("event")
    location = _location_str(entities)
    date = _date_str(entities)
    if claim_text:
        event_clause = f"{event} occurred" if event else "this occurred"
        loc_clause = f" in {location}" if location != "the claimed location" else ""
        return (
            f"Verify the claim: \"{claim_text}\". Specifically confirm whether {event_clause}"
            f"{loc_clause} on {date}. If the footage shown matches an earlier "
            f"or different event, identify its true date and location and cite sources."
        )
    event_str = _event_str(entities)
    return (
        f"Verify whether {event_str} occurred in {location} on {date}. If the "
        f"footage shown matches an earlier or different event, identify its "
        f"true date and location and cite sources."
    )


def _event_location_query(entities: Dict[str, Any], claim_text: Optional[str]) -> str:
    event = entities.get("event")
    location = _location_str(entities)
    if claim_text:
        event_clause = f"{event} occurred" if event else "this occurred"
        loc_clause = f" in {location}" if location != "the claimed location" else " as claimed"
        return (
            f"Verify the claim: \"{claim_text}\". Specifically confirm whether {event_clause}"
            f"{loc_clause}. If the footage shown is from a different "
            f"location, identify the correct location and cite sources."
        )
    event_str = _event_str(entities)
    return (
        f"Verify whether {event_str} occurred in {location} as claimed. If the "
        f"footage shown is from a different location, identify the correct "
        f"location and cite sources."
    )


def _event_occurrence_query(entities: Dict[str, Any], claim_text: Optional[str]) -> str:
    event = entities.get("event")
    if claim_text:
        event_clause = f"{event}" if event else "this event"
        return (
            f"Verify the claim: \"{claim_text}\". Specifically confirm whether {event_clause} "
            f"actually occurred as described in this clip. If the footage does not depict "
            f"{event_clause}, identify what it actually shows and cite sources."
        )
    event_str = _event_str(entities)
    return (
        f"Verify whether {event_str} actually occurred as described in this "
        f"clip. If the footage does not depict {event_str}, identify what it "
        f"actually shows and cite sources."
    )


def _statistical_query(entities: Dict[str, Any], claim_text: Optional[str]) -> str:
    numbers: List[str] = entities.get("numbers") or []
    number_str = ", ".join(numbers) if numbers else "the figure cited"
    event = entities.get("event")
    subject = f"the {event}" if event else "this claim"
    if claim_text:
        return (
            f"Verify the claim: \"{claim_text}\". Specifically verify the figure(s) {number_str} "
            f"cited in relation to {subject}. Confirm whether official or reliable sources "
            f"report the same number, and cite sources."
        )
    return (
        f"Verify the figure(s) {number_str} cited in relation to {subject}. "
        f"Confirm whether official or reliable sources report the same "
        f"number, and cite sources."
    )


def _identity_person_query(entities: Dict[str, Any], claim_text: Optional[str]) -> str:
    people: List[str] = entities.get("people") or []
    names = ", ".join(people) if people else "the named person"
    if claim_text:
        return (
            f"Verify the claim: \"{claim_text}\". Specifically confirm the identity and claimed "
            f"involvement of {names} in this clip, and cite sources."
        )
    return (
        f"Verify the identity and claimed involvement of {names} in this "
        f"clip. Confirm whether the person shown or named is correctly "
        f"identified, and cite sources."
    )


def _identity_org_query(entities: Dict[str, Any], claim_text: Optional[str]) -> str:
    organizations: List[str] = entities.get("organizations") or []
    names = ", ".join(organizations) if organizations else "the named organization"
    if claim_text:
        return (
            f"Verify the claim: \"{claim_text}\". Specifically confirm the claimed involvement "
            f"of {names} in this clip, and cite sources."
        )
    return (
        f"Verify the claimed involvement of {names} in this clip. Confirm "
        f"whether the organization is accurately represented, and cite "
        f"sources."
    )


def _general_query(entities: Dict[str, Any], claim_text: Optional[str]) -> str:
    if claim_text:
        return (
            f'Verify the following claim: "{claim_text}". Confirm whether '
            f"it is accurate, and cite sources."
        )
    return "Verify whether the content of this clip is accurately represented, and cite sources."


# Keyed by the exact (claim_type, verification_target) pairs that
# verification_target_selector.py can produce. Falls back to
# _general_query for any pair not listed here (e.g. if the rule lookup
# there gains a new target this file hasn't been updated for yet), rather
# than raising.
_QUERY_BUILDERS: Dict[Tuple[str, str], Callable[[Dict[str, Any], Optional[str]], str]] = {
    ("event_claim", "date_of_event"): _event_date_query,
    ("event_claim", "location_of_event"): _event_location_query,
    ("event_claim", "event_occurrence"): _event_occurrence_query,
    ("statistical_claim", "numeric_assertion"): _statistical_query,
    ("identity_claim", "person_identity"): _identity_person_query,
    ("identity_claim", "organization_identity"): _identity_org_query,
    ("general_claim", "general_verification"): _general_query,
}


def _no_claim_query(mcie_out: Dict[str, Any]) -> str:
    """
    verification_target_selector.py returns claim_type=None when no
    explicit claim was detected at all. There's nothing to verify a claim
    against, but the clip may still be worth a sanity check against its
    visual content, so fall back to that if it's available.
    """
    scene = mcie_out.get("visual_context")
    if scene:
        return (
            f"No explicit checkable claim was detected in this clip's "
            f"speech or on-screen text. Based on the visual content "
            f"({scene}), determine whether this footage appears to be "
            f"reused, unrelated to its posting context, or otherwise "
            f"out-of-context, and cite sources if so."
        )
    return (
        "No explicit checkable claim or usable visual context was detected "
        "in this clip. Flag for manual review."
    )


def _primary_claim_text(mcie_out: Dict[str, Any]) -> Optional[str]:
    primary = mcie_out.get("primary_claim")
    if primary:
        if isinstance(primary, dict) and primary.get("text"):
            return primary["text"]
        elif isinstance(primary, str) and primary.strip():
            return primary.strip()

    ranked = mcie_out.get("ranked_claims") or []
    if ranked:
        first = ranked[0]
        return first.get("text") if isinstance(first, dict) else str(first)

    explicit_claims = mcie_out.get("explicit_claims") or []
    if explicit_claims:
        return explicit_claims[0].get("text")

    implied_claims = mcie_out.get("implied_claims") or []
    if implied_claims:
        first = implied_claims[0]
        return first.get("text") if isinstance(first, dict) else str(first)

    return None


async def run(mcie_out: Dict[str, Any]) -> str:
    """
    Generate the verification query string (Section 7.1).

    `mcie_out` is the merged MCIE output dict assembled in routes.py, so
    claim_type/verification_target (from verification_target_selector.py),
    entities (from entity_extraction.py), explicit_claims (from
    explicit_claim_detector.py), and visual_context (from
    visual_context.py) are all read from it directly.
    """
    claim_type = mcie_out.get("claim_type")
    verification_target = mcie_out.get("verification_target")

    if claim_type is None or verification_target is None:
        return _no_claim_query(mcie_out)

    entities = mcie_out.get("entities") or {}
    claim_text = _primary_claim_text(mcie_out)

    builder = _QUERY_BUILDERS.get((claim_type, verification_target), _general_query)
    return builder(entities, claim_text)