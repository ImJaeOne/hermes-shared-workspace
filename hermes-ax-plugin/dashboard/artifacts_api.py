"""Artifact routes extracted from plugin_api."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

try:
    from .activity import _record_user_activity
    from .artifact_storage import get_artifact_storage
    from .auth_sessions import _require_authenticated_user
    from .common import _now, _uuid
    from .db import get_db
    from .events import _emit_event
    from .rows import row_to_dict, rows_to_list
    from .schemas import CreateArtifactBody, UpdateArtifactBody
except ImportError:
    from activity import _record_user_activity
    from artifact_storage import get_artifact_storage
    from auth_sessions import _require_authenticated_user
    from common import _now, _uuid
    from db import get_db
    from events import _emit_event
    from rows import row_to_dict, rows_to_list
    from schemas import CreateArtifactBody, UpdateArtifactBody

router = APIRouter()


def _reserve_artifact_version(conn, workflow_id: str, stage_id: str, artifact_type: str) -> int:
    """Mark older artifacts in a workflow/stage/type group as non-latest."""
    row = conn.execute(
        """SELECT COALESCE(MAX(version), 0) AS max_version
           FROM artifacts
           WHERE workflow_id=? AND stage_id=? AND artifact_type=?""",
        (workflow_id, stage_id, artifact_type),
    ).fetchone()
    next_version = int(row["max_version"] or 0) + 1
    conn.execute(
        """UPDATE artifacts
           SET is_latest=0
           WHERE workflow_id=? AND stage_id=? AND artifact_type=?""",
        (workflow_id, stage_id, artifact_type),
    )
    return next_version


@router.post("/artifacts")
def create_artifact(body: CreateArtifactBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (body.workflow_id,)).fetchone()
        if not wf:
            raise HTTPException(404, "Workflow not found")

        now = _now()
        art_id = _uuid("art_")
        mime_type = body.content_type

        content_bytes = body.content.encode("utf-8")
        stored = get_artifact_storage().write_bytes(
            workflow_id=body.workflow_id,
            stage_id=body.stage_id,
            artifact_id=art_id,
            content=content_bytes,
            mime_type=mime_type,
        )
        version = _reserve_artifact_version(conn, body.workflow_id, body.stage_id, body.artifact_type)

        conn.execute(
            """INSERT INTO artifacts
               (id, workflow_id, stage_id, artifact_type, title, content, content_type, status,
                file_path, file_size, mime_type, storage_backend, storage_key, original_filename,
                version, is_latest, created_at, updated_at, created_by_user_id, updated_by_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                art_id, body.workflow_id, body.stage_id, body.artifact_type, body.title,
                body.content, body.content_type, body.status, stored.file_path, stored.file_size,
                stored.mime_type, stored.storage_backend, stored.storage_key, stored.original_filename,
                version, 1, now, now, user["id"], user["id"],
            ),
        )
        _emit_event(conn, "artifact_added", body.workflow_id, art_id)
        _record_user_activity(
            conn,
            user=user,
            action="artifact.create",
            target_type="artifact",
            workflow_id=body.workflow_id,
            artifact_id=art_id,
            target_id=art_id,
            metadata={"stage_id": body.stage_id, "artifact_type": body.artifact_type, "title": body.title},
        )

    return {"id": art_id}


@router.post("/artifacts/upload")
async def upload_artifact(
    request: Request,
    workflow_id: str = Form(...),
    stage_id: str = Form(...),
    artifact_type: str = Form(...),
    title: str = Form(...),
    status: str = Form("draft"),
    file: UploadFile = File(...),
):
    """Upload a file as an artifact."""
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
        if not wf:
            raise HTTPException(404, "Workflow not found")

        now = _now()
        art_id = _uuid("art_")

        mime_type = file.content_type or "application/octet-stream"
        original_filename = file.filename or ""

        content_bytes = await file.read()
        stored = get_artifact_storage().write_bytes(
            workflow_id=workflow_id,
            stage_id=stage_id,
            artifact_id=art_id,
            content=content_bytes,
            mime_type=mime_type,
            original_filename=original_filename,
        )
        version = _reserve_artifact_version(conn, workflow_id, stage_id, artifact_type)

        content_text = ""
        if mime_type.startswith("text/") or mime_type == "application/json":
            try:
                content_text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                pass

        conn.execute(
            """INSERT INTO artifacts
               (id, workflow_id, stage_id, artifact_type, title, content, content_type, status,
                file_path, file_size, mime_type, storage_backend, storage_key, original_filename,
                version, is_latest, created_at, updated_at, created_by_user_id, updated_by_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                art_id, workflow_id, stage_id, artifact_type, title, content_text, mime_type, status,
                stored.file_path, stored.file_size, stored.mime_type, stored.storage_backend,
                stored.storage_key, stored.original_filename, version, 1, now, now, user["id"], user["id"],
            ),
        )
        _emit_event(conn, "artifact_added", workflow_id, art_id)
        _record_user_activity(
            conn,
            user=user,
            action="artifact.upload",
            target_type="artifact",
            workflow_id=workflow_id,
            artifact_id=art_id,
            target_id=art_id,
            metadata={"stage_id": stage_id, "artifact_type": artifact_type, "title": title, "mime_type": mime_type, "file_size": stored.file_size},
        )

    return {"id": art_id, "file_path": stored.file_path, "file_size": stored.file_size, "mime_type": stored.mime_type}


@router.get("/artifacts/{art_id}")
def get_artifact(art_id: str):
    with get_db() as conn:
        art = row_to_dict(conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone())
        if not art:
            raise HTTPException(404, "Artifact not found")
        art["comments"] = rows_to_list(
            conn.execute("SELECT * FROM comments WHERE artifact_id=? ORDER BY created_at", (art_id,)).fetchall()
        )
    return art


@router.get("/artifacts/{art_id}/file")
def get_artifact_file(art_id: str):
    """Serve artifact file from disk."""
    with get_db() as conn:
        art = row_to_dict(conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone())
        if not art:
            raise HTTPException(404, "Artifact not found")

    storage = get_artifact_storage()
    storage_key = art.get("storage_key") or art.get("file_path", "")
    if not storage_key:
        if art["content"]:
            mime = art.get("mime_type") or art["content_type"]
            content_bytes = art["content"].encode("utf-8")
            stored = storage.write_bytes(
                workflow_id=art["workflow_id"],
                stage_id=art["stage_id"],
                artifact_id=art_id,
                content=content_bytes,
                mime_type=mime,
                original_filename=art.get("original_filename") or "",
            )
            with get_db() as conn:
                conn.execute(
                    """UPDATE artifacts
                       SET file_path=?, file_size=?, mime_type=?, storage_backend=?, storage_key=?
                       WHERE id=?""",
                    (stored.file_path, stored.file_size, stored.mime_type, stored.storage_backend, stored.storage_key, art_id),
                )
            storage_key = stored.storage_key
        else:
            raise HTTPException(404, "No file content")

    try:
        full_path = storage.resolve_path(storage_key)
    except ValueError:
        raise HTTPException(400, "Invalid artifact storage key")
    if not full_path.exists():
        raise HTTPException(404, "File not found on disk")

    mime = art.get("mime_type") or art["content_type"]
    return FileResponse(str(full_path), media_type=mime)


@router.patch("/artifacts/{art_id}")
def update_artifact(art_id: str, body: UpdateArtifactBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        art = row_to_dict(conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone())
        if not art:
            raise HTTPException(404, "Artifact not found")

        updates = []
        params = []
        changed_fields: dict[str, Any] = {}
        for field in ("title", "content", "content_type", "status"):
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{field}=?")
                params.append(val)
                changed_fields[field] = val

        if body.content is not None:
            mime = body.content_type or art["content_type"]
            content_bytes = body.content.encode("utf-8")
            stored = get_artifact_storage().write_bytes(
                workflow_id=art["workflow_id"],
                stage_id=art["stage_id"],
                artifact_id=art_id,
                content=content_bytes,
                mime_type=mime,
                original_filename=art.get("original_filename") or "",
            )
            updates.extend(["file_path=?", "file_size=?", "mime_type=?", "storage_backend=?", "storage_key=?"])
            params.extend([stored.file_path, stored.file_size, stored.mime_type, stored.storage_backend, stored.storage_key])
            changed_fields["file_path"] = stored.file_path
            changed_fields["file_size"] = stored.file_size
            changed_fields["mime_type"] = mime

        if updates:
            updates.extend(["updated_at=?", "updated_by_user_id=?"])
            params.extend([_now(), user["id"], art_id])
            conn.execute(f"UPDATE artifacts SET {','.join(updates)} WHERE id=?", params)
            _emit_event(conn, "artifact_updated", art["workflow_id"], art_id)
            _record_user_activity(
                conn,
                user=user,
                action="artifact.update",
                target_type="artifact",
                workflow_id=art["workflow_id"],
                artifact_id=art_id,
                target_id=art_id,
                metadata={"changes": changed_fields},
            )

    return {"ok": True}
