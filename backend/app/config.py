"""Runtime paths and limits for the FactFlow backend.

Keeping these paths independent of the process working directory matters for
the Android client and for background tasks: both must refer to the same clip
and derived-artifact locations regardless of how Uvicorn was started.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")

UPLOADS_DIR = Path(os.getenv("FACTFLOW_UPLOADS_DIR", BACKEND_ROOT / "uploads")).resolve()
DERIVED_DIR = Path(os.getenv("FACTFLOW_DERIVED_DIR", BACKEND_ROOT / "derived")).resolve()

DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{(BACKEND_ROOT / 'factflow.db').as_posix()}"
DATABASE_URL = os.getenv("FACTFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)

# Video uploads are user-provided and can otherwise exhaust server memory or
# storage. The limit is configurable for larger deployment environments.
MAX_UPLOAD_BYTES = int(os.getenv("FACTFLOW_MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))
UPLOAD_CHUNK_BYTES = 1024 * 1024

# A deliberately small allow-list for the first Android client contract.
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}

# The original scaffold returned a fixed fact-check verdict for every clip.
# Never enable that behaviour accidentally in a user-facing run. It may be
# enabled only for explicitly marked UI-development demos while MCIE, VPG,
# and the Gemini/Grok client are completed in later milestones.
ENABLE_EXPERIMENTAL_STUB_VERIFICATION = True


def ensure_runtime_directories() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
