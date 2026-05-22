"""Storage adapter abstraction for dashboard artifacts.

Issue #29 intentionally keeps the existing local-volume layout and public API
paths stable.  This module centralizes the local implementation so future
backends can be added without exposing storage keys to the frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from .artifact_files import _ext_from_mime, _write_artifact_to_disk
    from .db import ARTIFACTS_DIR
except ImportError:
    from artifact_files import _ext_from_mime, _write_artifact_to_disk
    from db import ARTIFACTS_DIR


@dataclass(frozen=True)
class StoredArtifact:
    storage_backend: str
    storage_key: str
    file_path: str
    file_size: int
    mime_type: str
    original_filename: str = ""


class LocalArtifactStorage:
    """Local-volume artifact storage adapter.

    `storage_key` intentionally mirrors the legacy `file_path` relative path for
    local storage compatibility.  The path layout remains:
    `{workflow_id}/{stage_id}/{artifact_id}.{ext}`.
    """

    backend = "local"

    def write_bytes(
        self,
        *,
        workflow_id: str,
        stage_id: str,
        artifact_id: str,
        content: bytes,
        mime_type: str,
        original_filename: str = "",
    ) -> StoredArtifact:
        ext = self._extension_for(mime_type, original_filename)
        storage_key, file_size = _write_artifact_to_disk(workflow_id, stage_id, artifact_id, content, ext)
        return StoredArtifact(
            storage_backend=self.backend,
            storage_key=storage_key,
            file_path=storage_key,
            file_size=file_size,
            mime_type=mime_type,
            original_filename=original_filename or "",
        )

    def resolve_path(self, storage_key: str) -> Path:
        if not storage_key:
            raise ValueError("storage_key is required")
        full_path = (ARTIFACTS_DIR / storage_key).resolve()
        base_dir = ARTIFACTS_DIR.resolve()
        if base_dir != full_path and base_dir not in full_path.parents:
            raise ValueError("storage_key points outside artifact storage")
        return full_path

    @staticmethod
    def _extension_for(mime_type: str, original_filename: str = "") -> str:
        if original_filename:
            suffix = Path(original_filename).suffix.lstrip(".").lower()
            if suffix:
                return suffix
        return _ext_from_mime(mime_type)


_STORAGE = LocalArtifactStorage()


def get_artifact_storage() -> LocalArtifactStorage:
    return _STORAGE
