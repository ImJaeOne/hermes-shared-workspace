"""Workflow definition routes extracted from plugin_api."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

try:
    from .activity import _record_user_activity
    from .auth_sessions import _require_authenticated_user
    from .common import _now, _uuid
    from .db import get_db
    from .events import _emit_event
    from .rows import row_to_dict
    from .schemas import UpdateDefinitionBody
except ImportError:
    from activity import _record_user_activity
    from auth_sessions import _require_authenticated_user
    from common import _now, _uuid
    from db import get_db
    from events import _emit_event
    from rows import row_to_dict
    from schemas import UpdateDefinitionBody

router = APIRouter()


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
