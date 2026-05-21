"""Stage HITL settings routes extracted from plugin_api."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

try:
    from .activity import _record_user_activity
    from .auth_sessions import _require_authenticated_user
    from .db import get_db
    from .events import _emit_event
    from .schemas import UpdateStageBody
except ImportError:
    from activity import _record_user_activity
    from auth_sessions import _require_authenticated_user
    from db import get_db
    from events import _emit_event
    from schemas import UpdateStageBody

router = APIRouter()


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
