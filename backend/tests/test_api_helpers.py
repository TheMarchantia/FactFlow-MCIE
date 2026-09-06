from __future__ import annotations

from app.api.routes import _safe_filename


def test_safe_filename_strips_client_path_components() -> None:
    assert _safe_filename("../../factflow.db") == "factflow.db"
    assert _safe_filename(r"C:\\temp\\clip.mp4") == "clip.mp4"
    assert _safe_filename(None) == "clip.mp4"
