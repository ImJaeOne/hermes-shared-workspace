"""Hermes AX Plugin — MCP Server (stdio).

Exposes AX Dashboard database operations as MCP tools for Hermes agents.
Uses FastMCP SDK over stdio transport.
"""

from __future__ import annotations

import json
import sys
import os

# Allow importing plugin_api from the dashboard subpackage
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dashboard"))

from mcp.server.fastmcp import FastMCP
from plugin_api import get_db, init_db, rows_to_list, row_to_dict, _now, _uuid, _emit_event

mcp = FastMCP("hermes-ax")


# ---------------------------------------------------------------------------
# Tool: ax_list_workflows
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_list_workflows(agent_id: str, template_id: str = "") -> dict:
    """에이전트의 워크플로우 목록을 조회합니다.

    Args:
        agent_id: 에이전트 타입 ID (sales, marketing, support)
        template_id: 특정 템플릿으로 필터링 (선택사항)
    """
    init_db()
    with get_db() as conn:
        agent = row_to_dict(conn.execute("SELECT * FROM agent_types WHERE id=?", (agent_id,)).fetchone())
        if not agent:
            return {"error": f"Agent '{agent_id}' not found"}

        if template_id:
            tmpl = conn.execute(
                "SELECT * FROM workflow_templates WHERE id=? AND agent_type_id=? AND is_active=1",
                (template_id, agent_id),
            ).fetchone()
        else:
            tmpl = conn.execute(
                "SELECT * FROM workflow_templates WHERE agent_type_id=? AND is_active=1 ORDER BY created_at LIMIT 1",
                (agent_id,),
            ).fetchone()

        if not tmpl:
            return {"agent_id": agent_id, "template_id": None, "workflows": []}

        stages = rows_to_list(conn.execute(
            "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order",
            (tmpl["id"],),
        ).fetchall())

        workflows = rows_to_list(conn.execute(
            """SELECT wi.*, sd.name as current_stage_name, sd.stage_order as current_stage_order,
                      (SELECT count(*) FROM artifacts WHERE workflow_id=wi.id) as artifact_count
               FROM workflow_instances wi
               JOIN stage_definitions sd ON wi.current_stage_id = sd.id
               WHERE wi.template_id=? AND wi.status IN ('active','pending_approval')
               ORDER BY wi.priority DESC, wi.updated_at DESC""",
            (tmpl["id"],),
        ).fetchall())

        completed = rows_to_list(conn.execute(
            """SELECT wi.*, sd.name as current_stage_name
               FROM workflow_instances wi
               JOIN stage_definitions sd ON wi.current_stage_id = sd.id
               WHERE wi.template_id=? AND wi.status IN ('completed','failed','cancelled')
               ORDER BY wi.updated_at DESC LIMIT 10""",
            (tmpl["id"],),
        ).fetchall())

    return {
        "agent_id": agent_id,
        "template_id": tmpl["id"],
        "template_name": tmpl["name"],
        "stages": stages,
        "active_workflows": workflows,
        "completed_workflows": completed,
    }


# ---------------------------------------------------------------------------
# Tool: ax_get_workflow
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_get_workflow(workflow_id: str) -> dict:
    """워크플로우 상세 정보를 조회합니다 (단계, 산출물, 코멘트 포함).

    Args:
        workflow_id: 워크플로우 인스턴스 ID
    """
    init_db()
    with get_db() as conn:
        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone())
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}

        all_stages = rows_to_list(conn.execute(
            "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order",
            (wf["template_id"],),
        ).fetchall())

        current_order = 0
        for s in all_stages:
            if s["id"] == wf["current_stage_id"]:
                current_order = s["stage_order"]
                break

        for s in all_stages:
            s["is_completed"] = s["stage_order"] < current_order
            s["is_current"] = s["id"] == wf["current_stage_id"]

        artifacts = rows_to_list(conn.execute(
            "SELECT * FROM artifacts WHERE workflow_id=? ORDER BY created_at",
            (workflow_id,),
        ).fetchall())

        for art in artifacts:
            art["comments"] = rows_to_list(conn.execute(
                "SELECT * FROM comments WHERE artifact_id=? ORDER BY created_at",
                (art["id"],),
            ).fetchall())

        transitions = rows_to_list(conn.execute(
            "SELECT * FROM stage_transitions WHERE workflow_id=? ORDER BY created_at",
            (workflow_id,),
        ).fetchall())

        pending_approval = row_to_dict(conn.execute(
            "SELECT * FROM approval_requests WHERE workflow_id=? AND status='pending' LIMIT 1",
            (workflow_id,),
        ).fetchone())

        wf["stages"] = all_stages
        wf["artifacts"] = artifacts
        wf["transitions"] = transitions
        wf["pending_approval"] = pending_approval

    return wf


# ---------------------------------------------------------------------------
# Tool: ax_create_workflow
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_create_workflow(template_id: str, title: str, priority: int = 0, assignee: str = "") -> dict:
    """새 워크플로우(티켓)를 생성합니다.

    Args:
        template_id: 워크플로우 템플릿 ID (예: sales_pipeline_v1, mktg_blog)
        title: 워크플로우 제목
        priority: 우선순위 (0=보통, 1=높음, 2=긴급)
        assignee: 담당자 이름
    """
    init_db()
    with get_db() as conn:
        tmpl = row_to_dict(conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone())
        if not tmpl:
            return {"error": f"Template '{template_id}' not found"}

        first_stage = conn.execute(
            "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order LIMIT 1",
            (template_id,),
        ).fetchone()
        if not first_stage:
            return {"error": "Template has no stages"}

        now = _now()
        wf_id = _uuid("wi_")
        conn.execute(
            """INSERT INTO workflow_instances
               (id, template_id, agent_type_id, title, current_stage_id, status, priority, assignee, metadata_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (wf_id, template_id, tmpl["agent_type_id"], title, first_stage["id"], "active", priority, assignee, "{}", now, now),
        )
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at) VALUES (?,?,?,?,?,?)",
            (wf_id, None, first_stage["id"], "agent", "워크플로우 생성 (에이전트)", now),
        )
        _emit_event(conn, "workflow_created", wf_id)

    return {"id": wf_id, "status": "active", "current_stage_id": first_stage["id"]}


# ---------------------------------------------------------------------------
# Tool: ax_transition_stage
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_transition_stage(workflow_id: str, to_stage_id: str, note: str = "") -> dict:
    """워크플로우를 다음 단계로 전환합니다.

    승인이 필요한 단계(transition_mode=approval_required)인 경우 승인 요청이 생성됩니다.

    Args:
        workflow_id: 워크플로우 ID
        to_stage_id: 전환 대상 단계 ID
        note: 전환 사유/메모
    """
    init_db()
    with get_db() as conn:
        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone())
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}

        target = row_to_dict(conn.execute("SELECT * FROM stage_definitions WHERE id=?", (to_stage_id,)).fetchone())
        if not target:
            return {"error": f"Stage '{to_stage_id}' not found"}

        now = _now()

        if target["transition_mode"] == "approval_required":
            apr_id = _uuid("apr_")
            conn.execute(
                "INSERT INTO approval_requests (id, workflow_id, stage_id, status, requested_at, decided_by, note) VALUES (?,?,?,?,?,?,?)",
                (apr_id, workflow_id, to_stage_id, "pending", now, "", note),
            )
            conn.execute(
                "UPDATE workflow_instances SET status='pending_approval', updated_at=? WHERE id=?",
                (now, workflow_id),
            )
            _emit_event(conn, "approval_requested", workflow_id, payload={"approval_id": apr_id, "target_stage": to_stage_id})
            return {"ok": True, "pending_approval": True, "approval_id": apr_id, "message": "승인 대기 중입니다."}

        conn.execute(
            "UPDATE workflow_instances SET current_stage_id=?, updated_at=? WHERE id=?",
            (to_stage_id, now, workflow_id),
        )
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at) VALUES (?,?,?,?,?,?)",
            (workflow_id, wf["current_stage_id"], to_stage_id, "agent", note, now),
        )
        _emit_event(conn, "stage_changed", workflow_id, payload={"from": wf["current_stage_id"], "to": to_stage_id})

    return {"ok": True, "current_stage_id": to_stage_id}


# ---------------------------------------------------------------------------
# Tool: ax_create_artifact
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_create_artifact(
    workflow_id: str,
    stage_id: str,
    artifact_type: str,
    title: str,
    content: str,
    content_type: str = "text/markdown",
    status: str = "draft",
) -> dict:
    """워크플로우 단계에 산출물을 생성합니다.

    Args:
        workflow_id: 워크플로우 ID
        stage_id: 단계 ID
        artifact_type: 산출물 유형 (contact_info, email, meeting_notes, proposal, contract, report, brief, content_draft, ticket, log, resolution_note)
        title: 산출물 제목
        content: 산출물 내용 (마크다운 또는 JSON)
        content_type: MIME 타입 (text/markdown, application/json, text/plain)
        status: 상태 (draft, final, archived)
    """
    init_db()
    with get_db() as conn:
        wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}

        now = _now()
        art_id = _uuid("art_")
        conn.execute(
            """INSERT INTO artifacts
               (id, workflow_id, stage_id, artifact_type, title, content, content_type, status, file_path, file_size, mime_type, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (art_id, workflow_id, stage_id, artifact_type, title, content, content_type, status, "", 0, content_type, now, now),
        )
        _emit_event(conn, "artifact_added", workflow_id, art_id)

    return {"id": art_id}


# ---------------------------------------------------------------------------
# Tool: ax_update_artifact
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_update_artifact(
    artifact_id: str,
    title: str = "",
    content: str = "",
    content_type: str = "",
    status: str = "",
) -> dict:
    """산출물을 수정합니다.

    Args:
        artifact_id: 산출물 ID
        title: 새 제목 (변경 시)
        content: 새 내용 (변경 시)
        content_type: 새 MIME 타입 (변경 시)
        status: 새 상태 (변경 시: draft, final, archived)
    """
    init_db()
    with get_db() as conn:
        art = row_to_dict(conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone())
        if not art:
            return {"error": f"Artifact '{artifact_id}' not found"}

        updates = []
        params = []
        if title:
            updates.append("title=?")
            params.append(title)
        if content:
            updates.append("content=?")
            params.append(content)
        if content_type:
            updates.append("content_type=?")
            params.append(content_type)
        if status:
            updates.append("status=?")
            params.append(status)

        if not updates:
            return {"ok": True, "message": "변경사항 없음"}

        updates.append("updated_at=?")
        params.append(_now())
        params.append(artifact_id)
        conn.execute(f"UPDATE artifacts SET {','.join(updates)} WHERE id=?", params)
        _emit_event(conn, "artifact_updated", art["workflow_id"], artifact_id)

    return {"ok": True}


# ---------------------------------------------------------------------------
# Tool: ax_get_artifact
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_get_artifact(artifact_id: str) -> dict:
    """산출물 상세 정보를 조회합니다 (코멘트 포함).

    Args:
        artifact_id: 산출물 ID
    """
    init_db()
    with get_db() as conn:
        art = row_to_dict(conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone())
        if not art:
            return {"error": f"Artifact '{artifact_id}' not found"}
        art["comments"] = rows_to_list(
            conn.execute("SELECT * FROM comments WHERE artifact_id=? ORDER BY created_at", (artifact_id,)).fetchall()
        )
    return art


# ---------------------------------------------------------------------------
# Tool: ax_add_comment
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_add_comment(artifact_id: str, author: str, body: str) -> dict:
    """산출물에 코멘트를 추가합니다.

    Args:
        artifact_id: 산출물 ID
        author: 작성자 이름
        body: 코멘트 내용
    """
    init_db()
    with get_db() as conn:
        art = conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
        if not art:
            return {"error": f"Artifact '{artifact_id}' not found"}

        now = _now()
        cur = conn.execute(
            "INSERT INTO comments (artifact_id, author, body, created_at, updated_at) VALUES (?,?,?,?,?)",
            (artifact_id, author, body, now, now),
        )
        _emit_event(conn, "comment_added", art["workflow_id"], artifact_id, {"comment_id": cur.lastrowid})

    return {"id": cur.lastrowid}


# ---------------------------------------------------------------------------
# Tool: ax_list_approvals
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_list_approvals(status: str = "pending", workflow_id: str = "") -> dict:
    """승인 요청 목록을 조회합니다.

    Args:
        status: 필터 상태 (pending, approved, rejected). 기본값: pending
        workflow_id: 특정 워크플로우로 필터링 (선택사항)
    """
    init_db()
    with get_db() as conn:
        query = """
            SELECT ar.*, wi.title as workflow_title, sd.name as stage_name,
                   wi.agent_type_id, wi.template_id
            FROM approval_requests ar
            JOIN workflow_instances wi ON ar.workflow_id = wi.id
            JOIN stage_definitions sd ON ar.stage_id = sd.id
        """
        conditions = []
        params: list = []

        if workflow_id:
            conditions.append("ar.workflow_id=?")
            params.append(workflow_id)
        if status:
            conditions.append("ar.status=?")
            params.append(status)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY ar.requested_at DESC"

        approvals = rows_to_list(conn.execute(query, params).fetchall())

    return {"approvals": approvals, "count": len(approvals)}


# ---------------------------------------------------------------------------
# Tool: ax_decide_approval
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_decide_approval(approval_id: str, decision: str, decided_by: str, note: str = "") -> dict:
    """승인 요청을 승인하거나 거절합니다.

    Args:
        approval_id: 승인 요청 ID
        decision: 결정 (approved 또는 rejected)
        decided_by: 결정자 이름
        note: 결정 사유
    """
    if decision not in ("approved", "rejected"):
        return {"error": "decision must be 'approved' or 'rejected'"}

    init_db()
    with get_db() as conn:
        apr = row_to_dict(conn.execute("SELECT * FROM approval_requests WHERE id=?", (approval_id,)).fetchone())
        if not apr:
            return {"error": f"Approval '{approval_id}' not found"}
        if apr["status"] != "pending":
            return {"error": "Approval already decided"}

        now = _now()
        conn.execute(
            "UPDATE approval_requests SET status=?, decided_by=?, decided_at=?, note=? WHERE id=?",
            (decision, decided_by, now, note, approval_id),
        )

        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (apr["workflow_id"],)).fetchone())

        if decision == "approved":
            conn.execute(
                "UPDATE workflow_instances SET current_stage_id=?, status='active', updated_at=? WHERE id=?",
                (apr["stage_id"], now, apr["workflow_id"]),
            )
            conn.execute(
                "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at) VALUES (?,?,?,?,?,?)",
                (apr["workflow_id"], wf["current_stage_id"], apr["stage_id"], decided_by, f"승인: {note}" if note else "승인됨", now),
            )
            _emit_event(conn, "approval_approved", apr["workflow_id"], payload={"approval_id": approval_id})
            _emit_event(conn, "stage_changed", apr["workflow_id"], payload={
                "from": wf["current_stage_id"],
                "to": apr["stage_id"],
                "trigger_next": True,
            })
        else:
            conn.execute(
                "UPDATE workflow_instances SET status='active', updated_at=? WHERE id=?",
                (now, apr["workflow_id"]),
            )
            _emit_event(conn, "approval_rejected", apr["workflow_id"], payload={"approval_id": approval_id})

    return {"ok": True, "status": decision, "workflow_id": apr["workflow_id"]}


# ---------------------------------------------------------------------------
# Tool: ax_get_playbook
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_get_playbook(template_id: str) -> dict:
    """워크플로우 템플릿의 플레이북(정의서)을 조회합니다.

    플레이북은 해당 워크플로우 유형의 실행 가이드, 단계별 체크리스트,
    주의사항 등을 담은 마크다운 문서입니다.

    Args:
        template_id: 워크플로우 템플릿 ID (예: sales_pipeline_v1, mktg_blog)
    """
    init_db()
    with get_db() as conn:
        tmpl = row_to_dict(conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone())
        if not tmpl:
            return {"error": f"Template '{template_id}' not found"}

        defn = row_to_dict(conn.execute(
            "SELECT * FROM workflow_definitions WHERE template_id=?", (template_id,)
        ).fetchone())

        stages = rows_to_list(conn.execute(
            "SELECT id, name, slug, stage_order, expected_artifacts, transition_mode FROM stage_definitions WHERE template_id=? ORDER BY stage_order",
            (template_id,),
        ).fetchall())

    if defn:
        return {
            "template_id": template_id,
            "template_name": tmpl["name"],
            "stages": stages,
            "playbook": defn,
        }

    return {
        "template_id": template_id,
        "template_name": tmpl["name"],
        "stages": stages,
        "playbook": None,
        "message": "플레이북이 아직 없습니다. ax_save_playbook으로 생성하세요.",
    }


# ---------------------------------------------------------------------------
# Tool: ax_save_playbook
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_save_playbook(template_id: str, content: str) -> dict:
    """워크플로우 템플릿의 플레이북(정의서)을 생성하거나 업데이트합니다.

    마크다운 형식으로 작성하며, 기존 플레이북이 있으면 덮어씁니다.

    Args:
        template_id: 워크플로우 템플릿 ID
        content: 플레이북 마크다운 내용
    """
    init_db()
    with get_db() as conn:
        tmpl = row_to_dict(conn.execute("SELECT * FROM workflow_templates WHERE id=?", (template_id,)).fetchone())
        if not tmpl:
            return {"error": f"Template '{template_id}' not found"}

        now = _now()
        existing = conn.execute("SELECT * FROM workflow_definitions WHERE template_id=?", (template_id,)).fetchone()

        if existing:
            conn.execute(
                "UPDATE workflow_definitions SET content=?, updated_at=? WHERE template_id=?",
                (content, now, template_id),
            )
            _emit_event(conn, "definition_updated", payload={"template_id": template_id})
            return {"ok": True, "action": "updated", "template_id": template_id}
        else:
            def_id = _uuid("wdef_")
            conn.execute(
                "INSERT INTO workflow_definitions (id, template_id, content, created_at, updated_at) VALUES (?,?,?,?,?)",
                (def_id, template_id, content, now, now),
            )
            _emit_event(conn, "definition_updated", payload={"template_id": template_id})
            return {"ok": True, "action": "created", "id": def_id, "template_id": template_id}


# ---------------------------------------------------------------------------
# Tool: ax_get_stats
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_get_stats() -> dict:
    """AX 대시보드 전체 통계를 조회합니다."""
    init_db()
    with get_db() as conn:
        active = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='active'").fetchone()["c"]
        completed = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='completed'").fetchone()["c"]
        failed = conn.execute("SELECT count(*) as c FROM workflow_instances WHERE status='failed'").fetchone()["c"]
        pending_approvals = conn.execute("SELECT count(*) as c FROM approval_requests WHERE status='pending'").fetchone()["c"]

        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        artifacts_today = conn.execute(
            "SELECT count(*) as c FROM artifacts WHERE created_at >= ?", (today,)
        ).fetchone()["c"]

        by_agent: dict = {}
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
# Tool: ax_poll_events
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_poll_events(since: int = 0, limit: int = 50) -> dict:
    """마지막 커서 이후 새로운 AX 이벤트를 조회합니다.

    폴링 방식으로 새 이벤트(승인, 단계 변경 등)를 감지할 때 사용합니다.

    Args:
        since: 마지막으로 확인한 이벤트 ID (커서). 0이면 처음부터.
        limit: 최대 반환 이벤트 수
    """
    init_db()
    with get_db() as conn:
        events = rows_to_list(conn.execute(
            "SELECT * FROM ax_events WHERE id > ? ORDER BY id LIMIT ?",
            (since, limit),
        ).fetchall())

        for ev in events:
            if ev.get("payload"):
                try:
                    ev["payload"] = json.loads(ev["payload"])
                except (json.JSONDecodeError, TypeError):
                    pass

        cursor = events[-1]["id"] if events else since

    return {"events": events, "cursor": cursor, "count": len(events)}


# ---------------------------------------------------------------------------
# Tool: ax_create_kanban_task
# ---------------------------------------------------------------------------

@mcp.tool()
def ax_create_kanban_task(
    workflow_id: str,
    stage_id: str,
    title: str = "",
    body: str = "",
    priority: int = 10,
) -> dict:
    """워크플로우 단계에 대한 Hermes Kanban 태스크를 생성합니다.

    에이전트가 다음 단계 작업을 자동으로 수행하도록 Kanban 보드에 태스크를 등록합니다.

    Args:
        workflow_id: 워크플로우 ID
        stage_id: 대상 단계 ID
        title: 태스크 제목 (비워두면 자동 생성)
        body: 태스크 본문 (작업 지시)
        priority: 우선순위 (기본 10)
    """
    init_db()
    with get_db() as conn:
        wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone())
        if not wf:
            return {"error": f"Workflow '{workflow_id}' not found"}

        stage = row_to_dict(conn.execute("SELECT * FROM stage_definitions WHERE id=?", (stage_id,)).fetchone())
        if not stage:
            return {"error": f"Stage '{stage_id}' not found"}

        if not title:
            title = f"[AX] {wf['title']} — {stage['name']}"

        if not body:
            body = (
                f"워크플로우 '{wf['title']}'의 '{stage['name']}' 단계 작업을 수행하세요.\n\n"
                f"- workflow_id: {workflow_id}\n"
                f"- stage_id: {stage_id}\n"
                f"- expected_artifacts: {stage.get('expected_artifacts', '[]')}\n\n"
                f"ax-workflow 스킬을 참고하여 이 단계에 필요한 산출물을 생성하고, "
                f"완료 후 다음 단계로 전환하세요."
            )

    # Try to create a Kanban task via hermes_cli
    try:
        from hermes_cli import kanban_db as kb
        with kb.connect() as kconn:
            task_id = kb.create_task(
                kconn,
                title=title,
                body=body,
                skills=["ax-workflow"],
                priority=priority,
            )
        return {"ok": True, "kanban_task_id": task_id, "title": title}
    except ImportError:
        # hermes_cli not available — return task spec for manual creation
        return {
            "ok": False,
            "message": "hermes_cli not available. Task spec returned for manual creation.",
            "task_spec": {
                "title": title,
                "body": body,
                "skills": ["ax-workflow"],
                "priority": priority,
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "task_spec": {"title": title, "body": body}}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    mcp.run(transport="stdio")
