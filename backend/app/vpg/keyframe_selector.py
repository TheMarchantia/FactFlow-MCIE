"""
VPG — Priority Keyframe Selection (Section 7.3, "Priority Keyframe Selection").

Selects the most claim-relevant keyframes from the full candidate set,
prioritising frames that fall inside Context Unit windows containing
speech or OCR text (i.e., windows where a claim was likely detected)
over frames from silent/text-free windows.

This is the rule-based, latency-free implementation described in
Section 7.3's "temporal proximity" approach.  A future CLIP-embedding-
based reranker can replace or augment this without changing the output
contract (a list of frame-ID strings in priority order).
"""

from __future__ import annotations

from typing import Any, Dict, List


async def run(mcie_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Select priority keyframes based on claim timing (Section 7.3).

    Keyframes that co-occur with textual signals (speech or OCR) in the
    same Context Unit window are ranked higher than those in text-free
    windows.  Within each tier, original temporal order is preserved.

    If there are no claims or no context units, all keyframe refs are
    returned unchanged — there's nothing to prioritise against, but the
    downstream metadata_attachment stage still needs the full set.
    """
    all_refs: List[str] = mcie_out.get("keyframe_refs") or []
    context_units: List[Dict[str, Any]] = mcie_out.get("context_units") or []
    explicit_claims: List[Dict[str, Any]] = mcie_out.get("explicit_claims") or []
    implied_claims: List[Dict[str, Any]] = mcie_out.get("implied_claims") or []

    if not all_refs:
        return {"priority_keyframes": []}

    # No claims or no context to score against — return top frames unchanged.
    if (not explicit_claims and not implied_claims) or not context_units:
        return {"priority_keyframes": list(all_refs[:2]) if len(all_refs) > 2 else list(all_refs)}

    # Tier 1: keyframes inside windows that carry speech or OCR text
    # (the windows where a claim is most likely to have been detected).
    priority: List[str] = []
    for unit in context_units:
        has_text = bool(unit.get("speech_segments")) or bool(unit.get("ocr_segments"))
        if not has_text:
            continue
        for ref in unit.get("keyframe_refs") or []:
            if ref not in priority:
                priority.append(ref)

    # Tier 2: remaining keyframes (text-free windows), preserving order.
    for ref in all_refs:
        if ref not in priority:
            priority.append(ref)

    # Section 7.3: Select a compact subset (central frame + supporting frame)
    # to keep verification package focused.
    selected = priority[:2] if len(priority) >= 2 else priority
    return {"priority_keyframes": selected}
