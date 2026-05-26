"""Workflow routes extracted from plugin_api."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

try:
    from .activity import _record_user_activity
    from .auth_sessions import _require_authenticated_user
    from .common import _now, _uuid
    from .db import get_db
    from .events import _emit_event
    from .rows import row_to_dict, rows_to_list
    from .schemas import CreateWorkflowBody, TransitionBody, UpdateWorkflowBody
except ImportError:
    from activity import _record_user_activity
    from auth_sessions import _require_authenticated_user
    from common import _now, _uuid
    from db import get_db
    from events import _emit_event
    from rows import row_to_dict, rows_to_list
    from schemas import CreateWorkflowBody, TransitionBody, UpdateWorkflowBody

router = APIRouter()


@router.post("/workflows")
def create_workflow(body: CreateWorkflowBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        tmpl = row_to_dict(conn.execute("SELECT * FROM workflow_templates WHERE id=?", (body.template_id,)).fetchone())
        if not tmpl:
            raise HTTPException(404, "Template not found")

        first_stage = conn.execute(
            "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order LIMIT 1", (body.template_id,)
        ).fetchone()
        if not first_stage:
            raise HTTPException(400, "Template has no stages")

        now = _now()
        wf_id = _uuid("wi_")
        conn.execute(
            """INSERT INTO workflow_instances
               (id, template_id, agent_type_id, title, current_stage_id, status, priority, assignee, metadata_json, created_at, updated_at, created_by_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (wf_id, body.template_id, tmpl["agent_type_id"], body.title, first_stage["id"], "active", body.priority, body.assignee, body.metadata_json, now, now, user["id"]),
        )
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at, triggered_by_user_id) VALUES (?,?,?,?,?,?,?)",
            (wf_id, None, first_stage["id"], user["display_name"], "Workflow created", now, user["id"]),
        )
        _emit_event(conn, "workflow_created", wf_id)
        _record_user_activity(
            conn,
            user=user,
            action="workflow.create",
            target_type="workflow",
            workflow_id=wf_id,
            target_id=wf_id,
            metadata={"template_id": body.template_id, "initial_stage_id": first_stage["id"]},
        )

    return {"id": wf_id, "status": "active", "current_stage_id": first_stage["id"]}


@router.get("/workflows/{wf_id}")
def get_workflow(wf_id: str):
    with get_db() as conn:
        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (wf_id,)).fetchone())
        if not wf:
            raise HTTPException(404, "Workflow not found")

        all_stages = rows_to_list(conn.execute(
            "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order", (wf["template_id"],)
        ).fetchall())

        current_order = 0
        for s in all_stages:
            if s["id"] == wf["current_stage_id"]:
                current_order = s["stage_order"]
                break

        stages_with_status = []
        for s in all_stages:
            s["is_completed"] = s["stage_order"] < current_order
            s["is_current"] = s["id"] == wf["current_stage_id"]
            stages_with_status.append(s)

        artifacts = rows_to_list(conn.execute(
            "SELECT * FROM artifacts WHERE workflow_id=? ORDER BY created_at", (wf_id,)
        ).fetchall())

        transitions = rows_to_list(conn.execute(
            "SELECT * FROM stage_transitions WHERE workflow_id=? ORDER BY created_at", (wf_id,)
        ).fetchall())

        pending_approval = row_to_dict(conn.execute(
            "SELECT * FROM approval_requests WHERE workflow_id=? AND status='pending' LIMIT 1", (wf_id,)
        ).fetchone())

        activity_logs = rows_to_list(conn.execute(
            "SELECT * FROM activity_logs WHERE workflow_id=? ORDER BY created_at DESC, id DESC LIMIT 100", (wf_id,)
        ).fetchall())

        source_files = rows_to_list(conn.execute(
            "SELECT * FROM slack_workflow_source_files WHERE workflow_id=? ORDER BY created_at, id", (wf_id,)
        ).fetchall())
        material_collection_state = row_to_dict(conn.execute(
            "SELECT * FROM slack_material_collection_states WHERE workflow_id=?", (wf_id,)
        ).fetchone())
        worker_requests = rows_to_list(conn.execute(
            "SELECT * FROM planning_worker_requests WHERE workflow_id=? ORDER BY created_at, id", (wf_id,)
        ).fetchall())
        worker_results = rows_to_list(conn.execute(
            "SELECT * FROM planning_worker_results WHERE workflow_id=? ORDER BY created_at, id", (wf_id,)
        ).fetchall())

        wf["stages"] = stages_with_status
        wf["artifacts"] = artifacts
        wf["transitions"] = transitions
        wf["pending_approval"] = pending_approval
        wf["activity_logs"] = activity_logs
        wf["source_files"] = source_files
        wf["material_collection_state"] = material_collection_state
        wf["worker_requests"] = worker_requests
        wf["worker_results"] = worker_results

    return wf


@router.patch("/workflows/{wf_id}")
def update_workflow(wf_id: str, body: UpdateWorkflowBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (wf_id,)).fetchone()
        if not wf:
            raise HTTPException(404, "Workflow not found")

        updates = []
        params = []
        changed_fields: dict[str, Any] = {}
        for field in ("title", "status", "priority", "assignee", "metadata_json"):
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{field}=?")
                params.append(val)
                changed_fields[field] = val

        if updates:
            updates.append("updated_at=?")
            params.append(_now())
            params.append(wf_id)
            conn.execute(f"UPDATE workflow_instances SET {','.join(updates)} WHERE id=?", params)
            _emit_event(conn, "workflow_updated", wf_id)
            _record_user_activity(
                conn,
                user=user,
                action="workflow.update",
                target_type="workflow",
                workflow_id=wf_id,
                target_id=wf_id,
                metadata={"changes": changed_fields},
            )

    return {"ok": True}


@router.delete("/workflows/{wf_id}")
def delete_workflow(wf_id: str, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (wf_id,)).fetchone()
        if not wf:
            raise HTTPException(404, "Workflow not found")
        art_ids = [r["id"] for r in conn.execute("SELECT id FROM artifacts WHERE workflow_id=?", (wf_id,)).fetchall()]
        for aid in art_ids:
            conn.execute("DELETE FROM comments WHERE artifact_id=?", (aid,))
        conn.execute("DELETE FROM artifacts WHERE workflow_id=?", (wf_id,))
        conn.execute("DELETE FROM stage_transitions WHERE workflow_id=?", (wf_id,))
        conn.execute("DELETE FROM approval_requests WHERE workflow_id=?", (wf_id,))
        conn.execute("DELETE FROM workflow_instances WHERE id=?", (wf_id,))
        _emit_event(conn, "workflow_deleted", wf_id)
        _record_user_activity(
            conn,
            user=user,
            action="workflow.delete",
            target_type="workflow",
            workflow_id=wf_id,
            target_id=wf_id,
            metadata={"title": wf["title"]},
        )
    return {"ok": True}


@router.post("/workflows/{wf_id}/transition")
def transition_workflow(wf_id: str, body: TransitionBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (wf_id,)).fetchone())
        if not wf:
            raise HTTPException(404, "Workflow not found")

        target = row_to_dict(conn.execute("SELECT * FROM stage_definitions WHERE id=?", (body.to_stage_id,)).fetchone())
        if not target:
            raise HTTPException(400, "Invalid target stage")

        if target["transition_mode"] == "approval_required":
            now = _now()
            apr_id = _uuid("apr_")
            conn.execute(
                "INSERT INTO approval_requests (id, workflow_id, stage_id, status, requested_at, decided_by, note, requested_by_user_id) VALUES (?,?,?,?,?,?,?,?)",
                (apr_id, wf_id, body.to_stage_id, "pending", now, "", body.note, user["id"]),
            )
            conn.execute(
                "UPDATE workflow_instances SET status='pending_approval', updated_at=? WHERE id=?",
                (now, wf_id),
            )
            _emit_event(conn, "approval_requested", wf_id, payload={"approval_id": apr_id, "target_stage": body.to_stage_id})
            _record_user_activity(
                conn,
                user=user,
                action="workflow.request_approval",
                target_type="approval_request",
                workflow_id=wf_id,
                target_id=apr_id,
                metadata={"from_stage_id": wf["current_stage_id"], "to_stage_id": body.to_stage_id, "note": body.note},
            )
            return {"ok": True, "pending_approval": True, "approval_id": apr_id}

        now = _now()
        conn.execute(
            "UPDATE workflow_instances SET current_stage_id=?, updated_at=? WHERE id=?",
            (body.to_stage_id, now, wf_id),
        )
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at, triggered_by_user_id) VALUES (?,?,?,?,?,?,?)",
            (wf_id, wf["current_stage_id"], body.to_stage_id, user["display_name"], body.note, now, user["id"]),
        )
        _emit_event(conn, "stage_changed", wf_id, payload={"from": wf["current_stage_id"], "to": body.to_stage_id})
        _record_user_activity(
            conn,
            user=user,
            action="workflow.transition",
            target_type="workflow",
            workflow_id=wf_id,
            target_id=wf_id,
            metadata={"from_stage_id": wf["current_stage_id"], "to_stage_id": body.to_stage_id, "note": body.note},
        )

    return {"ok": True, "current_stage_id": body.to_stage_id}
