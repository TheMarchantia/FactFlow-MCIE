"""
Section 5.3: PaddleOCR on-screen text extraction.

Kept as its own module (mirroring how each preprocessing/MCIE/VPG stage
gets a dedicated file elsewhere in this codebase) so pipeline.py stays
focused on FFmpeg orchestration and OCR-specific concerns -- model
lifecycle, result-shape parsing, confidence filtering -- live here.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# PaddleOCR recognition returns a per-detection confidence score; text below
# this is treated as noise (common on low-contrast or heavily stylized
# captions) rather than a genuine on-screen caption worth passing to MCIE.
MIN_OCR_CONFIDENCE = 0.5

_ocr_engine: Optional[Any] = None
_ocr_engine_lock = threading.Lock()


class OcrError(RuntimeError):
    """
    Raised when the OCR engine itself cannot be created -- missing
    dependency or unreachable model weights -- as distinct from a single
    frame simply yielding no text, which is not an error.
    """


def _load_engine() -> Any:
    """
    Lazily create a single PaddleOCR instance, reused across every keyframe
    and every clip in this process. Model load is comparatively expensive
    (on the order of seconds); re-creating it per frame or per request would
    make preprocessing far slower than necessary.

    Guarded with a plain threading.Lock rather than an asyncio.Lock because
    this function runs inside a worker thread (via asyncio.to_thread in
    run(), below), not directly on the event loop.
    """
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine

    with _ocr_engine_lock:
        if _ocr_engine is not None:  # re-check after acquiring the lock
            return _ocr_engine

        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OcrError(
                "paddleocr is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        try:
            # enable_mkldnn=False: PaddleOCR 2.7.x's default oneDNN
            # (MKL-DNN) fused-convolution graph optimization pass is known
            # to be incompatible with certain CPU/paddlepaddle-wheel/model
            # combinations, failing every inference with "OneDnnContext
            # does not have the input Filter" (operator <fused_conv2d>).
            # Disabling it trades a little inference speed for the plain
            # (non-fused) conv path, which doesn't have this bug.
            _ocr_engine = PaddleOCR(
                use_angle_cls=False, lang="en", show_log=False, enable_mkldnn=False,
            )
        except SystemExit as exc:
            # PaddleOCR's own model-download utility calls sys.exit() on a
            # failed download instead of raising a normal exception.
            # SystemExit is a BaseException, not an Exception -- left
            # uncaught here, it would propagate straight past a bare
            # `except Exception` and kill the entire backend worker
            # process on any network hiccup, not just fail this one clip.
            raise OcrError(
                "PaddleOCR could not download its model weights (it calls "
                "sys.exit() internally on a failed download instead of "
                "raising a normal exception -- caught and converted here). "
                "Check outbound network access to paddleocr.bj.bcebos.com."
            ) from exc
        except Exception as exc:
            raise OcrError(
                "Failed to initialize PaddleOCR. This is most commonly a first-run "
                "model download failure: PaddleOCR fetches its detection and "
                "recognition weights from paddleocr.bj.bcebos.com the first time "
                "it runs, which requires outbound network access to that host."
            ) from exc
        return _ocr_engine


def _polygon_to_bbox(polygon: List[List[float]]) -> List[float]:
    """Convert PaddleOCR's 4-point polygon into a flat [x_min, y_min, x_max,
    y_max] box, matching the flat bbox shape used elsewhere in the Section
    5.5 contract."""
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def _extract_frame_text(raw_result: Any) -> List[Dict[str, Any]]:
    """
    Parse a single image's PaddleOCR 2.x `.ocr()` result into
    {"text", "bbox", "confidence"} entries.

    PaddleOCR 2.x returns, for one image, a single-element list whose entry
    is either None (no text detected -- a documented PaddleOCR 2.x
    behaviour, not an error) or a list of
    [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (text, confidence)] detections.
    Each detection is parsed defensively; a single malformed entry is
    skipped rather than failing the whole frame.
    """
    if not raw_result or raw_result[0] is None:
        return []

    entries: List[Dict[str, Any]] = []
    for detection in raw_result[0]:
        try:
            polygon, (text, confidence) = detection
            confidence = float(confidence)
            if confidence < MIN_OCR_CONFIDENCE:
                continue
            text = text.strip()
            if not text:
                continue
            entries.append({
                "text": text,
                "bbox": _polygon_to_bbox(polygon),
                "confidence": confidence,
            })
        except (ValueError, TypeError) as exc:
            logger.warning("Skipping malformed PaddleOCR detection: %s", exc)
            continue
    return entries


def _run_ocr_sync(image_path: str) -> List[Dict[str, Any]]:
    engine = _load_engine()
    raw_result = engine.ocr(image_path, cls=False)
    return _extract_frame_text(raw_result)


async def run(candidate_keyframes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Run PaddleOCR against each extracted keyframe, producing the Section
    5.5 `ocr_segments` list.

    A failure on an individual frame (a corrupt/unreadable image, an
    unexpected result shape) is logged and skipped -- it degrades that one
    frame to "no on-screen text detected", not a failed clip. An OcrError
    (the engine can't be created at all) is allowed to propagate, since
    that's a real configuration problem worth surfacing loudly rather than
    silently and permanently returning empty OCR for every clip.
    """
    if not candidate_keyframes:
        return []

    # Fail fast on a real configuration problem before looping over frames.
    # Run via to_thread even for this check -- model loading can itself take
    # a noticeable moment and must not block the event loop.
    await asyncio.to_thread(_load_engine)

    ocr_segments: List[Dict[str, Any]] = []
    for keyframe in candidate_keyframes:
        frame_path = keyframe.get("path")
        frame_ts = keyframe.get("timestamp", 0.0)
        if not frame_path or not Path(frame_path).is_file():
            continue
        try:
            detections = await asyncio.to_thread(_run_ocr_sync, frame_path)
        except OcrError:
            raise
        except Exception as exc:
            logger.warning("OCR failed for keyframe %s: %s", frame_path, exc)
            continue

        for detection in detections:
            ocr_segments.append({
                "text": detection["text"],
                "frame_ts": frame_ts,
                "bbox": detection["bbox"],
            })

    return ocr_segments