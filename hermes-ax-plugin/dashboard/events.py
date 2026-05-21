"""AX event helpers shared across dashboard modules."""

from __future__ import annotations

import json
import sqlite3

try:
    from .common import _now
except ImportError:
    from common import _now


def _emit_event(
    conn: sqlite3.Connection,
    kind: str,
    workflow_id: str | None = None,
    artifact_id: str | None = None,
    payload: dict | None = None,
):
    conn.execute(
        "INSERT INTO ax_events (kind, workflow_id, artifact_id, payload, created_at) VALUES (?,?,?,?,?)",
        (kind, workflow_id, artifact_id, json.dumps(payload or {}), _now()),
    )
