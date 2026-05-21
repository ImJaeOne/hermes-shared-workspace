"""Stats routes extracted from plugin_api."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

try:
    from .db import get_db
except ImportError:
    from db import get_db

router = APIRouter()


@router.get("/stats")
def get_stats():
    with get_db() as conn:
        active = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='active'").fetchone()["c"]
        completed = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='completed'").fetchone()["c"]
        failed = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='failed'").fetchone()["c"]
        pending_approvals = conn.execute("SELECT count(*) as c FROM approval_requests WHERE status='pending'").fetchone()["c"]

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        artifacts_today = conn.execute(
            "SELECT count(*) as c FROM artifacts WHERE created_at >= ?", (today,)
        ).fetchone()["c"]

        by_agent: dict[str, dict] = {}
        for row in conn.execute(
            "SELECT agent_type_id, status, count(*) as c FROM workflow_instances GROUP BY agent_type_id, status"
        ).fetchall():
            aid = row["agent_type_id"]
            if aid not in by_agent:
                by_agent[aid] = {"active": 0, "completed": 0, "failed": 0}
            s = row["status"]
            if s in by_agent[aid]:
                by_agent[aid][s] = row["c"]

    return {
        "active": active,
        "completed": completed,
        "failed": failed,
        "pending_approvals": pending_approvals,
        "artifacts_today": artifacts_today,
        "by_agent": by_agent,
    }
