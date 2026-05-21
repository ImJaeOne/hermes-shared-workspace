"""Catalog routes for agents, templates, and boards."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

try:
    from .activity import _record_user_activity
    from .auth_sessions import _require_authenticated_user
    from .common import _now, _uuid
    from .db import get_db
    from .events import _emit_event
    from .rows import row_to_dict, rows_to_list
    from .schemas import CreateTemplateBody
except ImportError:
    from activity import _record_user_activity
    from auth_sessions import _require_authenticated_user
    from common import _now, _uuid
    from db import get_db
    from events import _emit_event
    from rows import row_to_dict, rows_to_list
    from schemas import CreateTemplateBody

router = APIRouter()


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
