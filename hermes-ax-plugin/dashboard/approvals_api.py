"""Approval routes extracted from plugin_api."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

try:
    from .activity import _actor_label, _record_user_activity
    from .auth_sessions import _require_authenticated_user
    from .common import _now
    from .db import get_db
    from .events import _emit_event
    from .rows import row_to_dict, rows_to_list
    from .schemas import DecideApprovalBody
except ImportError:
    from activity import _actor_label, _record_user_activity
    from auth_sessions import _require_authenticated_user
    from common import _now
    from db import get_db
    from events import _emit_event
    from rows import row_to_dict, rows_to_list
    from schemas import DecideApprovalBody

router = APIRouter()


@router.get("/approvals")
def list_approvals(workflow_id: str | None = Query(None), status: str | None = Query(None)):
    with get_db() as conn:
        query = """
            SELECT ar.*, wi.title as workflow_title, sd.name as stage_name
            FROM approval_requests ar
            JOIN workflow_instances wi ON ar.workflow_id = wi.id
            JOIN stage_definitions sd ON ar.stage_id = sd.id
        """
        conditions = []
        params = []
        if workflow_id:
            conditions.append("ar.workflow_id=?")
            params.append(workflow_id)
        if status:
            conditions.append("ar.status=?")
            params.append(status)
        else:
            conditions.append("ar.status='pending'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY ar.requested_at DESC"

        approvals = rows_to_list(conn.execute(query, params).fetchall())
    return approvals


@router.post("/approvals/{approval_id}/decide")
def decide_approval(approval_id: str, body: DecideApprovalBody, request: Request):
    if body.status not in ("approved", "rejected"):
        raise HTTPException(400, "Status must be 'approved' or 'rejected'")

    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        apr = row_to_dict(conn.execute("SELECT * FROM approval_requests WHERE id=?", (approval_id,)).fetchone())
        if not apr:
            raise HTTPException(404, "Approval request not found")
        if apr["status"] != "pending":
            raise HTTPException(400, "Approval already decided")

        now = _now()
        decided_by = body.decided_by.strip() or _actor_label(user, fallback=user["username"])
        conn.execute(
            "UPDATE approval_requests SET status=?, decided_by=?, decided_at=?, note=?, decided_by_user_id=? WHERE id=?",
            (body.status, decided_by, now, body.note, user["id"], approval_id),
        )

        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (apr["workflow_id"],)).fetchone())

        if body.status == "approved":
            conn.execute(
                "UPDATE workflow_instances SET current_stage_id=?, status='active', updated_at=? WHERE id=?",
                (apr["stage_id"], now, apr["workflow_id"]),
            )
            conn.execute(
                "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at, triggered_by_user_id) VALUES (?,?,?,?,?,?,?)",
                (apr["workflow_id"], wf["current_stage_id"], apr["stage_id"], decided_by, f"승인: {body.note}" if body.note else "승인됨", now, user["id"]),
            )
            _emit_event(conn, "approval_approved", apr["workflow_id"], payload={"approval_id": approval_id, "trigger_next": True})
            _emit_event(conn, "stage_changed", apr["workflow_id"], payload={"from": wf["current_stage_id"], "to": apr["stage_id"], "trigger_next": True})
        else:
            conn.execute(
                "UPDATE workflow_instances SET status='active', updated_at=? WHERE id=?",
                (now, apr["workflow_id"]),
            )
            _emit_event(conn, "approval_rejected", apr["workflow_id"], payload={"approval_id": approval_id})

        _record_user_activity(
            conn,
            user=user,
            action=f"approval.{body.status}",
            target_type="approval_request",
            workflow_id=apr["workflow_id"],
            target_id=approval_id,
            metadata={"stage_id": apr["stage_id"], "note": body.note},
        )

    return {"ok": True, "status": body.status}
