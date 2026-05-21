"""Comment routes extracted from plugin_api."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

try:
    from .activity import _actor_label, _record_user_activity
    from .auth_sessions import _require_authenticated_user
    from .common import _now
    from .db import get_db
    from .events import _emit_event
    from .schemas import CreateCommentBody, UpdateCommentBody
except ImportError:
    from activity import _actor_label, _record_user_activity
    from auth_sessions import _require_authenticated_user
    from common import _now
    from db import get_db
    from events import _emit_event
    from schemas import CreateCommentBody, UpdateCommentBody

router = APIRouter()


@router.post("/artifacts/{art_id}/comments")
def create_comment(art_id: str, body: CreateCommentBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        art = conn.execute("SELECT * FROM artifacts WHERE id=?", (art_id,)).fetchone()
        if not art:
            raise HTTPException(404, "Artifact not found")

        now = _now()
        author = body.author.strip() or _actor_label(user, fallback=user["username"])
        cur = conn.execute(
            "INSERT INTO comments (artifact_id, author, author_user_id, body, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (art_id, author, user["id"], body.body, now, now),
        )
        comment_id = cur.lastrowid
        _emit_event(conn, "comment_added", art["workflow_id"], art_id, {"comment_id": comment_id})
        _record_user_activity(
            conn,
            user=user,
            action="comment.create",
            target_type="comment",
            workflow_id=art["workflow_id"],
            artifact_id=art_id,
            target_id=str(comment_id),
            metadata={"artifact_id": art_id},
        )

    return {"id": comment_id}


@router.patch("/comments/{comment_id}")
def update_comment(comment_id: int, body: UpdateCommentBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        comment = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
        if not comment:
            raise HTTPException(404, "Comment not found")
        conn.execute(
            "UPDATE comments SET body=?, updated_at=? WHERE id=?",
            (body.body, _now(), comment_id),
        )
        art = conn.execute("SELECT workflow_id FROM artifacts WHERE id=?", (comment["artifact_id"],)).fetchone()
        if art:
            _emit_event(conn, "comment_updated", art["workflow_id"], comment["artifact_id"], {"comment_id": comment_id})
            _record_user_activity(
                conn,
                user=user,
                action="comment.update",
                target_type="comment",
                workflow_id=art["workflow_id"],
                artifact_id=comment["artifact_id"],
                target_id=str(comment_id),
                metadata={"artifact_id": comment["artifact_id"]},
            )

    return {"ok": True}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        comment = conn.execute("SELECT * FROM comments WHERE id=?", (comment_id,)).fetchone()
        if not comment:
            raise HTTPException(404, "Comment not found")
        art = conn.execute("SELECT workflow_id FROM artifacts WHERE id=?", (comment["artifact_id"],)).fetchone()
        conn.execute("DELETE FROM comments WHERE id=?", (comment_id,))
        if art:
            _emit_event(conn, "comment_deleted", art["workflow_id"], comment["artifact_id"], {"comment_id": comment_id})
            _record_user_activity(
                conn,
                user=user,
                action="comment.delete",
                target_type="comment",
                workflow_id=art["workflow_id"],
                artifact_id=comment["artifact_id"],
                target_id=str(comment_id),
                metadata={"artifact_id": comment["artifact_id"]},
            )

    return {"ok": True}
