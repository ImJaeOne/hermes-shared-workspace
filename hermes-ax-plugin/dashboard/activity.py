"""Activity log helpers for the Hermes AX dashboard API."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()



def _uuid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"



def _actor_label(user: sqlite3.Row | dict | None, fallback: str = "system") -> str:
    if not user:
        return fallback
    return (user.get("display_name") if isinstance(user, dict) else user["display_name"]) or (
        user.get("username") if isinstance(user, dict) else user["username"]
    ) or fallback



def _record_activity(
    conn: sqlite3.Connection,
    *,
    action: str,
    target_type: str,
    actor_kind: str,
    workflow_id: str | None = None,
    target_id: str | None = None,
    artifact_id: str | None = None,
    actor_user_id: str | None = None,
    actor_label: str = "system",
    metadata: dict | None = None,
):
    conn.execute(
        """INSERT INTO activity_logs
           (id, actor_kind, actor_user_id, actor_label, action, target_type, target_id, workflow_id, artifact_id, metadata_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            _uuid("act_"),
            actor_kind,
            actor_user_id,
            actor_label,
            action,
            target_type,
            target_id,
            workflow_id,
            artifact_id,
            json.dumps(metadata or {}, ensure_ascii=False),
            _now(),
        ),
    )



def _record_user_activity(
    conn: sqlite3.Connection,
    *,
    user: sqlite3.Row | dict,
    action: str,
    target_type: str,
    workflow_id: str | None = None,
    target_id: str | None = None,
    artifact_id: str | None = None,
    metadata: dict | None = None,
):
    _record_activity(
        conn,
        action=action,
        target_type=target_type,
        actor_kind="human",
        actor_user_id=user["id"],
        actor_label=_actor_label(user, fallback="user"),
        workflow_id=workflow_id,
        target_id=target_id,
        artifact_id=artifact_id,
        metadata=metadata,
    )
