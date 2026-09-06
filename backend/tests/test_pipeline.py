from __future__ import annotations
import pytest
import asyncio
from app.mcie import (
    timeline_alignment, context_builder, visual_context, explicit_claim_detector,
    implied_claim_detector, entity_extraction, verification_target_selector,
    confidence_estimator
)
from app.vpg import query_generator, keyframe_selector, metadata_attachment
from app.reasoning import gemini_client

# ---------------------------------------------------------------------------
# Fixtures matching the Section 5.5 preprocessing output contract, used to
# validate timeline_alignment / context_builder / explicit_claim_detector
# (the three stages implemented with real logic; the rest of MCIE stays
# stubbed and is only exercised by the full-pipeline integration tests below).
# ---------------------------------------------------------------------------

# (0) The document's own running example (Section 6.3): individually, none
# of the signals states a complete claim -- "flood" only exists once the
# visual context is added. The rule-based, text-only layer should therefore
# find NO explicit claim here; that's correct, not a gap in this task.
CROSS_MODAL_ONLY_FIXTURE = {
    "transcript": [{"text": "This happened yesterday.", "start": 3.1, "end": 5.4}],
    "ocr_segments": [{"text": "Mumbai", "frame_ts": 3.0, "bbox": [100, 200, 300, 250]}],
    "candidate_keyframes": [{"frame_id": "kf_01", "timestamp": 3.0, "path": "/tmp/kf_01.jpg"}],
}

# (a) Numeric/statistical claim -- should be caught by the numeric-assertion
# rule even without an explicit location entity.
NUMERIC_CLAIM_FIXTURE = {
    "transcript": [{"text": "The earthquake measured 6.2.", "start": 1.0, "end": 3.0}],
    "ocr_segments": [],
    "candidate_keyframes": [{"frame_id": "kf_02", "timestamp": 1.5, "path": "/tmp/kf_02.jpg"}],
}

# (b) No checkable claim at all -- no numbers, no event noun, no temporal
# marker. The detector must return an empty list, not fabricate a claim.
NO_CLAIM_FIXTURE = {
    "transcript": [{"text": "I really love this song.", "start": 0.5, "end": 2.0}],
    "ocr_segments": [],
    "candidate_keyframes": [],
}

# (c) Transcript and OCR disagree on location ("Mumbai" vs "Delhi"). Stages
# 1-2 must preserve both signals distinctly rather than dropping or merging
# one into the other -- resolving the disagreement itself is Entity
# Extraction / Confidence Estimator's job (Sections 6.7/6.9, out of scope).
LOCATION_DISAGREEMENT_FIXTURE = {
    "transcript": [{"text": "A protest broke out in Mumbai.", "start": 4.0, "end": 6.0}],
    "ocr_segments": [{"text": "Delhi", "frame_ts": 4.2, "bbox": [50, 50, 150, 90]}],
    "candidate_keyframes": [{"frame_id": "kf_03", "timestamp": 4.1, "path": "/tmp/kf_03.jpg"}],
}


@pytest.mark.asyncio
async def test_timeline_alignment_sorts_all_signal_types():
    ta_out = await timeline_alignment.run(LOCATION_DISAGREEMENT_FIXTURE)
    timeline = ta_out["aligned_timeline"]

    # All three signal types are present and sorted ascending by timestamp.
    assert {e["type"] for e in timeline} == {"speech", "ocr", "keyframe"}
    timestamps = [e["timestamp"] for e in timeline]
    assert timestamps == sorted(timestamps)

    speech_event = next(e for e in timeline if e["type"] == "speech")
    ocr_event = next(e for e in timeline if e["type"] == "ocr")
    assert "Mumbai" in speech_event["text"]
    assert ocr_event["text"] == "Delhi"


@pytest.mark.asyncio
async def test_context_builder_groups_signals_into_windows():
    ta_out = await timeline_alignment.run(LOCATION_DISAGREEMENT_FIXTURE)
    cb_out = await context_builder.run(ta_out)

    assert "context_units" in cb_out
    assert len(cb_out["context_units"]) > 0

    # The disagreeing signals land in at least one shared window, and remain
    # distinct within it (not merged into a single string).
    unit_with_both = next(
        u for u in cb_out["context_units"]
        if u["speech_segments"] and u["ocr_segments"]
    )
    assert any("Mumbai" in s for s in unit_with_both["speech_segments"])
    assert "Delhi" in unit_with_both["ocr_segments"]


@pytest.mark.asyncio
async def test_context_builder_dedupes_persistent_caption():
    # A caption ("Mumbai") that appears at two OCR timestamps close enough
    # to land in the same window should not be double-counted in that unit.
    preproc_out = {
        "transcript": [],
        "ocr_segments": [
            {"text": "Mumbai", "frame_ts": 3.0, "bbox": [0, 0, 10, 10]},
            {"text": "Mumbai", "frame_ts": 3.5, "bbox": [0, 0, 10, 10]},
        ],
        "candidate_keyframes": [],
    }
    ta_out = await timeline_alignment.run(preproc_out)
    cb_out = await context_builder.run(ta_out)

    unit = next(u for u in cb_out["context_units"] if u["ocr_segments"])
    assert unit["ocr_segments"].count("Mumbai") == 1


@pytest.mark.asyncio
async def test_explicit_claim_detector_cross_modal_only_yields_no_claim():
    ta_out = await timeline_alignment.run(CROSS_MODAL_ONLY_FIXTURE)
    cb_out = await context_builder.run(ta_out)
    vc_out = await visual_context.run(cb_out)  # untouched stub

    ecd_out = await explicit_claim_detector.run(cb_out, vc_out)
    assert ecd_out["explicit_claims"] == []


@pytest.mark.asyncio
async def test_explicit_claim_detector_numeric_claim():
    ta_out = await timeline_alignment.run(NUMERIC_CLAIM_FIXTURE)
    cb_out = await context_builder.run(ta_out)
    vc_out = await visual_context.run(cb_out)

    ecd_out = await explicit_claim_detector.run(cb_out, vc_out)
    assert len(ecd_out["explicit_claims"]) >= 1
    claim = ecd_out["explicit_claims"][0]
    assert "6.2" in claim["text"]
    assert claim["source"] == "asr"
    assert claim["confidence"] > 0


@pytest.mark.asyncio
async def test_explicit_claim_detector_no_claim():
    ta_out = await timeline_alignment.run(NO_CLAIM_FIXTURE)
    cb_out = await context_builder.run(ta_out)
    vc_out = await visual_context.run(cb_out)

    ecd_out = await explicit_claim_detector.run(cb_out, vc_out)
    assert ecd_out["explicit_claims"] == []


@pytest.mark.asyncio
async def test_explicit_claim_detector_no_duplicate_across_overlapping_windows():
    # A single signal (Context Units are overlapping windows: 4s width, 2s
    # stride) commonly falls inside two consecutive windows. The same claim
    # must not be reported twice just because of that overlap.
    preproc_out = {
        "transcript": [{"text": "Flood in Mumbai.", "start": 2.0, "end": 3.5}],
        "ocr_segments": [],
        "candidate_keyframes": [],
    }
    ta_out = await timeline_alignment.run(preproc_out)
    cb_out = await context_builder.run(ta_out)
    vc_out = await visual_context.run(cb_out)

    ecd_out = await explicit_claim_detector.run(cb_out, vc_out)
    assert len(ecd_out["explicit_claims"]) == 1


@pytest.mark.asyncio
async def test_explicit_claim_detector_location_disagreement_preserved():
    ta_out = await timeline_alignment.run(LOCATION_DISAGREEMENT_FIXTURE)
    cb_out = await context_builder.run(ta_out)
    vc_out = await visual_context.run(cb_out)

    ecd_out = await explicit_claim_detector.run(cb_out, vc_out)
    assert len(ecd_out["explicit_claims"]) >= 1
    claim = ecd_out["explicit_claims"][0]
    # Both disagreeing location mentions must survive into the claim text --
    # this stage must not silently pick one and drop the other.
    assert "Mumbai" in claim["text"]
    assert "Delhi" in claim["text"]
    assert claim["source"] == "asr+ocr"


# ---------------------------------------------------------------------------
# Existing full-pipeline integration tests (unchanged in intent): these still
# exercise every MCIE/VPG/reasoning stage end-to-end, including the ones that
# remain stubs. They assert on output *shape*, not stub-specific values,
# except test_vpg_and_reasoning's gemini_client assertion, since that module
# is untouched by this task.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcie_pipeline():
    preproc_out = {
        "transcript": [{"text": "This happened yesterday.", "start": 3.1, "end": 5.4}],
        "ocr_segments": [{"text": "Mumbai", "frame_ts": 3.0, "bbox": [100, 200, 300, 250]}],
        "candidate_keyframes": [{"frame_id": "kf_01", "timestamp": 3.0, "path": "/tmp/kf_01.jpg"}]
    }
    ta_out = await timeline_alignment.run(preproc_out)
    assert "aligned_timeline" in ta_out
    
    cb_out = await context_builder.run(ta_out)
    assert "context_units" in cb_out
    
    vc_out = await visual_context.run(cb_out)
    assert "visual_descriptions" in vc_out
    
    ecd_out = await explicit_claim_detector.run(cb_out, vc_out)
    assert "explicit_claims" in ecd_out
    
    icd_out = await implied_claim_detector.run(cb_out, vc_out)
    assert "implied_claims" in icd_out
    
    ee_out = await entity_extraction.run(ecd_out, icd_out)
    assert "entities" in ee_out
    
    vts_out = await verification_target_selector.run(ecd_out, ee_out)
    assert "verification_target" in vts_out
    
    ce_out = await confidence_estimator.run(cb_out, ecd_out, icd_out)
    assert "confidence" in ce_out

@pytest.mark.asyncio
async def test_vpg_and_reasoning():
    mcie_out = {
        "claim_type": "event_claim",
        "verification_target": "date_of_event",
        "explicit_claims": [{"text": "A flood occurred in Mumbai yesterday.", "source": "asr+ocr"}],
        "entities": {
            "event": "flood",
            "location": {"value": "Mumbai"},
            "date": {"resolved": "2026-08-28"}
        },
        "visual_context": "Flooded street, heavy rainfall."
    }
    
    query = await query_generator.run(mcie_out)
    assert isinstance(query, str)
    
    ks_out = await keyframe_selector.run(mcie_out)
    assert "priority_keyframes" in ks_out
    
    vpg_out = await metadata_attachment.run(mcie_out, query, ks_out)
    assert vpg_out["verification_query"] == query
    
    reasoning_out = await gemini_client.get_verdict(vpg_out)
    # Without GEMINI_API_KEY the client returns INCONCLUSIVE; with a real
    # key it returns the model's actual verdict. Assert the response shape
    # rather than a specific verdict value.
    assert reasoning_out["verdict"] in {"TRUE", "FALSE", "MISLEADING", "INCONCLUSIVE"}
    assert isinstance(reasoning_out["confidence"], int)
    assert 0 <= reasoning_out["confidence"] <= 100
    assert isinstance(reasoning_out["summary"], str) and reasoning_out["summary"]
    assert isinstance(reasoning_out["sources"], list)