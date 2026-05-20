"""Hermes AX Plugin API — FastAPI backend for Agent eXecution Dashboard."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse

try:
    from .activity import _actor_label, _record_activity, _record_user_activity
    from .auth import (
        AUTH_SESSION_TTL_SECONDS,
        AX_SESSION_COOKIE,
        AX_SESSION_COOKIE_SECURE_ENV,
        hash_session_token,
        normalize_username,
        parse_timestamp,
        serialize_user,
        verify_password,
        env_flag,
    )
    from .bootstrap import _upsert_bootstrap_admin
    from .common import _now, _uuid
    from .db_schema import SCHEMA_SQL, _run_migrations
    from .seed import seed_if_empty
    from .rows import row_to_dict, rows_to_list
    from .schemas import (
        CreateArtifactBody,
        CreateCommentBody,
        CreateSkillBindingBody,
        CreateSkillBody,
        CreateTemplateBody,
        CreateWorkflowBody,
        DecideApprovalBody,
        LoginBody,
        TransitionBody,
        UpdateArtifactBody,
        UpdateCommentBody,
        UpdateDefinitionBody,
        UpdateSkillBody,
        UpdateStageBody,
        UpdateWorkflowBody,
    )
except ImportError:
    from activity import _actor_label, _record_activity, _record_user_activity
    from auth import (
        AUTH_SESSION_TTL_SECONDS,
        AX_SESSION_COOKIE,
        AX_SESSION_COOKIE_SECURE_ENV,
        env_flag,
        hash_session_token,
        normalize_username,
        parse_timestamp,
        serialize_user,
        verify_password,
    )
    from bootstrap import _upsert_bootstrap_admin
    from common import _now, _uuid
    from db_schema import SCHEMA_SQL, _run_migrations
    from seed import seed_if_empty
    from rows import row_to_dict, rows_to_list
    from schemas import (
        CreateArtifactBody,
        CreateCommentBody,
        CreateSkillBindingBody,
        CreateSkillBody,
        CreateTemplateBody,
        CreateWorkflowBody,
        DecideApprovalBody,
        LoginBody,
        TransitionBody,
        UpdateArtifactBody,
        UpdateCommentBody,
        UpdateDefinitionBody,
        UpdateSkillBody,
        UpdateStageBody,
        UpdateWorkflowBody,
    )

router = APIRouter()

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
PLUGIN_DATA_DIR = HERMES_HOME / "plugins" / "hermes-ax-plugin"
DB_DIR = PLUGIN_DATA_DIR
DB_PATH = DB_DIR / "ax.db"
ARTIFACTS_DIR = DB_DIR / "artifacts"

def _require_authenticated_user(conn: sqlite3.Connection, request: Request) -> dict[str, Any]:
    token = _get_request_session_token(request)
    auth = _get_authenticated_session(conn, token)
    if not auth:
        raise HTTPException(401, "Authentication required")
    return auth["user"]


def _create_auth_session(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    now_dt = datetime.now(timezone.utc)
    expires_dt = now_dt + timedelta(seconds=AUTH_SESSION_TTL_SECONDS)
    session_token = secrets.token_urlsafe(32)
    session_id = _uuid("axs_")
    now = now_dt.isoformat()
    expires_at = expires_dt.isoformat()
    conn.execute(
        """INSERT INTO auth_sessions
           (id, user_id, session_token_hash, expires_at, created_at, last_seen_at)
           VALUES (?,?,?,?,?,?)""",
        (session_id, user_id, hash_session_token(session_token), expires_at, now, now),
    )
    return {
        "id": session_id,
        "token": session_token,
        "expires_at": expires_at,
        "created_at": now,
        "last_seen_at": now,
    }


def _get_request_session_token(request: Request) -> str:
    header_token = request.headers.get("X-Hermes-Session-Token", "").strip()
    if header_token:
        return header_token
    return request.cookies.get(AX_SESSION_COOKIE, "").strip()


def _get_authenticated_session(conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
    if not token:
        return None

    row = conn.execute(
        """SELECT
               s.id,
               s.user_id,
               s.expires_at,
               s.created_at,
               s.last_seen_at,
               u.username,
               u.display_name,
               u.role,
               u.is_active,
               u.created_at AS user_created_at,
               u.updated_at AS user_updated_at
           FROM auth_sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.session_token_hash=?""",
        (hash_session_token(token),),
    ).fetchone()
    if not row:
        return None

    if not row["is_active"]:
        conn.execute("DELETE FROM auth_sessions WHERE id=?", (row["id"],))
        return None

    if parse_timestamp(row["expires_at"]) <= datetime.now(timezone.utc):
        conn.execute("DELETE FROM auth_sessions WHERE id=?", (row["id"],))
        return None

    last_seen_at = _now()
    conn.execute("UPDATE auth_sessions SET last_seen_at=? WHERE id=?", (last_seen_at, row["id"]))
    return {
        "session": {
            "id": row["id"],
            "user_id": row["user_id"],
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "last_seen_at": last_seen_at,
        },
        "user": {
            "id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": row["user_created_at"],
            "updated_at": row["user_updated_at"],
        },
    }


@contextmanager
def get_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _emit_event(conn: sqlite3.Connection, kind: str, workflow_id: str | None = None, artifact_id: str | None = None, payload: dict | None = None):
    conn.execute(
        "INSERT INTO ax_events (kind, workflow_id, artifact_id, payload, created_at) VALUES (?,?,?,?,?)",
        (kind, workflow_id, artifact_id, json.dumps(payload or {}), _now()),
    )


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)
        seed_if_empty(conn, _now, _emit_event)
        _upsert_bootstrap_admin(conn)


# Run on import
init_db()

# ---------------------------------------------------------------------------
# API: Auth
# ---------------------------------------------------------------------------

@router.post("/auth/login")
def login(body: LoginBody, response: Response):
    username = normalize_username(body.username)
    password = body.password.strip()
    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
            raise HTTPException(401, "Invalid username or password")

        session = _create_auth_session(conn, user["id"])
        _record_user_activity(
            conn,
            user=user,
            action="auth.login",
            target_type="session",
            target_id=session["id"],
            metadata={"username": user["username"]},
        )

    response.set_cookie(
        key=AX_SESSION_COOKIE,
        value=session["token"],
        httponly=True,
        samesite="lax",
        secure=env_flag(AX_SESSION_COOKIE_SECURE_ENV, default=False),
        max_age=AUTH_SESSION_TTL_SECONDS,
        path="/",
    )
    return {
        "ok": True,
        "token": session["token"],
        "expires_at": session["expires_at"],
        "user": serialize_user(user),
    }


@router.get("/auth/session")
def get_auth_session(request: Request, response: Response):
    token = _get_request_session_token(request)
    with get_db() as conn:
        auth = _get_authenticated_session(conn, token)

    if not auth:
        response.delete_cookie(key=AX_SESSION_COOKIE, path="/")
        return {"authenticated": False, "user": None, "expires_at": None}

    return {
        "authenticated": True,
        "user": auth["user"],
        "expires_at": auth["session"]["expires_at"],
    }


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = _get_request_session_token(request)
    with get_db() as conn:
        auth = _get_authenticated_session(conn, token) if token else None
        if token:
            conn.execute(
                "DELETE FROM auth_sessions WHERE session_token_hash=?",
                (hash_session_token(token),),
            )
        if auth:
            _record_user_activity(
                conn,
                user=auth["user"],
                action="auth.logout",
                target_type="session",
                target_id=auth["session"]["id"],
                metadata={"username": auth["user"]["username"]},
            )

    response.delete_cookie(key=AX_SESSION_COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Agents
# ---------------------------------------------------------------------------

@router.get("/agents")
def list_agents():
    with get_db() as conn:
        agents = rows_to_list(conn.execute("SELECT * FROM agent_types ORDER BY id").fetchall())
        for agent in agents:
            templates = rows_to_list(
                conn.execute("SELECT * FROM workflow_templates WHERE agent_type_id=? AND is_active=1", (agent["id"],)).fetchall()
            )
            for tmpl in templates:
                tmpl["stages"] = rows_to_list(
                    conn.execute("SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order", (tmpl["id"],)).fetchall()
                )
            agent["templates"] = templates
    return agents


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    with get_db() as conn:
        agent = row_to_dict(conn.execute("SELECT * FROM agent_types WHERE id=?", (agent_id,)).fetchone())
        if not agent:
            raise HTTPException(404, "Agent not found")
        templates = rows_to_list(
            conn.execute("SELECT * FROM workflow_templates WHERE agent_type_id=? AND is_active=1", (agent_id,)).fetchall()
        )
        stages = []
        for tmpl in templates:
            tmpl["stages"] = rows_to_list(
                conn.execute("SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order", (tmpl["id"],)).fetchall()
            )
            stages.extend(tmpl["stages"])
        agent["templates"] = templates
        agent["stages"] = stages
    return agent


# ---------------------------------------------------------------------------
# API: Templates
# ---------------------------------------------------------------------------

@router.post("/templates")
def create_template(body: CreateTemplateBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        agent = conn.execute("SELECT * FROM agent_types WHERE id=?", (body.agent_type_id,)).fetchone()
        if not agent:
            raise HTTPException(404, "Agent not found")

        now = _now()
        tmpl_id = _uuid("tmpl_")
        conn.execute(
            "INSERT INTO workflow_templates (id, agent_type_id, name, is_active, version, created_at) VALUES (?,?,?,1,1,?)",
            (tmpl_id, body.agent_type_id, body.name, now),
        )

        for i, stage in enumerate(body.stages):
            stage_id = _uuid("stg_")
            slug = stage.slug or stage.name.lower().replace(" ", "-")
            conn.execute(
                "INSERT INTO stage_definitions (id, template_id, name, slug, stage_order, expected_artifacts, trigger_conditions, transition_mode, approval_roles, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (stage_id, tmpl_id, stage.name, slug, i, "[]", "{}", "auto", "[]", now),
            )

        _emit_event(conn, "template_created", payload={"template_id": tmpl_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.create",
            target_type="template",
            target_id=tmpl_id,
            metadata={"agent_type_id": body.agent_type_id, "stage_count": len(body.stages), "name": body.name},
        )

    return {"id": tmpl_id}


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")
        active_count = conn.execute(
            "SELECT count(*) as c FROM workflow_instances WHERE template_id=? AND status IN ('active','pending_approval')",
            (template_id,),
        ).fetchone()["c"]
        if active_count > 0:
            raise HTTPException(400, f"활성 워크플로우 {active_count}개가 있어 삭제할 수 없습니다. 먼저 워크플로우를 완료하거나 삭제하세요.")
        wf_ids = [r["id"] for r in conn.execute("SELECT id FROM workflow_instances WHERE template_id=?", (template_id,)).fetchall()]
        for wid in wf_ids:
            art_ids = [r["id"] for r in conn.execute("SELECT id FROM artifacts WHERE workflow_id=?", (wid,)).fetchall()]
            for aid in art_ids:
                conn.execute("DELETE FROM comments WHERE artifact_id=?", (aid,))
            conn.execute("DELETE FROM artifacts WHERE workflow_id=?", (wid,))
            conn.execute("DELETE FROM stage_transitions WHERE workflow_id=?", (wid,))
            conn.execute("DELETE FROM approval_requests WHERE workflow_id=?", (wid,))
        conn.execute("DELETE FROM workflow_instances WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM workflow_skill_bindings WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM workflow_definitions WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM stage_definitions WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM workflow_templates WHERE id=?", (template_id,))
        _emit_event(conn, "template_deleted", payload={"template_id": template_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.delete",
            target_type="template",
            target_id=template_id,
            metadata={"name": tmpl["name"]},
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Board (Kanban)
# ---------------------------------------------------------------------------

@router.get("/board/{agent_id}")
def get_board(agent_id: str, template_id: str | None = Query(None)):
    with get_db() as conn:
        agent = conn.execute("SELECT * FROM agent_types WHERE id=?", (agent_id,)).fetchone()
        if not agent:
            raise HTTPException(404, "Agent not found")

        # Get template: specified or first active
        if template_id:
            tmpl = conn.execute(
                "SELECT * FROM workflow_templates WHERE id=? AND agent_type_id=? AND is_active=1", (template_id, agent_id)
            ).fetchone()
        else:
            tmpl = conn.execute(
                "SELECT * FROM workflow_templates WHERE agent_type_id=? AND is_active=1 ORDER BY created_at LIMIT 1", (agent_id,)
            ).fetchone()
        if not tmpl:
            return {"agent_type_id": agent_id, "template_id": None, "columns": [], "completed": []}

        stages = rows_to_list(
            conn.execute("SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order", (tmpl["id"],)).fetchall()
        )

        columns = []
        for stage in stages:
            workflows = rows_to_list(conn.execute(
                """SELECT wi.*, sd.name as current_stage_name, sd.stage_order as current_stage_order,
                          (SELECT count(*) FROM artifacts WHERE workflow_id=wi.id) as artifact_count
                   FROM workflow_instances wi
                   JOIN stage_definitions sd ON wi.current_stage_id = sd.id
                   WHERE wi.template_id=? AND wi.current_stage_id=? AND wi.status IN ('active','pending_approval')
                   ORDER BY wi.priority DESC, wi.updated_at DESC""",
                (tmpl["id"], stage["id"]),
            ).fetchall())
            columns.append({"stage": stage, "workflows": workflows})

        completed = rows_to_list(conn.execute(
            """SELECT wi.*, sd.name as current_stage_name, sd.stage_order as current_stage_order,
                      (SELECT count(*) FROM artifacts WHERE workflow_id=wi.id) as artifact_count
               FROM workflow_instances wi
               JOIN stage_definitions sd ON wi.current_stage_id = sd.id
               WHERE wi.template_id=? AND wi.status IN ('completed','failed','cancelled')
               ORDER BY wi.updated_at DESC LIMIT 20""",
            (tmpl["id"],),
        ).fetchall())

    return {"agent_type_id": agent_id, "template_id": tmpl["id"], "columns": columns, "completed": completed}


# ---------------------------------------------------------------------------
# API: Stats
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# API: Workflows
# ---------------------------------------------------------------------------

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

        wf["stages"] = stages_with_status
        wf["artifacts"] = artifacts
        wf["transitions"] = transitions
        wf["pending_approval"] = pending_approval
        wf["activity_logs"] = activity_logs

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


# ---------------------------------------------------------------------------
# API: Artifacts
# ---------------------------------------------------------------------------

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
    # Common overrides
    if mime_type == "text/markdown":
        ext = "md"
    elif mime_type == "text/plain":
        ext = "txt"
    elif mime_type == "application/json":
        ext = "json"
    return ext


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


# ---------------------------------------------------------------------------
# API: Comments
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# API: Skills
# ---------------------------------------------------------------------------

@router.get("/skills")
def list_skills(agent_type_id: str | None = Query(None)):
    with get_db() as conn:
        if agent_type_id:
            skills = rows_to_list(conn.execute(
                "SELECT * FROM skills WHERE agent_type_id=? OR agent_type_id IS NULL ORDER BY name",
                (agent_type_id,),
            ).fetchall())
        else:
            skills = rows_to_list(conn.execute("SELECT * FROM skills ORDER BY name").fetchall())
    return skills


@router.post("/skills")
def create_skill(body: CreateSkillBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        now = _now()
        skill_id = _uuid("skill_")
        conn.execute(
            "INSERT INTO skills (id, name, description, content, agent_type_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (skill_id, body.name, body.description, body.content, body.agent_type_id, now, now),
        )
        _emit_event(conn, "skill_created", payload={"skill_id": skill_id})
        _record_user_activity(
            conn,
            user=user,
            action="skill.create",
            target_type="skill",
            target_id=skill_id,
            metadata={"name": body.name, "agent_type_id": body.agent_type_id},
        )
    return {"id": skill_id}


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str):
    with get_db() as conn:
        skill = row_to_dict(conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone())
        if not skill:
            raise HTTPException(404, "Skill not found")
    return skill


@router.patch("/skills/{skill_id}")
def update_skill(skill_id: str, body: UpdateSkillBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "Skill not found")

        updates = []
        params = []
        changed_fields: dict[str, Any] = {}
        for field in ("name", "description", "content", "agent_type_id"):
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{field}=?")
                params.append(val)
                changed_fields[field] = val

        if updates:
            updates.append("updated_at=?")
            params.append(_now())
            params.append(skill_id)
            conn.execute(f"UPDATE skills SET {','.join(updates)} WHERE id=?", params)
            _emit_event(conn, "skill_updated", payload={"skill_id": skill_id})
            _record_user_activity(
                conn,
                user=user,
                action="skill.update",
                target_type="skill",
                target_id=skill_id,
                metadata={"changes": changed_fields},
            )

    return {"ok": True}


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "Skill not found")
        conn.execute("DELETE FROM workflow_skill_bindings WHERE skill_id=?", (skill_id,))
        conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        _emit_event(conn, "skill_deleted", payload={"skill_id": skill_id})
        _record_user_activity(
            conn,
            user=user,
            action="skill.delete",
            target_type="skill",
            target_id=skill_id,
            metadata={"name": skill["name"]},
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Workflow Definitions
# ---------------------------------------------------------------------------

@router.get("/templates/{template_id}/definition")
def get_definition(template_id: str):
    with get_db() as conn:
        tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")

        defn = row_to_dict(conn.execute(
            "SELECT * FROM workflow_definitions WHERE template_id=?", (template_id,)
        ).fetchone())

    return defn or {"id": None, "template_id": template_id, "content": "", "created_at": None, "updated_at": None}


@router.put("/templates/{template_id}/definition")
def upsert_definition(template_id: str, body: UpdateDefinitionBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")

        now = _now()
        existing = conn.execute("SELECT * FROM workflow_definitions WHERE template_id=?", (template_id,)).fetchone()

        if existing:
            conn.execute(
                "UPDATE workflow_definitions SET content=?, updated_at=? WHERE template_id=?",
                (body.content, now, template_id),
            )
        else:
            def_id = _uuid("wdef_")
            conn.execute(
                "INSERT INTO workflow_definitions (id, template_id, content, created_at, updated_at) VALUES (?,?,?,?,?)",
                (def_id, template_id, body.content, now, now),
            )

        _emit_event(conn, "definition_updated", payload={"template_id": template_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.definition_upsert",
            target_type="workflow_definition",
            target_id=template_id,
            metadata={"template_id": template_id, "content_length": len(body.content)},
        )

    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Skill Bindings
# ---------------------------------------------------------------------------

@router.get("/templates/{template_id}/skills")
def list_skill_bindings(template_id: str):
    with get_db() as conn:
        bindings = rows_to_list(conn.execute(
            """SELECT wsb.*, s.name as skill_name, s.description as skill_description
               FROM workflow_skill_bindings wsb
               JOIN skills s ON wsb.skill_id = s.id
               WHERE wsb.template_id=?
               ORDER BY wsb.execution_order""",
            (template_id,),
        ).fetchall())
    return bindings


@router.post("/templates/{template_id}/skills")
def create_skill_binding(template_id: str, body: CreateSkillBindingBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        tmpl = conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")
        skill = conn.execute("SELECT * FROM skills WHERE id=?", (body.skill_id,)).fetchone()
        if not skill:
            raise HTTPException(404, "Skill not found")

        try:
            cur = conn.execute(
                "INSERT INTO workflow_skill_bindings (template_id, skill_id, stage_id, execution_order) VALUES (?,?,?,?)",
                (template_id, body.skill_id, body.stage_id, body.execution_order),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Binding already exists")

        _emit_event(conn, "binding_created", payload={"template_id": template_id, "skill_id": body.skill_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.skill_binding_create",
            target_type="workflow_skill_binding",
            target_id=str(cur.lastrowid),
            metadata={"template_id": template_id, "skill_id": body.skill_id, "stage_id": body.stage_id},
        )

    return {"id": cur.lastrowid}


@router.delete("/templates/{template_id}/skills/{binding_id}")
def delete_skill_binding(template_id: str, binding_id: int, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        binding = conn.execute(
            "SELECT * FROM workflow_skill_bindings WHERE id=? AND template_id=?", (binding_id, template_id)
        ).fetchone()
        if not binding:
            raise HTTPException(404, "Binding not found")
        conn.execute("DELETE FROM workflow_skill_bindings WHERE id=?", (binding_id,))
        _emit_event(conn, "binding_deleted", payload={"template_id": template_id, "binding_id": binding_id})
        _record_user_activity(
            conn,
            user=user,
            action="template.skill_binding_delete",
            target_type="workflow_skill_binding",
            target_id=str(binding_id),
            metadata={"template_id": template_id, "skill_id": binding["skill_id"], "stage_id": binding["stage_id"]},
        )
    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Stage HITL Settings
# ---------------------------------------------------------------------------

@router.patch("/stages/{stage_id}")
def update_stage(stage_id: str, body: UpdateStageBody, request: Request):
    with get_db() as conn:
        user = _require_authenticated_user(conn, request)
        stage = conn.execute("SELECT * FROM stage_definitions WHERE id=?", (stage_id,)).fetchone()
        if not stage:
            raise HTTPException(404, "Stage not found")

        updates = []
        params = []
        changed_fields: dict[str, Any] = {}
        if body.transition_mode is not None:
            if body.transition_mode not in ("auto", "approval_required"):
                raise HTTPException(400, "transition_mode must be 'auto' or 'approval_required'")
            updates.append("transition_mode=?")
            params.append(body.transition_mode)
            changed_fields["transition_mode"] = body.transition_mode
        if body.approval_roles is not None:
            updates.append("approval_roles=?")
            params.append(body.approval_roles)
            changed_fields["approval_roles"] = body.approval_roles

        if updates:
            params.append(stage_id)
            conn.execute(f"UPDATE stage_definitions SET {','.join(updates)} WHERE id=?", params)
            _emit_event(conn, "stage_updated", payload={"stage_id": stage_id})
            _record_user_activity(
                conn,
                user=user,
                action="stage.update",
                target_type="stage",
                target_id=stage_id,
                metadata={"changes": changed_fields},
            )

    return {"ok": True}


# ---------------------------------------------------------------------------
# API: Approval System
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# API: Events (polling)
# ---------------------------------------------------------------------------

@router.get("/events")
def get_events(since: int = Query(0), limit: int = Query(200)):
    with get_db() as conn:
        events = rows_to_list(
            conn.execute(
                "SELECT * FROM ax_events WHERE id > ? ORDER BY id LIMIT ?", (since, limit)
            ).fetchall()
        )
        cursor = events[-1]["id"] if events else since

    return {"events": events, "cursor": cursor}
