"""Skill and workflow skill binding routes extracted from plugin_api."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

try:
    from .activity import _record_user_activity
    from .auth_sessions import _require_authenticated_user
    from .common import _now, _uuid
    from .db import get_db
    from .events import _emit_event
    from .rows import row_to_dict, rows_to_list
    from .schemas import CreateSkillBindingBody, CreateSkillBody, UpdateSkillBody
except ImportError:
    from activity import _record_user_activity
    from auth_sessions import _require_authenticated_user
    from common import _now, _uuid
    from db import get_db
    from events import _emit_event
    from rows import row_to_dict, rows_to_list
    from schemas import CreateSkillBindingBody, CreateSkillBody, UpdateSkillBody

router = APIRouter()


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
