from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable

from app.config import DERIVED_DIR
from app.preprocessing import ocr as ocr_pipeline
from app.preprocessing import whisper as whisper_pipeline


class PreprocessingError(RuntimeError):
    """Raised when preprocessing cannot produce valid MCIE input signals."""


FFMPEG_BIN = os.getenv("FACTFLOW_FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FACTFLOW_FFPROBE_BIN", "ffprobe")

KEYFRAME_INTERVAL_SEC = float(
    os.getenv("FACTFLOW_KEYFRAME_INTERVAL_SEC", "4")
)

MAX_CANDIDATE_KEYFRAMES = 6


def _require_binary(binary: str) -> str:
    resolved = shutil.which(binary)

    if not resolved:
        raise PreprocessingError(
            f"Required binary '{binary}' was not found. "
            "Install FFmpeg or set the matching FACTFLOW_*_BIN setting."
        )

    return resolved


async def _run_command(
    command: Iterable[str],
    label: str,
) -> str:
    """
    Run an external command and return stdout.

    Blocking subprocess.run() is executed inside a worker thread so this
    remains compatible with Uvicorn on Windows.
    """

    command_list = list(command)

    loop = asyncio.get_running_loop()

    def _run() -> "subprocess.CompletedProcess[bytes]":
        return subprocess.run(
            command_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    result = await loop.run_in_executor(None, _run)

    if result.returncode != 0:
        details = result.stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()

        raise PreprocessingError(
            f"{label} failed: {details[-1000:]}"
        )

    return result.stdout.decode(
        "utf-8",
        errors="replace",
    )


async def _probe_clip(
    clip_path: Path,
    ffprobe: str,
) -> Dict[str, Any]:

    raw = await _run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(clip_path),
        ],
        "FFprobe inspection",
    )

    try:
        metadata = json.loads(raw)

        duration = float(
            metadata["format"]["duration"]
        )

    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:

        raise PreprocessingError(
            "FFprobe returned no valid duration for this clip."
        ) from exc

    if not math.isfinite(duration) or duration <= 0:
        raise PreprocessingError(
            "Clip duration must be a positive finite value."
        )

    streams = metadata.get(
        "streams",
        [],
    )

    if not any(
        stream.get("codec_type") == "video"
        for stream in streams
    ):
        raise PreprocessingError(
            "The uploaded file does not contain a video stream."
        )

    return {
        "duration_sec": duration,
        "has_audio": any(
            stream.get("codec_type") == "audio"
            for stream in streams
        ),
    }


def _candidate_timestamps(
    duration_sec: float,
) -> list[float]:
    """
    Choose a bounded, evenly-spaced temporary keyframe set.

    This remains the temporary claim-agnostic sampling stage.
    The architecture's later PySceneDetect + CLIP stage can replace
    this without changing the preprocessing output contract.
    """

    count = max(
        1,
        min(
            MAX_CANDIDATE_KEYFRAMES,
            math.ceil(
                duration_sec / KEYFRAME_INTERVAL_SEC
            ),
        ),
    )

    upper_bound = max(
        0.0,
        duration_sec - 0.05,
    )

    return [
        round(
            min(
                upper_bound,
                duration_sec * (index + 0.5) / count,
            ),
            3,
        )
        for index in range(count)
    ]


async def run(
    clip_path: str,
    output_dir: Path | None = None,
) -> Dict[str, Any]:
    """
    Build the FactFlow preprocessing contract.

    Pipeline:

        Video
          |
          +--> FFmpeg --> audio.wav --> Whisper.cpp --> transcript
          |
          +--> FFmpeg --> keyframes --> PaddleOCR --> ocr_segments
          |
          +--> candidate_keyframes

    Output:

        {
            "transcript": [...],
            "ocr_segments": [...],
            "candidate_keyframes": [...]
        }
    """

    source = Path(
        clip_path
    ).expanduser().resolve()

    if not source.is_file():
        raise PreprocessingError(
            f"Uploaded clip does not exist: {source}"
        )

    ffmpeg = _require_binary(
        FFMPEG_BIN
    )

    ffprobe = _require_binary(
        FFPROBE_BIN
    )

    metadata = await _probe_clip(
        source,
        ffprobe,
    )

    artifact_dir = (
        output_dir
        or DERIVED_DIR / source.stem
    ).resolve()

    artifact_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------
    # Section 5.2: Audio extraction + Whisper.cpp transcription
    # ---------------------------------------------------------

    audio_path: Path | None = None
    transcript: list[dict[str, Any]] = []

    if metadata["has_audio"]:

        audio_path = (
            artifact_dir / "audio.wav"
        )

        await _run_command(
            [
                ffmpeg,
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(audio_path),
            ],
            "FFmpeg audio extraction",
        )

        try:

            transcript = await whisper_pipeline.run(
                audio_path,
                artifact_dir,
            )

        except whisper_pipeline.WhisperError as exc:

            # Whisper.cpp is optional — if the binary or model is
            # missing the pipeline degrades gracefully to OCR-only
            # (no speech transcript) rather than failing the clip.
            import logging
            logging.getLogger(__name__).warning(
                "Whisper transcription skipped: %s", exc,
            )

    # ---------------------------------------------------------
    # Section 5.4: Temporary candidate keyframe extraction
    # ---------------------------------------------------------

    candidate_keyframes = []

    for index, timestamp in enumerate(
        _candidate_timestamps(
            metadata["duration_sec"]
        ),
        start=1,
    ):

        frame_path = (
            artifact_dir
            / f"keyframe_{index:02d}.jpg"
        )

        await _run_command(
            [
                ffmpeg,
                "-y",
                "-ss",
                str(timestamp),
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame_path),
            ],
            f"FFmpeg keyframe extraction at {timestamp}s",
        )

        candidate_keyframes.append(
            {
                "frame_id": f"kf_{index:02d}",
                "timestamp": timestamp,
                "path": str(frame_path),
            }
        )

    # ---------------------------------------------------------
    # Section 5.3: PaddleOCR
    # ---------------------------------------------------------

    try:

        ocr_segments = await ocr_pipeline.run(
            candidate_keyframes
        )

    except ocr_pipeline.OcrError as exc:

        raise PreprocessingError(
            str(exc)
        ) from exc

    # ---------------------------------------------------------
    # Final preprocessing contract
    # ---------------------------------------------------------

    return {
        "transcript": transcript,

        "ocr_segments": ocr_segments,

        "candidate_keyframes": candidate_keyframes,

        "artifacts": {
            "duration_sec": metadata["duration_sec"],
            "audio_path": (
                str(audio_path)
                if audio_path
                else None
            ),
            "artifact_dir": str(
                artifact_dir
            ),
        },
    }