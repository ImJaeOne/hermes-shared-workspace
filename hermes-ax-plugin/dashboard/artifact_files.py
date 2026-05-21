"""Artifact file helpers for AX dashboard storage."""

from __future__ import annotations

import mimetypes
from pathlib import Path

try:
    from .db import ARTIFACTS_DIR
except ImportError:
    from db import ARTIFACTS_DIR


def _get_artifact_file_path(workflow_id: str, stage_id: str, art_id: str, ext: str) -> Path:
    """Get the filesystem path for an artifact file."""
    return ARTIFACTS_DIR / workflow_id / stage_id / f"{art_id}.{ext}"


def _write_artifact_to_disk(workflow_id: str, stage_id: str, art_id: str, content: bytes, ext: str) -> tuple[str, int]:
    """Write artifact content to disk. Returns (relative_path, file_size)."""
    file_path = _get_artifact_file_path(workflow_id, stage_id, art_id, ext)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    relative = f"{workflow_id}/{stage_id}/{art_id}.{ext}"
    return relative, len(content)


def _ext_from_mime(mime_type: str) -> str:
    """Get file extension from mime type."""
    ext = mimetypes.guess_extension(mime_type) or ".bin"
    if ext.startswith("."):
        ext = ext[1:]
    if mime_type == "text/markdown":
        ext = "md"
    elif mime_type == "text/plain":
        ext = "txt"
    elif mime_type == "application/json":
        ext = "json"
    return ext
