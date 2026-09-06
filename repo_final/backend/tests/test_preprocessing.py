from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.preprocessing.pipeline import PreprocessingError, run


@pytest.fixture
def video_clip(tmp_path: Path) -> Path:
    """Create a small real MP4 with both video and audio using FFmpeg."""
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is required for preprocessing tests")

    clip = tmp_path / "fixture.mp4"
    command = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=1.2",
        "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=16000:duration=1.2",
        "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(clip),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return clip


def test_preprocessing_extracts_real_audio_and_candidate_keyframes(
    video_clip: Path, tmp_path: Path
) -> None:
    # This fixture is a synthetic FFmpeg test pattern with no burned-in
    # text, so an empty ocr_segments result is the correct outcome here --
    # not because OCR is unimplemented (it now is; see app/preprocessing/ocr.py)
    # but because there is genuinely no on-screen text in this clip. Skip
    # rather than fail if the OCR engine itself can't be reached in this
    # environment (e.g. no network access to download PaddleOCR's model
    # weights), mirroring the ffmpeg-availability skip above.
    try:
        from app.preprocessing.ocr import _load_engine
        _load_engine()
    except Exception as exc:
        pytest.skip(f"PaddleOCR engine unavailable in this environment: {exc}")

    result = asyncio.run(run(str(video_clip), output_dir=tmp_path / "derived"))

    # Section 5.5 contract stays stable. Transcript is empty until the
    # Whisper.cpp integration exists. OCR is real (PaddleOCR) as of this
    # test, but finds nothing here since the fixture has no on-screen text.
    assert result["transcript"] == []
    assert result["ocr_segments"] == []
    assert result["candidate_keyframes"]

    timestamps = [frame["timestamp"] for frame in result["candidate_keyframes"]]
    assert timestamps == sorted(timestamps)
    assert all(Path(frame["path"]).is_file() for frame in result["candidate_keyframes"])

    artifacts = result["artifacts"]
    assert artifacts["duration_sec"] == pytest.approx(1.2, abs=0.25)
    assert Path(artifacts["audio_path"]).is_file()


def test_preprocessing_rejects_a_missing_clip(tmp_path: Path) -> None:
    with pytest.raises(PreprocessingError, match="does not exist"):
        asyncio.run(run(str(tmp_path / "missing.mp4"), output_dir=tmp_path / "derived"))
