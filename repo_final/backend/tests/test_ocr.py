from __future__ import annotations
import pytest
from app.preprocessing.ocr import _extract_frame_text, _polygon_to_bbox, run as ocr_run


def test_polygon_to_bbox_converts_four_point_polygon():
    polygon = [[30.0, 80.0], [310.0, 80.0], [310.0, 110.0], [30.0, 110.0]]
    assert _polygon_to_bbox(polygon) == [30.0, 80.0, 310.0, 110.0]


def test_extract_frame_text_happy_path():
    # Matches the documented PaddleOCR 2.x .ocr() shape for one image:
    # [[[polygon, (text, confidence)], ...]]
    raw_result = [[
        [[[30, 80], [310, 80], [310, 110], [30, 110]], ("Magnitude 6.2 earthquake", 0.97)],
    ]]
    entries = _extract_frame_text(raw_result)
    assert len(entries) == 1
    assert entries[0]["text"] == "Magnitude 6.2 earthquake"
    assert entries[0]["bbox"] == [30, 80, 310, 110]
    assert entries[0]["confidence"] == pytest.approx(0.97)


def test_extract_frame_text_filters_low_confidence():
    raw_result = [[
        [[[0, 0], [10, 0], [10, 10], [0, 10]], ("blurry noise", 0.2)],
    ]]
    assert _extract_frame_text(raw_result) == []


def test_extract_frame_text_filters_whitespace_only_text():
    raw_result = [[
        [[[0, 0], [10, 0], [10, 10], [0, 10]], ("   ", 0.99)],
    ]]
    assert _extract_frame_text(raw_result) == []


def test_extract_frame_text_no_detection_in_frame():
    # PaddleOCR 2.x's documented behaviour for a frame with no text at all.
    assert _extract_frame_text([None]) == []
    assert _extract_frame_text(None) == []


def test_extract_frame_text_skips_malformed_entry_without_crashing():
    raw_result = [[
        ["this is not a valid detection shape"],
        [[[0, 0], [50, 0], [50, 20], [0, 20]], ("Mumbai", 0.91)],
    ]]
    entries = _extract_frame_text(raw_result)
    # The malformed first entry is skipped; the valid second one still comes through.
    assert len(entries) == 1
    assert entries[0]["text"] == "Mumbai"


@pytest.mark.asyncio
async def test_run_returns_empty_list_for_no_keyframes():
    assert await ocr_run([]) == []
