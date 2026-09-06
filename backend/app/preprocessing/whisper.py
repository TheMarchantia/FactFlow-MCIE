from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class WhisperError(RuntimeError):
    """Raised when Whisper.cpp cannot produce a valid transcript."""


WHISPER_BIN = os.getenv(
    "FACTFLOW_WHISPER_BIN",
    "whisper-cli",
)

WHISPER_MODEL = os.getenv(
    "FACTFLOW_WHISPER_MODEL",
    "",
)

WHISPER_LANGUAGE = os.getenv(
    "FACTFLOW_WHISPER_LANGUAGE",
    "en",
)

WHISPER_THREADS = int(
    os.getenv(
        "FACTFLOW_WHISPER_THREADS",
        "4",
    )
)


def _resolve_binary() -> str:
    """Find the Whisper.cpp executable."""

    candidate = Path(WHISPER_BIN).expanduser()

    if candidate.is_file():
        return str(candidate.resolve())

    resolved = shutil.which(WHISPER_BIN)

    if resolved:
        return resolved

    raise WhisperError(
        "Whisper.cpp executable was not found. "
        "Set FACTFLOW_WHISPER_BIN to the full path of whisper-cli.exe."
    )


def _resolve_model() -> str:
    """Find the Whisper.cpp model."""

    if not WHISPER_MODEL:
        raise WhisperError(
            "Whisper model is not configured. "
            "Set FACTFLOW_WHISPER_MODEL to the ggml model file."
        )

    model = Path(WHISPER_MODEL).expanduser()

    if not model.is_file():
        raise WhisperError(
            f"Whisper model does not exist: {model}"
        )

    return str(model.resolve())


async def _run_command(command: list[str]) -> tuple[int, str, str]:
    """
    Run Whisper.cpp without blocking the FastAPI event loop.

    subprocess.run() is executed inside a worker thread because this
    application needs to work reliably with Uvicorn on Windows.
    """

    loop = asyncio.get_running_loop()

    def _run() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    result = await loop.run_in_executor(None, _run)

    stdout = result.stdout.decode(
        "utf-8",
        errors="replace",
    )

    stderr = result.stderr.decode(
        "utf-8",
        errors="replace",
    )

    return result.returncode, stdout, stderr


def _parse_json(json_path: Path) -> list[dict[str, Any]]:
    """
    Convert Whisper.cpp JSON segments into FactFlow's transcript contract.

    Whisper.cpp timestamps are milliseconds.
    FactFlow timestamps are seconds.
    """

    try:
        data = json.loads(
            json_path.read_text(
                encoding="utf-8"
            )
        )

    except FileNotFoundError as exc:
        raise WhisperError(
            "Whisper.cpp completed but did not create "
            f"its JSON output: {json_path}"
        ) from exc

    except json.JSONDecodeError as exc:
        raise WhisperError(
            f"Whisper.cpp produced invalid JSON: {json_path}"
        ) from exc

    transcription = data.get("transcription")

    if not isinstance(transcription, list):
        raise WhisperError(
            "Whisper.cpp JSON does not contain "
            "a valid 'transcription' array."
        )

    transcript: list[dict[str, Any]] = []

    for segment in transcription:

        if not isinstance(segment, dict):
            continue

        offsets = segment.get(
            "offsets",
            {},
        )

        if not isinstance(offsets, dict):
            continue

        start_ms = offsets.get("from")
        end_ms = offsets.get("to")

        text = str(
            segment.get(
                "text",
                "",
            )
        ).strip()

        if (
            start_ms is None
            or end_ms is None
            or not text
        ):
            continue

        try:
            start = float(start_ms) / 1000.0
            end = float(end_ms) / 1000.0

        except (
            TypeError,
            ValueError,
        ):
            continue

        if end < start:
            continue

        transcript.append(
            {
                "text": text,
                "start": round(start, 3),
                "end": round(end, 3),
            }
        )

    transcript.sort(
        key=lambda item: item["start"]
    )

    return transcript


async def run(
    audio_path: str | Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    """
    Transcribe a 16 kHz mono WAV file with Whisper.cpp.

    Returns FactFlow's transcript contract:

    [
        {
            "text": "...",
            "start": 0.0,
            "end": 2.5
        }
    ]
    """

    audio = Path(
        audio_path
    ).expanduser().resolve()

    if not audio.is_file():
        raise WhisperError(
            f"Whisper input audio does not exist: {audio}"
        )

    whisper_bin = _resolve_binary()
    model = _resolve_model()

    output_dir = output_dir.resolve()
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_base = (
        output_dir / "whisper_transcript"
    )

    output_json = Path(
        f"{output_base}.json"
    )

    # Remove stale output from an earlier run.
    if output_json.exists():
        output_json.unlink()

    command = [
        whisper_bin,
        "-m",
        model,
        "-f",
        str(audio),
        "-l",
        WHISPER_LANGUAGE,
        "-t",
        str(WHISPER_THREADS),
        "-ojf",
        "-of",
        str(output_base),
        "-np",
    ]

    returncode, stdout, stderr = (
        await _run_command(command)
    )

    if returncode != 0:

        details = (
            stderr.strip()
            or stdout.strip()
        )

        raise WhisperError(
            "Whisper.cpp failed with "
            f"exit code {returncode}: "
            f"{details[-1500:]}"
        )

    if not output_json.is_file():
        raise WhisperError(
            "Whisper.cpp returned successfully "
            "but no JSON transcription was created "
            f"at {output_json}."
        )

    return _parse_json(output_json)