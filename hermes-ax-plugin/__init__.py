"""Hermes AX Plugin — Agent hooks and auto-trigger logic.

Registers:
  - post_tool_call hook: detects ax_decide_approval calls → auto-creates next-stage Kanban tasks
  - /ax-trigger command: manual trigger for next workflow stage
"""

from __future__ import annotations

import json
import logging
import sys
import os

# Allow importing plugin_api
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dashboard"))

log = logging.getLogger("hermes-ax")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_next_stage(conn, workflow_id: str) -> dict | None:
    """Given a workflow, return the next stage definition (or None if at last stage)."""
    wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
    if not wf:
        return None

    stages = conn.execute(
        "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order",
        (wf["template_id"],),
    ).fetchall()

    current_order = None
    for s in stages:
        if s["id"] == wf["current_stage_id"]:
            current_order = s["stage_order"]
            break

    if current_order is None:
        return None

    for s in stages:
        if s["stage_order"] == current_order + 1:
            return dict(s)

    return None


def _build_worker_prompt(wf: dict, stage: dict) -> str:
    """Build a task body for the Kanban task assigned to this stage."""
    expected = stage.get("expected_artifacts", "[]")
    return (
        f"## AX 워크플로우 자동 태스크\n\n"
        f"**워크플로우**: {wf['title']}\n"
        f"**현재 단계**: {stage['name']} (`{stage['slug']}`)\n"
        f"**workflow_id**: `{wf['id']}`\n"
        f"**stage_id**: `{stage['id']}`\n\n"
        f"### 작업 지시\n"
        f"이 단계에서 요구되는 산출물을 생성하세요.\n\n"
        f"**필요 산출물**: {expected}\n\n"
        f"### 수행 절차\n"
        f"1. `ax_get_workflow`로 워크플로우 현황 확인\n"
        f"2. 이전 단계 산출물과 코멘트 검토\n"
        f"3. `ax_create_artifact`로 산출물 생성\n"
        f"4. 필요 시 `ax_add_comment`로 메모 추가\n"
        f"5. 모든 산출물 완료 후 `ax_transition_stage`로 다음 단계 전환\n\n"
        f"**스킬 참조**: ax-workflow\n"
    )


def _create_kanban_task_for_stage(workflow_id: str, stage: dict, wf: dict, priority: int = 10):
    """Create a Kanban task for the given workflow stage."""
    title = f"[AX] {wf['title']} — {stage['name']}"
    body = _build_worker_prompt(wf, stage)

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
        log.info(f"Kanban task created: {task_id} for {title}")
        return task_id
    except ImportError:
        log.warning("hermes_cli.kanban_db not available — cannot create Kanban task")
        return None
    except Exception as e:
        log.error(f"Failed to create Kanban task: {e}")
        return None


# ---------------------------------------------------------------------------
# Hook: post_tool_call
# ---------------------------------------------------------------------------

def _on_post_tool_call(ctx, tool_name: str, tool_args: dict, result: dict | str | None):
    """Called after any MCP tool call completes.

    Watches for:
    - ax_decide_approval with decision=approved → auto-create next-stage task
    - ax_transition_stage success → auto-create next-stage task (if auto mode)
    """
    if tool_name == "ax_decide_approval":
        # Check if approval was approved
        decision = tool_args.get("decision", "")
        if decision != "approved":
            return

        # Parse result
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return

        if not isinstance(result, dict) or not result.get("ok"):
            return

        workflow_id = result.get("workflow_id") or tool_args.get("workflow_id", "")
        if not workflow_id:
            # Try to get from approval
            approval_id = tool_args.get("approval_id", "")
            if not approval_id:
                return
            try:
                from plugin_api import get_db, init_db, row_to_dict
                init_db()
                with get_db() as conn:
                    apr = row_to_dict(conn.execute("SELECT * FROM approval_requests WHERE id=?", (approval_id,)).fetchone())
                    if apr:
                        workflow_id = apr["workflow_id"]
            except Exception:
                return

        if not workflow_id:
            return

        _dispatch_next_stage(workflow_id)

    elif tool_name == "ax_transition_stage":
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                return

        if not isinstance(result, dict) or not result.get("ok"):
            return

        # Don't auto-dispatch if pending approval
        if result.get("pending_approval"):
            return

        workflow_id = tool_args.get("workflow_id", "")
        if workflow_id:
            _dispatch_next_stage(workflow_id)


def _dispatch_next_stage(workflow_id: str):
    """Look at the workflow's current stage and create a Kanban task for it."""
    try:
        from plugin_api import get_db, init_db, row_to_dict
        init_db()
        with get_db() as conn:
            wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone())
            if not wf or wf["status"] not in ("active",):
                return

            # Get current stage info
            stage = row_to_dict(conn.execute("SELECT * FROM stage_definitions WHERE id=?", (wf["current_stage_id"],)).fetchone())
            if not stage:
                return

            # Determine priority from workflow
            priority_map = {0: 10, 1: 20, 2: 30}
            priority = priority_map.get(wf.get("priority", 0), 10)

            _create_kanban_task_for_stage(workflow_id, stage, wf, priority)

    except Exception as e:
        log.error(f"Error dispatching next stage for {workflow_id}: {e}")


# ---------------------------------------------------------------------------
# Command: /ax-trigger
# ---------------------------------------------------------------------------

def _handle_trigger(ctx, args: str = ""):
    """Manual trigger: create Kanban task for a workflow's current stage.

    Usage: /ax-trigger <workflow_id>
    """
    workflow_id = args.strip()
    if not workflow_id:
        return "사용법: /ax-trigger <workflow_id>"

    try:
        from plugin_api import get_db, init_db, row_to_dict
        init_db()
        with get_db() as conn:
            wf = row_to_dict(conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone())
            if not wf:
                return f"워크플로우 '{workflow_id}'를 찾을 수 없습니다."

            stage = row_to_dict(conn.execute("SELECT * FROM stage_definitions WHERE id=?", (wf["current_stage_id"],)).fetchone())
            if not stage:
                return "현재 단계를 찾을 수 없습니다."

            task_id = _create_kanban_task_for_stage(workflow_id, stage, wf)
            if task_id:
                return f"Kanban 태스크 생성 완료: {task_id}\n워크플로우: {wf['title']}\n단계: {stage['name']}"
            else:
                return "Kanban 태스크 생성에 실패했습니다. hermes_cli가 사용 가능한지 확인하세요."

    except Exception as e:
        return f"오류: {e}"


# ---------------------------------------------------------------------------
# Skill auto-install
# ---------------------------------------------------------------------------

def _install_bundled_skills():
    """Symlink bundled skills into ~/.hermes/skills/domain/ on plugin load."""
    from pathlib import Path

    plugin_skills_dir = Path(__file__).parent / "skills"
    target_base = Path.home() / ".hermes" / "skills"

    if not plugin_skills_dir.is_dir():
        return

    for skill_dir in plugin_skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        target = target_base / skill_dir.name
        if target.is_symlink():
            # Already linked — update if pointing elsewhere
            if target.resolve() != skill_dir.resolve():
                target.unlink()
                target.symlink_to(skill_dir)
                log.info(f"Skill symlink updated: {skill_dir.name}")
        elif target.exists():
            # Directory exists (not a symlink) — skip to avoid overwriting manual edits
            log.debug(f"Skill '{skill_dir.name}' already exists as directory, skipping")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(skill_dir)
            log.info(f"Skill installed: {skill_dir.name} -> {target}")


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def register(ctx):
    """Register hooks and commands with the Hermes plugin system."""
    _install_bundled_skills()
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_command(
        "ax-trigger",
        handler=_handle_trigger,
        description="AX 워크플로우 다음 단계 수동 트리거",
    )
    log.info("hermes-ax plugin registered (hooks: post_tool_call, commands: /ax-trigger)")
