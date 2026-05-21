"""Artifact routes extracted from plugin_api."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

try:
    from .activity import _record_user_activity
    from .artifact_files import _ext_from_mime, _write_artifact_to_disk
    from .auth_sessions import _require_authenticated_user
    from .common import _now, _uuid
    from .db import ARTIFACTS_DIR, get_db
    from .events import _emit_event
    from .rows import row_to_dict, rows_to_list
    from .schemas import CreateArtifactBody, UpdateArtifactBody
except ImportError:
    from activity import _record_user_activity
    from artifact_files import _ext_from_mime, _write_artifact_to_disk
    from auth_sessions import _require_authenticated_user
    from common import _now, _uuid
    from db import ARTIFACTS_DIR, get_db
    from events import _emit_event
    from rows import row_to_dict, rows_to_list
    from schemas import CreateArtifactBody, UpdateArtifactBody

router = APIRouter()


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

        ext = _ext_from_mime(mime_type)
        content_bytes = body.content.encode("utf-8")
        file_path, file_size = _write_artifact_to_disk(body.workflow_id, body.stage_id, art_id, content_bytes, ext)

        conn.execute(
            """INSERT INTO artifacts
               (id, workflow_id, stage_id, artifact_type, title, content, content_type, status, file_path, file_size, mime_type, created_at, updated_at, created_by_user_id, updated_by_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (art_id, body.workflow_id, body.stage_id, body.artifact_type, body.title, body.content, body.content_type, body.status, file_path, file_size, mime_type, now, now, user["id"], user["id"]),
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
        ext = _ext_from_mime(mime_type)
        if file.filename:
            parts = file.filename.rsplit(".", 1)
            if len(parts) > 1:
                ext = parts[1].lower()

        content_bytes = await file.read()
        file_path, file_size = _write_artifact_to_disk(workflow_id, stage_id, art_id, content_bytes, ext)

        content_text = ""
        if mime_type.startswith("text/") or mime_type == "application/json":
            try:
                content_text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                pass

        conn.execute(
            """INSERT INTO artifacts
               (id, workflow_id, stage_id, artifact_type, title, content, content_type, status, file_path, file_size, mime_type, created_at, updated_at, created_by_user_id, updated_by_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (art_id, workflow_id, stage_id, artifact_type, title, content_text, mime_type, status, file_path, file_size, mime_type, now, now, user["id"], user["id"]),
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
            metadata={"stage_id": stage_id, "artifact_type": artifact_type, "title": title, "mime_type": mime_type, "file_size": file_size},
        )

    return {"id": art_id, "file_path": file_path, "file_size": file_size, "mime_type": mime_type}


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

    file_path = art.get("file_path", "")
    if not file_path:
        if art["content"]:
            ext = _ext_from_mime(art.get("mime_type") or art["content_type"])
            content_bytes = art["content"].encode("utf-8")
            rel_path, file_size = _write_artifact_to_disk(art["workflow_id"], art["stage_id"], art_id, content_bytes, ext)
            with get_db() as conn:
                conn.execute(
                    "UPDATE artifacts SET file_path=?, file_size=?, mime_type=? WHERE id=?",
                    (rel_path, file_size, art.get("mime_type") or art["content_type"], art_id),
                )
            file_path = rel_path
        else:
            raise HTTPException(404, "No file content")

    full_path = ARTIFACTS_DIR / file_path
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
            ext = _ext_from_mime(mime)
            content_bytes = body.content.encode("utf-8")
            file_path, file_size = _write_artifact_to_disk(art["workflow_id"], art["stage_id"], art_id, content_bytes, ext)
            updates.extend(["file_path=?", "file_size=?", "mime_type=?"])
            params.extend([file_path, file_size, mime])
            changed_fields["file_path"] = file_path
            changed_fields["file_size"] = file_size
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
