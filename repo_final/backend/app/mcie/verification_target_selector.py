"""
MCIE — Verification Target Selection (Section 6.8, "Verification Target
Selection").

Classifies the checkable "shape" of a clip's claims (claim_type) and picks
what specifically needs to be verified (verification_target), using the
real output of Explicit Claim Detection (Section 6.5.1) and Entity
Extraction (Section 6.7) rather than a fixed answer. Downstream stages
(query_generator.py, metadata_attachment.py) read claim_type and
verification_target to decide what question to actually ask the reasoning
provider.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Priority order for the rule lookup below, most-specific-signal-first.
# A single claim can carry several of these signals at once (e.g. "A flood
# killed 12 people in Mumbai yesterday" has an event noun, a location, a
# date, AND a number) -- ties are broken in this order, not by list
# position in the entities dict:
#
#   1. date        -> event_claim / date_of_event
#        A specific date is the single most useful thing to verify against
#        (it's also the core of this project's recontextualized-media
#        thesis: is this footage really from the claimed date?), so a date
#        wins over a bare number even when both are present.
#   2. numbers      -> statistical_claim / numeric_assertion
#        No date, but a checkable figure (death toll, magnitude, percent).
#   3. location     -> event_claim / location_of_event
#        No date or number, but a place is named alongside the claim.
#   4. event noun   -> event_claim / event_occurrence
#        An event word (e.g. "flood") with no date/number/location to
#        anchor it -- still worth checking that the event itself occurred.
#   5. people/orgs  -> identity_claim / person_identity | organization_identity
#        No event-shaped signal at all, just a named person or organization.
#   6. nothing      -> general_claim / general_verification
#        A claim was detected but carries none of the above entities.


def _classify(entities: Dict[str, Any]) -> Tuple[str, str]:
    date = entities.get("date")
    numbers: List[str] = entities.get("numbers") or []
    location = entities.get("location")
    event = entities.get("event")
    people: List[str] = entities.get("people") or []
    organizations: List[str] = entities.get("organizations") or []

    if date is not None:
        return "event_claim", "date_of_event"
    if numbers:
        return "statistical_claim", "numeric_assertion"
    if location is not None:
        return "event_claim", "location_of_event"
    if event is not None:
        return "event_claim", "event_occurrence"
    if people:
        return "identity_claim", "person_identity"
    if organizations:
        return "identity_claim", "organization_identity"
    return "general_claim", "general_verification"


async def run(ecd_out: Dict[str, Any], ee_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Select claim_type + verification_target (Section 6.8).

    If no explicit claim was detected at all, there is nothing to select a
    verification target for -- return both fields as None rather than
    guessing "event_claim" the way the old stub always did. Otherwise,
    classify using the aggregated entities from Entity Extraction (ee_out),
    which already merges signals across every claim in ecd_out.
    """
    explicit_claims = ecd_out.get("explicit_claims") or []
    if not explicit_claims:
        return {"claim_type": None, "verification_target": None}

    entities = ee_out.get("entities") or {}
    claim_type, verification_target = _classify(entities)

    return {
        "claim_type": claim_type,
        "verification_target": verification_target,
    }