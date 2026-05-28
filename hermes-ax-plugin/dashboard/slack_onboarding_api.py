"""Slack channel onboarding routes for the AX planning MVP."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException, Request

try:
    from .activity import _record_activity
    from .artifact_storage import get_artifact_storage
    from .auth_sessions import _require_authenticated_user
    from .common import _now, _uuid
    from .db import get_db
    from .events import _emit_event
    from .rows import row_to_dict
except ImportError:
    from activity import _record_activity
    from artifact_storage import get_artifact_storage
    from auth_sessions import _require_authenticated_user
    from common import _now, _uuid
    from db import get_db
    from events import _emit_event
    from rows import row_to_dict

router = APIRouter()

PLANNING_TEMPLATE_ID = "planning_research_mvp_v1"
PLANNING_ASSIGNEE = "기획팀 임팀장"
PLANNING_WORKER_ASSIGNEE = "기획팀 임사원"
STAGE_MATERIAL_WAITING = "p_material_waiting"
STAGE_RESEARCH_RUNNING = "p_research_running"
STAGE_USER_REVIEW_WAITING = "p_user_review_waiting"
STAGE_REVISION_RUNNING = "p_revision_running"
STAGE_RESEARCH_CONFIRMED = "p_research_confirmed"
SLACK_DEFAULT_MAX_FILES_PER_MESSAGE = 10
SLACK_DEFAULT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
SUPPORTED_CHANNEL_EVENTS = {"channel_created", "channel_joined", "channel_rename", "member_joined_channel"}
SUPPORTED_SLACK_FILE_EXTENSIONS = {"pdf", "txt", "md", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "csv", "png", "jpg", "jpeg"}
SUPPORTED_SLACK_FILE_MIMES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpeg",
}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _normalize_research_engine(value: str | None, default: str = "mock") -> str:
    engine = (value or default or "mock").strip().lower().replace("-", "_")
    return engine or default


def _research_engine_name() -> str:
    return _normalize_research_engine(os.getenv("HERMES_AX_RESEARCH_ENGINE"), "mock")


def _research_fallback_engine_name() -> str:
    return _normalize_research_engine(os.getenv("HERMES_AX_RESEARCH_FALLBACK_ENGINE"), "mock")


def _research_prompt_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    skill_id = (os.getenv("HERMES_AX_RESEARCH_SKILL_ID") or "skill_001").strip() or "skill_001"
    row = conn.execute("SELECT id, name, updated_at FROM skills WHERE id=?", (skill_id,)).fetchone()
    if not row:
        return {"source": "skills", "skill_id": skill_id, "name": "", "version": ""}
    return {"source": "skills", "skill_id": row["id"], "name": row["name"], "version": row["updated_at"]}


def _slack_max_files_per_message() -> int:
    return _env_int("HERMES_AX_SLACK_MAX_FILES_PER_MESSAGE", SLACK_DEFAULT_MAX_FILES_PER_MESSAGE)


def _slack_max_file_size_bytes() -> int:
    return _env_int("HERMES_AX_SLACK_MAX_FILE_SIZE_BYTES", SLACK_DEFAULT_MAX_FILE_SIZE_BYTES)


def _format_file_size_limit(size_bytes: int) -> str:
    if size_bytes % (1024 * 1024) == 0:
        return f"{size_bytes // (1024 * 1024)}MB"
    return f"{size_bytes} bytes"


def _slack_material_upload_guide() -> str:
    return (
        "지원 형식: pdf, txt/md, doc/docx, ppt/pptx, xls/xlsx, csv, png/jpg/jpeg · "
        f"한 번에 최대 {_slack_max_files_per_message()}개 · "
        f"파일당 최대 {_format_file_size_limit(_slack_max_file_size_bytes())}"
    )


def _slack_signing_secret() -> str:
    return (os.getenv("HERMES_AX_SLACK_SIGNING_SECRET") or os.getenv("SLACK_SIGNING_SECRET") or "").strip()


def _slack_bot_token() -> str:
    return (os.getenv("HERMES_AX_SLACK_BOT_TOKEN") or os.getenv("SLACK_BOT_TOKEN") or "").strip()


def _slack_bot_user_id() -> str:
    return (os.getenv("HERMES_AX_SLACK_BOT_USER_ID") or os.getenv("SLACK_BOT_USER_ID") or "").strip()


def _message_template() -> str:
    return os.getenv(
        "HERMES_AX_SLACK_ONBOARDING_MESSAGE_TEMPLATE",
        "{company_name}에 대한 기획 작업을 시작하겠습니다. 기획하기 앞서 {company_name}에 대한 자료가 있으시면 첨부해주세요.",
    )


def _verify_slack_signature(headers: dict[str, str], body: bytes):
    secret = _slack_signing_secret()
    if not secret:
        if _env_bool("HERMES_AX_SLACK_ALLOW_UNSIGNED_EVENTS"):
            return
        raise HTTPException(401, "Slack signing secret is not configured")

    timestamp = headers.get("x-slack-request-timestamp") or headers.get("X-Slack-Request-Timestamp") or ""
    signature = headers.get("x-slack-signature") or headers.get("X-Slack-Signature") or ""
    if not timestamp or not signature:
        raise HTTPException(401, "Missing Slack signature headers")

    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(401, "Invalid Slack request timestamp")
    if abs(int(time.time()) - ts) > 60 * 5:
        raise HTTPException(401, "Stale Slack request timestamp")

    base = b"v0:" + timestamp.encode("ascii") + b":" + body
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid Slack signature")


def _parse_json_body(body: bytes) -> dict[str, Any]:
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON payload")


def _normalize_channel_name(channel_name: str) -> str:
    cleaned = channel_name.strip().lstrip("#").lower().replace("_", "-")
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned)
    return cleaned.strip("-")


def _extract_company_name(channel_name: str) -> str:
    cleaned = channel_name.strip().lstrip("#").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise HTTPException(400, "Slack channel name is required")
    return cleaned


def _extract_event_channel(event: dict[str, Any]) -> tuple[str, str]:
    channel = event.get("channel")
    channel_id = ""
    channel_name = ""
    if isinstance(channel, dict):
        channel_id = str(channel.get("id") or "").strip()
        channel_name = str(channel.get("name") or "").strip()
    else:
        channel_id = str(channel or event.get("channel_id") or "").strip()
        channel_name = str(event.get("channel_name") or event.get("name") or "").strip()
    return channel_id, channel_name.lstrip("#")


def _fetch_slack_channel_name(channel_id: str) -> str:
    if _env_bool("HERMES_AX_SLACK_DRY_RUN"):
        return ""
    token = _slack_bot_token()
    if not token:
        return ""
    query = urllib.parse.urlencode({"channel": channel_id})
    req = urllib.request.Request(
        f"https://slack.com/api/conversations.info?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    timeout = float(os.getenv("HERMES_AX_SLACK_API_TIMEOUT_SECONDS", "2"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return ""
    if not payload.get("ok"):
        return ""
    channel = payload.get("channel") or {}
    return str(channel.get("name") or "").strip().lstrip("#")


def _call_slack_api(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = _slack_bot_token()
    if not token:
        return {"ok": False, "reason": "missing_bot_token"}

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    timeout = float(os.getenv("HERMES_AX_SLACK_API_TIMEOUT_SECONDS", "2"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": "slack_api_error", "error": str(exc)}

    if not data.get("ok"):
        return {"ok": False, "reason": "slack_api_rejected", "error": str(data.get("error") or "unknown_error"), "data": data}
    return {"ok": True, "data": data}


def _join_slack_channel(channel_id: str) -> dict[str, Any]:
    if _env_bool("HERMES_AX_SLACK_DRY_RUN"):
        return {"joined": True, "dry_run": True}
    result = _call_slack_api("conversations.join", {"channel": channel_id})
    if result.get("ok"):
        return {"joined": True, "channel": (result.get("data") or {}).get("channel") or {}}
    if result.get("error") == "already_in_channel":
        return {"joined": True, "already_in_channel": True}
    return {
        "joined": False,
        "reason": result.get("reason") or "slack_join_failed",
        "error": result.get("error") or result.get("reason") or "slack_join_failed",
    }


def _onboarding_message(company_name: str) -> str:
    return _message_template().format(company_name=company_name)


def _record_slack_activity(
    conn: sqlite3.Connection,
    *,
    action: str,
    workflow_id: str | None = None,
    target_id: str | None = None,
    artifact_id: str | None = None,
    metadata: dict[str, Any] | None = None,
):
    _record_activity(
        conn,
        action=action,
        target_type="slack_channel",
        actor_kind="integration",
        actor_label="slack",
        workflow_id=workflow_id,
        target_id=target_id,
        artifact_id=artifact_id,
        metadata=metadata,
    )


def _find_workflow_by_project_key(conn: sqlite3.Connection, project_key: str) -> sqlite3.Row | None:
    rows = conn.execute(
        """SELECT * FROM workflow_instances
           WHERE template_id=?
           ORDER BY created_at""",
        (PLANNING_TEMPLATE_ID,),
    ).fetchall()
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            continue
        if metadata.get("project_key") == project_key:
            return row
    return None


def _create_planning_workflow(
    conn: sqlite3.Connection,
    *,
    team_id: str,
    enterprise_id: str,
    channel_id: str,
    channel_name: str,
    company_name: str,
    project_key: str,
) -> str:
    tmpl = row_to_dict(conn.execute("SELECT * FROM workflow_templates WHERE id=?", (PLANNING_TEMPLATE_ID,)).fetchone())
    if not tmpl:
        raise HTTPException(500, "Planning template not found")
    first_stage = conn.execute(
        "SELECT * FROM stage_definitions WHERE template_id=? ORDER BY stage_order LIMIT 1",
        (PLANNING_TEMPLATE_ID,),
    ).fetchone()
    if not first_stage:
        raise HTTPException(500, "Planning template has no stages")

    now = _now()
    wf_id = _uuid("wi_")
    metadata = {
        "company_name": company_name,
        "project_key": project_key,
        "source": "slack",
        "slack": {
            "team_id": team_id,
            "enterprise_id": enterprise_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
        },
        "mvp_scope": "research_only",
        "future_placeholders": ["synopsis", "storyboard", "script"],
    }
    conn.execute(
        """INSERT INTO workflow_instances
           (id, template_id, agent_type_id, title, current_stage_id, status, priority, assignee, metadata_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            wf_id,
            PLANNING_TEMPLATE_ID,
            tmpl["agent_type_id"],
            f"[{company_name}] 기획 자료조사",
            first_stage["id"],
            "active",
            1,
            PLANNING_ASSIGNEE,
            json.dumps(metadata, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at) VALUES (?,?,?,?,?,?)",
        (wf_id, None, first_stage["id"], "slack", "Slack channel onboarding", now),
    )
    _emit_event(conn, "workflow_created", wf_id)
    _record_slack_activity(
        conn,
        action="slack.workflow_created",
        workflow_id=wf_id,
        target_id=channel_id,
        metadata={"team_id": team_id, "channel_id": channel_id, "channel_name": channel_name, "company_name": company_name},
    )
    return wf_id


def _ensure_mapping(
    conn: sqlite3.Connection,
    *,
    team_id: str,
    enterprise_id: str,
    channel_id: str,
    channel_name: str,
    event_id: str,
) -> tuple[sqlite3.Row, bool, bool]:
    company_name = _extract_company_name(channel_name)
    normalized = _normalize_channel_name(channel_name)
    project_key = f"planning-research:{company_name}"
    now = _now()

    existing = conn.execute(
        "SELECT * FROM slack_channel_project_mappings WHERE team_id=? AND channel_id=?",
        (team_id, channel_id),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE slack_channel_project_mappings
               SET channel_name=?, normalized_channel_name=?, last_event_id=?, updated_at=?
               WHERE id=?""",
            (channel_name, normalized, event_id, now, existing["id"]),
        )
        mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE id=?", (existing["id"],)).fetchone()
        return mapping, False, False

    existing_project_mapping = conn.execute(
        "SELECT * FROM slack_channel_project_mappings WHERE team_id=? AND project_key=?",
        (team_id, project_key),
    ).fetchone()
    if existing_project_mapping:
        _record_slack_activity(
            conn,
            action="slack.project_already_linked",
            workflow_id=existing_project_mapping["workflow_id"],
            target_id=channel_id,
            metadata={
                "team_id": team_id,
                "channel_id": channel_id,
                "existing_channel_id": existing_project_mapping["channel_id"],
                "company_name": company_name,
                "project_key": project_key,
            },
        )
        return existing_project_mapping, False, False

    workflow_created = False
    wf = _find_workflow_by_project_key(conn, project_key)
    if wf:
        workflow_id = wf["id"]
    else:
        workflow_id = _create_planning_workflow(
            conn,
            team_id=team_id,
            enterprise_id=enterprise_id,
            channel_id=channel_id,
            channel_name=channel_name,
            company_name=company_name,
            project_key=project_key,
        )
        workflow_created = True

    message = _onboarding_message(company_name)
    mapping_id = _uuid("scpm_")
    try:
        conn.execute(
            """INSERT INTO slack_channel_project_mappings
               (id, team_id, enterprise_id, channel_id, channel_name, normalized_channel_name,
                company_name, project_key, workflow_id, status, onboarding_message, first_event_id,
                last_event_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mapping_id,
                team_id,
                enterprise_id,
                channel_id,
                channel_name,
                normalized,
                company_name,
                project_key,
                workflow_id,
                "active",
                message,
                event_id,
                event_id,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        mapping = conn.execute(
            "SELECT * FROM slack_channel_project_mappings WHERE team_id=? AND channel_id=?",
            (team_id, channel_id),
        ).fetchone()
        if not mapping:
            mapping = conn.execute(
                "SELECT * FROM slack_channel_project_mappings WHERE team_id=? AND project_key=?",
                (team_id, project_key),
            ).fetchone()
        if not mapping:
            raise
        return mapping, False, workflow_created

    mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE id=?", (mapping_id,)).fetchone()
    _emit_event(
        conn,
        "slack_channel_onboarded",
        workflow_id,
        payload={"mapping_id": mapping_id, "team_id": team_id, "channel_id": channel_id, "company_name": company_name},
    )
    _record_slack_activity(
        conn,
        action="slack.channel_onboarded",
        workflow_id=workflow_id,
        target_id=mapping_id,
        metadata={
            "team_id": team_id,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "company_name": company_name,
            "project_key": project_key,
            "workflow_created": workflow_created,
        },
    )
    return mapping, True, workflow_created


def _post_slack_message(channel_id: str, message: str) -> dict[str, Any]:
    if _env_bool("HERMES_AX_SLACK_DRY_RUN"):
        return {"sent": True, "ts": f"dry-run-{channel_id}", "dry_run": True}

    result = _call_slack_api("chat.postMessage", {"channel": channel_id, "text": message})
    if not result.get("ok"):
        return {"sent": False, "reason": result.get("reason") or "slack_api_error", "error": result.get("error") or "unknown_error"}
    data = result.get("data") or {}
    return {"sent": True, "ts": str(data.get("ts") or "")}


def _update_slack_message(channel_id: str, message_ts: str, message: str) -> dict[str, Any]:
    """Update the single planning progress message, falling back at caller level."""
    if _env_bool("HERMES_AX_SLACK_DRY_RUN"):
        return {"sent": True, "ts": message_ts or f"dry-run-{channel_id}", "updated": bool(message_ts), "dry_run": True}
    if not message_ts:
        return {"sent": False, "reason": "missing_message_ts"}

    result = _call_slack_api("chat.update", {"channel": channel_id, "ts": message_ts, "text": message})
    if not result.get("ok"):
        return {"sent": False, "reason": result.get("reason") or "slack_api_error", "error": result.get("error") or "unknown_error"}
    data = result.get("data") or {}
    return {"sent": True, "ts": str(data.get("ts") or message_ts), "updated": True}


def _send_progress_message(conn: sqlite3.Connection, mapping: sqlite3.Row, message: str) -> dict[str, Any]:
    """Post once, then update the same Slack status message for planning progress."""
    state = conn.execute(
        "SELECT last_message_ts FROM slack_material_collection_states WHERE workflow_id=?",
        (mapping["workflow_id"],),
    ).fetchone()
    existing_ts = str(state["last_message_ts"] or "").strip() if state else ""
    if existing_ts:
        update_result = _update_slack_message(mapping["channel_id"], existing_ts, message)
        if update_result.get("sent"):
            return update_result
        post_result = _post_slack_message(mapping["channel_id"], message)
        if not post_result.get("sent"):
            post_result["update_error"] = update_result.get("error") or update_result.get("reason") or "update_failed"
        else:
            post_result["fallback_from_update"] = True
        return post_result
    return _post_slack_message(mapping["channel_id"], message)


def _run_worker_request_background(request_id: str) -> None:
    """Run one queued worker request outside the Slack event response path."""
    # Slack event DB writes commit after the request handler exits. The
    # background runner may briefly race that commit or SQLite locks, so retry a
    # few times before leaving the request queued for the manual runner.
    try:
        try:
            from .research_worker import run_worker_request
        except ImportError:
            from research_worker import run_worker_request
        for attempt in range(10):
            time.sleep(0.1 if attempt == 0 else min(0.25 * attempt, 1.0))
            try:
                with get_db() as conn:
                    run_worker_request(conn, request_id)
                return
            except HTTPException as exc:
                # Another runner already claimed/completed it; the DB claim is
                # the source of truth and duplicate execution is prevented.
                if exc.status_code == 409:
                    return
                if exc.status_code != 404 or attempt == 9:
                    return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 9:
                    return
    except Exception:
        # Keep Slack event handling best-effort: failures are reflected by the
        # worker request remaining queued/running/failed and can be retried by
        # the manual /worker/run-queued endpoint.
        return


def _kick_worker_runner(request_id: str) -> dict[str, Any]:
    """Schedule a non-blocking run for the just-created queued worker request."""
    request_id = str(request_id or "").strip()
    if not request_id:
        return {"scheduled": False, "reason": "request_id_required"}
    if _env_bool("HERMES_AX_WORKER_AUTO_RUNNER_DISABLED"):
        return {"scheduled": False, "request_id": request_id, "reason": "auto_runner_disabled"}
    thread = threading.Thread(target=_run_worker_request_background, args=(request_id,), daemon=True)
    thread.start()
    return {"scheduled": True, "request_id": request_id, "mode": "background_thread"}


def _post_onboarding_message(channel_id: str, message: str) -> dict[str, Any]:
    return _post_slack_message(channel_id, message)


def _maybe_send_onboarding_message(conn: sqlite3.Connection, mapping: sqlite3.Row) -> dict[str, Any]:
    if mapping["onboarding_message_sent_at"]:
        return {"message_sent": False, "message_skipped_reason": "already_sent"}

    message = mapping["onboarding_message"] or _onboarding_message(mapping["company_name"])
    join_result = _join_slack_channel(mapping["channel_id"])
    now = _now()
    if not join_result.get("joined"):
        error = join_result.get("error") or join_result.get("reason") or "slack_join_failed"
        conn.execute(
            "UPDATE slack_channel_project_mappings SET last_error=?, updated_at=? WHERE id=?",
            (error, now, mapping["id"]),
        )
        _record_slack_activity(
            conn,
            action="slack.onboarding_message_failed",
            workflow_id=mapping["workflow_id"],
            target_id=mapping["id"],
            metadata={
                "team_id": mapping["team_id"],
                "channel_id": mapping["channel_id"],
                "company_name": mapping["company_name"],
                "reason": join_result.get("reason") or "slack_join_failed",
                "join_error": error,
            },
        )
        return {"message_sent": False, "message_skipped_reason": join_result.get("reason") or "slack_join_failed"}

    send_result = _post_onboarding_message(mapping["channel_id"], message)
    now = _now()
    if send_result.get("sent"):
        conn.execute(
            """UPDATE slack_channel_project_mappings
               SET onboarding_message=?, onboarding_message_ts=?, onboarding_message_sent_at=?, last_error='', updated_at=?
               WHERE id=?""",
            (message, send_result.get("ts") or "", now, now, mapping["id"]),
        )
        _record_slack_activity(
            conn,
            action="slack.onboarding_message_sent",
            workflow_id=mapping["workflow_id"],
            target_id=mapping["id"],
            metadata={
                "team_id": mapping["team_id"],
                "channel_id": mapping["channel_id"],
                "company_name": mapping["company_name"],
                "dry_run": bool(send_result.get("dry_run")),
            },
        )
        return {"message_sent": True, "onboarding_message_ts": send_result.get("ts") or ""}

    error = send_result.get("error") or send_result.get("reason") or "unknown_error"
    conn.execute(
        "UPDATE slack_channel_project_mappings SET last_error=?, updated_at=? WHERE id=?",
        (error, now, mapping["id"]),
    )
    _record_slack_activity(
        conn,
        action="slack.onboarding_message_failed",
        workflow_id=mapping["workflow_id"],
        target_id=mapping["id"],
        metadata={
            "team_id": mapping["team_id"],
            "channel_id": mapping["channel_id"],
            "company_name": mapping["company_name"],
            "reason": send_result.get("reason") or "unknown_error",
        },
    )
    return {"message_sent": False, "message_skipped_reason": send_result.get("reason") or "send_failed"}


def _slack_file_extension(file_info: dict[str, Any]) -> str:
    name = str(file_info.get("name") or file_info.get("title") or "")
    if "." in name:
        return name.rsplit(".", 1)[-1].lower()
    return str(file_info.get("filetype") or "").strip().lower()


def _slack_file_supported(file_info: dict[str, Any]) -> tuple[bool, str]:
    size = int(file_info.get("size") or 0)
    max_size = _slack_max_file_size_bytes()
    if size > max_size:
        return False, f"file_too_large:{size}>{max_size}"

    mimetype = str(file_info.get("mimetype") or file_info.get("mime_type") or "").strip().lower()
    ext = _slack_file_extension(file_info)
    if ext in SUPPORTED_SLACK_FILE_EXTENSIONS or mimetype in SUPPORTED_SLACK_FILE_MIMES:
        return True, ""
    return False, f"unsupported_file_type:{mimetype or ext or 'unknown'}"


def _slack_file_content_bytes(file_info: dict[str, Any]) -> bytes | None:
    if "content_text" in file_info:
        return str(file_info.get("content_text") or "").encode("utf-8")
    if "content" in file_info:
        content = file_info.get("content")
        if isinstance(content, str):
            return content.encode("utf-8")
        if isinstance(content, bytes):
            return content
    url = str(file_info.get("url_private_download") or file_info.get("url_private") or "").strip()
    return _download_slack_file_bytes(url) if url else None


def _download_slack_file_bytes(url: str) -> bytes | None:
    """Future-compatible Slack file downloader; disabled unless explicitly opted in."""
    if _env_bool("HERMES_AX_SLACK_DRY_RUN"):
        return None
    if not _env_bool("HERMES_AX_SLACK_DOWNLOAD_FILES"):
        return None
    token = _slack_bot_token()
    if not token:
        return None
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    timeout = float(os.getenv("HERMES_AX_SLACK_API_TIMEOUT_SECONDS", "2"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError):
        return None


def _slack_file_manifest(file_info: dict[str, Any], *, reason: str = "metadata_manifest") -> str:
    safe_metadata = {k: v for k, v in file_info.items() if k not in {"content", "content_text"}}
    return "Slack file metadata manifest\n" + json.dumps({"reason": reason, "file": safe_metadata}, ensure_ascii=False, indent=2)


def _slack_file_metadata_json(file_info: dict[str, Any], *, reason: str = "slack_file_metadata") -> str:
    safe_metadata = {k: v for k, v in file_info.items() if k not in {"content", "content_text"}}
    return json.dumps({"reason": reason, "file": safe_metadata}, ensure_ascii=False)


def _source_material_stage_id(conn: sqlite3.Connection, workflow_id: str) -> str:
    stage = conn.execute(
        """SELECT s.id FROM workflow_instances w
           JOIN stage_definitions s ON s.template_id=w.template_id
           WHERE w.id=? AND s.id='p_material_waiting'
           LIMIT 1""",
        (workflow_id,),
    ).fetchone()
    if stage:
        return stage["id"]
    wf = conn.execute("SELECT current_stage_id FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
    return wf["current_stage_id"] if wf else "p_material_waiting"


def _create_slack_source_artifact(
    conn: sqlite3.Connection,
    *,
    workflow_id: str,
    stage_id: str,
    file_info: dict[str, Any],
    filename: str,
    title: str,
    mimetype: str,
) -> str:
    art_id = _uuid("art_")
    content_bytes = _slack_file_content_bytes(file_info)
    manifest = _slack_file_manifest(file_info)
    manifest_fallback = content_bytes is None
    stored_mimetype = mimetype or "application/octet-stream"
    stored_filename = filename
    if manifest_fallback:
        content_bytes = manifest.encode("utf-8")
        stored_mimetype = "text/plain"
        stored_filename = f"{filename or title or 'slack-file'}.manifest.txt"
    stored = get_artifact_storage().write_bytes(
        workflow_id=workflow_id,
        stage_id=stage_id,
        artifact_id=art_id,
        content=content_bytes,
        mime_type=stored_mimetype,
        original_filename=stored_filename,
    )
    content_text = ""
    if (stored_mimetype or "").startswith("text/") or (stored_mimetype or "") in {"application/json", "text/markdown"}:
        try:
            content_text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content_text = ""
    elif content_bytes == manifest.encode("utf-8"):
        content_text = manifest

    version_row = conn.execute(
        """SELECT COALESCE(MAX(version), 0) AS max_version
           FROM artifacts WHERE workflow_id=? AND stage_id=? AND artifact_type=?""",
        (workflow_id, stage_id, "source_material"),
    ).fetchone()
    version = int(version_row["max_version"] or 0) + 1
    now = _now()
    conn.execute(
        """INSERT INTO artifacts
           (id, workflow_id, stage_id, artifact_type, title, content, content_type, status,
            file_path, file_size, mime_type, storage_backend, storage_key, original_filename,
            version, is_latest, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            art_id,
            workflow_id,
            stage_id,
            "source_material",
            title or filename or "Slack 첨부 파일",
            content_text,
            stored.mime_type,
            "final",
            stored.file_path,
            stored.file_size,
            stored.mime_type,
            stored.storage_backend,
            stored.storage_key,
            stored.original_filename,
            version,
            1,
            now,
            now,
        ),
    )
    _emit_event(conn, "artifact_added", workflow_id, art_id)
    return art_id


def _transition_to_material_waiting(conn: sqlite3.Connection, workflow_id: str):
    wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
    if not wf or wf["current_stage_id"] == "p_material_waiting":
        return
    target = conn.execute("SELECT * FROM stage_definitions WHERE template_id=? AND id='p_material_waiting'", (wf["template_id"],)).fetchone()
    if not target:
        return
    current = conn.execute("SELECT stage_order FROM stage_definitions WHERE id=?", (wf["current_stage_id"],)).fetchone()
    if current and int(current["stage_order"]) > int(target["stage_order"]):
        return
    now = _now()
    conn.execute("UPDATE workflow_instances SET current_stage_id=?, updated_at=? WHERE id=?", (target["id"], now, workflow_id))
    conn.execute(
        "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at) VALUES (?,?,?,?,?,?)",
        (workflow_id, wf["current_stage_id"], target["id"], "slack", "Slack source materials collected", now),
    )
    _emit_event(conn, "stage_changed", workflow_id, payload={"from": wf["current_stage_id"], "to": target["id"]})


def _transition_to_research_running(conn: sqlite3.Connection, workflow_id: str):
    wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
    if not wf:
        return
    target = conn.execute("SELECT * FROM stage_definitions WHERE template_id=? AND id='p_research_running'", (wf["template_id"],)).fetchone()
    if not target:
        return
    now = _now()
    if wf["current_stage_id"] == target["id"]:
        conn.execute("UPDATE workflow_instances SET assignee=?, updated_at=? WHERE id=?", (PLANNING_WORKER_ASSIGNEE, now, workflow_id))
        return
    current = conn.execute("SELECT stage_order FROM stage_definitions WHERE id=?", (wf["current_stage_id"],)).fetchone()
    if current and int(current["stage_order"]) > int(target["stage_order"]):
        return
    conn.execute(
        "UPDATE workflow_instances SET current_stage_id=?, assignee=?, updated_at=? WHERE id=?",
        (target["id"], PLANNING_WORKER_ASSIGNEE, now, workflow_id),
    )
    conn.execute(
        "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at) VALUES (?,?,?,?,?,?)",
        (workflow_id, wf["current_stage_id"], target["id"], "slack", "Slack material collection confirmed", now),
    )
    _emit_event(conn, "stage_changed", workflow_id, payload={"from": wf["current_stage_id"], "to": target["id"]})


def _transition_planning_stage(
    conn: sqlite3.Connection,
    workflow_id: str,
    target_stage_id: str,
    *,
    assignee: str,
    note: str,
    status: str | None = None,
) -> None:
    wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
    if not wf:
        return
    target = conn.execute("SELECT * FROM stage_definitions WHERE template_id=? AND id=?", (wf["template_id"], target_stage_id)).fetchone()
    if not target:
        return
    now = _now()
    status_sql = ", status=?" if status else ""
    params: list[Any] = [target_stage_id, assignee, now]
    if status:
        params.append(status)
    params.append(workflow_id)
    conn.execute(
        f"UPDATE workflow_instances SET current_stage_id=?, assignee=?, updated_at=?{status_sql} WHERE id=?",
        params,
    )
    if wf["current_stage_id"] != target_stage_id:
        conn.execute(
            "INSERT INTO stage_transitions (workflow_id, from_stage_id, to_stage_id, triggered_by, note, created_at) VALUES (?,?,?,?,?,?)",
            (workflow_id, wf["current_stage_id"], target_stage_id, "slack", note, now),
        )
        _emit_event(conn, "stage_changed", workflow_id, payload={"from": wf["current_stage_id"], "to": target_stage_id})


def _mapping_for_workflow(conn: sqlite3.Connection, workflow_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM slack_channel_project_mappings WHERE workflow_id=? AND status='active' LIMIT 1",
        (workflow_id,),
    ).fetchone()


def _mapping_value(mapping: sqlite3.Row | dict[str, Any], key: str, default: str = "") -> str:
    try:
        value = mapping[key]
    except (KeyError, IndexError, TypeError):
        value = default
    return str(value or default).strip()


def _mapping_table_has_column(conn: sqlite3.Connection, column: str) -> bool:
    return any(row[1] == column for row in conn.execute("PRAGMA table_info(slack_channel_project_mappings)").fetchall())


def _payload_notebook_id(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    for source in (metadata, result, payload):
        notebook_id = str(source.get("notebook_id") or "").strip()
        if notebook_id:
            return notebook_id
    return ""


def _workflow_company_name(wf: sqlite3.Row | dict[str, Any]) -> str:
    try:
        metadata = json.loads(wf["metadata_json"] or "{}")
    except Exception:
        metadata = {}
    return str(metadata.get("company_name") or wf["title"].strip("[]").split("]")[0] or "").strip()


def _worker_source_files(conn: sqlite3.Connection, workflow_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, artifact_id, slack_file_id, filename, title, mimetype, size, url_private, url_private_download, uploaded_user, uploaded_ts
           FROM slack_workflow_source_files
           WHERE workflow_id=? AND status='stored'
           ORDER BY created_at, id""",
        (workflow_id,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def _latest_research_artifact(conn: sqlite3.Connection, workflow_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT id, title, artifact_type, stage_id, version, is_latest
           FROM artifacts
           WHERE workflow_id=? AND artifact_type='research_report'
           ORDER BY is_latest DESC, version DESC, created_at DESC LIMIT 1""",
        (workflow_id,),
    ).fetchone()
    return row_to_dict(row) if row else None


def _finalize_latest_research_artifact(conn: sqlite3.Connection, workflow_id: str) -> str:
    row = conn.execute(
        """SELECT id FROM artifacts
           WHERE workflow_id=? AND artifact_type='research_report'
           ORDER BY is_latest DESC, version DESC, created_at DESC LIMIT 1""",
        (workflow_id,),
    ).fetchone()
    if not row:
        return ""
    now = _now()
    conn.execute("UPDATE artifacts SET status='final', is_latest=1, updated_at=? WHERE id=?", (now, row["id"]))
    _emit_event(conn, "artifact_updated", workflow_id, row["id"])
    return str(row["id"])


def _build_worker_payload(
    conn: sqlite3.Connection,
    *,
    mapping: sqlite3.Row,
    request_type: str,
    source_event_id: str,
    revision_instruction: str = "",
    revision_attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (mapping["workflow_id"],)).fetchone()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    try:
        metadata = json.loads(wf["metadata_json"] or "{}")
    except Exception:
        metadata = {}
    task_type = "revision" if request_type == "revision" else "initial_research"
    stage_id = STAGE_REVISION_RUNNING if request_type == "revision" else STAGE_RESEARCH_RUNNING
    notebook_id = _mapping_value(mapping, "notebook_id")
    notebook_binding = {
        "provider": "notebooklm_py",
        "scope": "slack_channel",
        "mapping_id": _mapping_value(mapping, "id"),
        "team_id": _mapping_value(mapping, "team_id"),
        "channel_id": _mapping_value(mapping, "channel_id"),
        "notebook_id": notebook_id,
    }
    payload = {
        "schema_version": 1,
        "worker": "planning_material_research_worker",
        "task_type": task_type,
        "workflow_id": wf["id"],
        "stage_id": stage_id,
        "company_name": _workflow_company_name(wf),
        "project_key": metadata.get("project_key", ""),
        "requested_by": "planning_lead_orchestrator",
        "source_event_id": source_event_id,
        "research_engine": _research_engine_name(),
        "fallback_engine": _research_fallback_engine_name(),
        "prompt": _research_prompt_metadata(conn),
        "notebook_id": notebook_id,
        "notebook_binding": notebook_binding,
        "slack": {
            "team_id": mapping["team_id"],
            "channel_id": mapping["channel_id"],
            "channel_name": mapping["channel_name"],
            "mapping_id": mapping["id"],
        },
        "source_files": _worker_source_files(conn, wf["id"]),
    }
    if request_type == "revision":
        payload["revision"] = {
            "instruction": revision_instruction.strip(),
            "attachments": revision_attachments or [],
            "base_report": _latest_research_artifact(conn, wf["id"]),
        }
    return payload


def _create_worker_request(
    conn: sqlite3.Connection,
    *,
    mapping: sqlite3.Row,
    request_type: str,
    source_event_id: str,
    revision_instruction: str = "",
    revision_attachments: list[dict[str, Any]] | None = None,
) -> sqlite3.Row:
    payload = _build_worker_payload(
        conn,
        mapping=mapping,
        request_type=request_type,
        source_event_id=source_event_id,
        revision_instruction=revision_instruction,
        revision_attachments=revision_attachments,
    )
    now = _now()
    req_id = _uuid("wreq_")
    conn.execute(
        """INSERT INTO planning_worker_requests
           (id, workflow_id, mapping_id, request_type, status, payload_json, source_event_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (req_id, mapping["workflow_id"], mapping["id"], request_type, "queued", json.dumps(payload, ensure_ascii=False), source_event_id, now, now),
    )
    _record_slack_activity(
        conn,
        action="slack.worker_request_created",
        workflow_id=mapping["workflow_id"],
        target_id=req_id,
        metadata={"request_type": request_type, "task_type": payload["task_type"], "source_event_id": source_event_id},
    )
    return conn.execute("SELECT * FROM planning_worker_requests WHERE id=?", (req_id,)).fetchone()


def _review_message_for_result(title: str) -> str:
    return f"자료조사 결과가 도착했습니다: {title}\n검토 후 확정이면 '확정' 또는 '좋아'라고 답해주세요. 수정이 필요하면 요청 사항을 그대로 남겨주세요."


def _positive_reply(text: str) -> bool:
    normalized = re.sub(r"[\s!?.。~]+", "", text.strip().lower())
    if not normalized:
        return False
    positive_values = {"ㅇㅋ", "오케이", "ok", "okay", "좋아", "좋아요", "진행해", "진행", "다음", "확정", "승인", "네", "넵"}
    if normalized in positive_values:
        return True
    return any(token in normalized for token in ("확정", "진행해", "좋아요", "좋습니다")) and len(normalized) <= 20


def _create_research_report_artifact(conn: sqlite3.Connection, *, workflow_id: str, title: str, content: str) -> str:
    now = _now()
    art_id = _uuid("art_")
    version_row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS max_version FROM artifacts WHERE workflow_id=? AND artifact_type='research_report'",
        (workflow_id,),
    ).fetchone()
    version = int(version_row["max_version"] or 0) + 1
    conn.execute(
        "UPDATE artifacts SET is_latest=0, updated_at=? WHERE workflow_id=? AND artifact_type='research_report'",
        (now, workflow_id),
    )
    conn.execute(
        """INSERT INTO artifacts
           (id, workflow_id, stage_id, artifact_type, title, content, content_type, status,
            file_path, file_size, mime_type, storage_backend, storage_key, original_filename,
            version, is_latest, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            art_id,
            workflow_id,
            STAGE_USER_REVIEW_WAITING,
            "research_report",
            title,
            content,
            "text/markdown",
            "draft",
            "",
            0,
            "text/markdown",
            "local",
            "",
            "",
            version,
            1,
            now,
            now,
        ),
    )
    _emit_event(conn, "artifact_added", workflow_id, art_id)
    return art_id


def _create_revision_file_artifacts(
    conn: sqlite3.Connection,
    *,
    workflow_id: str,
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for index, file_info in enumerate(files):
        if not isinstance(file_info, dict):
            continue
        supported, rejection_reason = _slack_file_supported(file_info)
        if not supported:
            attachments.append({
                "filename": str(file_info.get("name") or file_info.get("title") or f"file-{index}"),
                "status": "rejected",
                "rejection_reason": rejection_reason,
            })
            continue
        filename = str(file_info.get("name") or file_info.get("title") or f"revision-{index}").strip()
        title = str(file_info.get("title") or filename).strip()
        mimetype = str(file_info.get("mimetype") or file_info.get("mime_type") or "text/plain").strip()
        artifact_id = _create_slack_source_artifact(
            conn,
            workflow_id=workflow_id,
            stage_id=STAGE_REVISION_RUNNING,
            file_info=file_info,
            filename=filename,
            title=title,
            mimetype=mimetype,
        )
        conn.execute(
            "UPDATE artifacts SET artifact_type='revision_request', title=? WHERE id=?",
            (title, artifact_id),
        )
        attachments.append({
            "artifact_id": artifact_id,
            "slack_file_id": str(file_info.get("id") or ""),
            "filename": filename,
            "title": title,
            "mimetype": mimetype,
            "status": "stored",
        })
    return attachments


def _handle_review_reply_event(
    conn: sqlite3.Connection,
    *,
    mapping: sqlite3.Row,
    event: dict[str, Any],
    files: list[dict[str, Any]],
    event_id: str,
    team_id: str,
    channel_id: str,
) -> dict[str, Any] | None:
    wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (mapping["workflow_id"],)).fetchone()
    if not wf or wf["current_stage_id"] != STAGE_USER_REVIEW_WAITING:
        return None

    text = str(event.get("text") or "").strip()
    if files:
        attachments = _create_revision_file_artifacts(conn, workflow_id=mapping["workflow_id"], files=files)
        instruction = text or "첨부 파일 기준으로 자료조사 결과를 수정해주세요."
        _transition_planning_stage(
            conn,
            mapping["workflow_id"],
            STAGE_REVISION_RUNNING,
            assignee=PLANNING_WORKER_ASSIGNEE,
            note="Slack review attachment requested revision",
        )
        worker_request = _create_worker_request(
            conn,
            mapping=mapping,
            request_type="revision",
            source_event_id=event_id,
            revision_instruction=instruction,
            revision_attachments=attachments,
        )
        message = "수정 요청 파일을 확인했습니다. 기획팀 임사원에게 자료조사 worker 수정 실행을 전달했습니다."
        send_result = _send_progress_message(conn, mapping, message)
        _upsert_material_state(conn, mapping=mapping, message=message, send_result=send_result, status="revision_running")
        _record_slack_activity(
            conn,
            action="slack.revision_requested",
            workflow_id=mapping["workflow_id"],
            target_id=worker_request["id"],
            metadata={"team_id": team_id, "channel_id": channel_id, "event_id": event_id, "request_type": "attachment", "dry_run": bool(send_result.get("dry_run"))},
        )
        return {
            "ok": bool(send_result.get("sent")),
            "workflow_id": mapping["workflow_id"],
            "mapping_id": mapping["id"],
            "channel_id": channel_id,
            "review_status": "revision_requested",
            "current_stage_id": STAGE_REVISION_RUNNING,
            "worker_request_id": worker_request["id"],
            "message": message,
            "message_sent": bool(send_result.get("sent")),
            "message_ts": send_result.get("ts") or "",
        }

    if _positive_reply(text):
        final_artifact_id = _finalize_latest_research_artifact(conn, mapping["workflow_id"])
        _transition_planning_stage(
            conn,
            mapping["workflow_id"],
            STAGE_RESEARCH_CONFIRMED,
            assignee=PLANNING_ASSIGNEE,
            note="Slack review confirmed research",
            status="completed",
        )
        message = "자료조사 결과를 확정했습니다. 감사합니다."
        send_result = _send_progress_message(conn, mapping, message)
        _upsert_material_state(conn, mapping=mapping, message=message, send_result=send_result, status="research_confirmed")
        _record_slack_activity(
            conn,
            action="slack.research_confirmed",
            workflow_id=mapping["workflow_id"],
            target_id=mapping["id"],
            metadata={"team_id": team_id, "channel_id": channel_id, "event_id": event_id, "artifact_id": final_artifact_id, "dry_run": bool(send_result.get("dry_run"))},
        )
        return {
            "ok": bool(send_result.get("sent")),
            "workflow_id": mapping["workflow_id"],
            "mapping_id": mapping["id"],
            "channel_id": channel_id,
            "review_status": "confirmed",
            "current_stage_id": STAGE_RESEARCH_CONFIRMED,
            "artifact_id": final_artifact_id,
            "message": message,
            "message_sent": bool(send_result.get("sent")),
            "message_ts": send_result.get("ts") or "",
        }

    if text:
        _transition_planning_stage(
            conn,
            mapping["workflow_id"],
            STAGE_REVISION_RUNNING,
            assignee=PLANNING_WORKER_ASSIGNEE,
            note="Slack review requested revision",
        )
        worker_request = _create_worker_request(
            conn,
            mapping=mapping,
            request_type="revision",
            source_event_id=event_id,
            revision_instruction=text,
            revision_attachments=[],
        )
        message = "수정 요청을 확인했습니다. 기획팀 임사원에게 자료조사 worker 수정 실행을 전달했습니다."
        send_result = _send_progress_message(conn, mapping, message)
        _upsert_material_state(conn, mapping=mapping, message=message, send_result=send_result, status="revision_running")
        _record_slack_activity(
            conn,
            action="slack.revision_requested",
            workflow_id=mapping["workflow_id"],
            target_id=worker_request["id"],
            metadata={"team_id": team_id, "channel_id": channel_id, "event_id": event_id, "request_type": "text", "dry_run": bool(send_result.get("dry_run"))},
        )
        return {
            "ok": bool(send_result.get("sent")),
            "workflow_id": mapping["workflow_id"],
            "mapping_id": mapping["id"],
            "channel_id": channel_id,
            "review_status": "revision_requested",
            "current_stage_id": STAGE_REVISION_RUNNING,
            "worker_request_id": worker_request["id"],
            "message": message,
            "message_sent": bool(send_result.get("sent")),
            "message_ts": send_result.get("ts") or "",
        }
    return {"ok": True, "ignored": True, "reason": "empty_review_reply", "event_type": "message"}


def _material_confirmation_message(stored_files: list[dict[str, Any]], rejected_files: list[dict[str, Any]]) -> str:
    lines = ["첨부된 자료는 다음과 같습니다"]
    if stored_files:
        for item in stored_files:
            lines.append(f"- {item.get('title') or item.get('filename')}")
    else:
        lines.append("- 지원되는 첨부 자료가 아직 없습니다.")
    if rejected_files:
        lines.append("\n지원하지 않는 파일은 제외되었습니다:")
        for item in rejected_files:
            lines.append(f"- {item.get('filename')}: {item.get('rejection_reason')}")
    lines.append(f"\n{_slack_material_upload_guide()}")
    lines.append("\n추가 자료는 없으십니까?")
    return "\n".join(lines)


def _material_more_needed_message() -> str:
    return f"추가 자료가 있으시면 이 채널에 계속 첨부해주세요.\n{_slack_material_upload_guide()}"


def _material_confirmed_message() -> str:
    return "자료 목록 확인이 완료되었습니다. 기획팀 임사원에게 자료조사 worker 실행을 전달했습니다."


def _classify_material_reply(text: str) -> str:
    normalized = re.sub(r"\s+", "", text.strip().lower())
    if not normalized:
        return ""
    if "추가" in normalized and ("있" in normalized or "올리" in normalized or "첨부" in normalized) and "없" not in normalized:
        return "more_needed"
    if "없" in normalized or "자료조사worker" in normalized or "전달" in normalized or _positive_reply(text):
        return "confirmed"
    return ""


def _upsert_material_state(
    conn: sqlite3.Connection,
    *,
    mapping: sqlite3.Row,
    message: str,
    send_result: dict[str, Any],
    status: str = "pending_confirmation",
) -> None:
    counts = conn.execute(
        """SELECT
              SUM(CASE WHEN status='stored' THEN 1 ELSE 0 END) AS stored_count,
              SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected_count
           FROM slack_workflow_source_files WHERE workflow_id=?""",
        (mapping["workflow_id"],),
    ).fetchone()
    now = _now()
    conn.execute(
        """INSERT INTO slack_material_collection_states
           (workflow_id, mapping_id, status, source_file_count, rejected_file_count,
            last_message, last_message_ts, last_message_sent_at, last_error, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(workflow_id) DO UPDATE SET
             mapping_id=excluded.mapping_id,
             status=excluded.status,
             source_file_count=excluded.source_file_count,
             rejected_file_count=excluded.rejected_file_count,
             last_message=excluded.last_message,
             last_message_ts=excluded.last_message_ts,
             last_message_sent_at=excluded.last_message_sent_at,
             last_error=excluded.last_error,
             updated_at=excluded.updated_at""",
        (
            mapping["workflow_id"],
            mapping["id"],
            status,
            int(counts["stored_count"] or 0),
            int(counts["rejected_count"] or 0),
            message,
            send_result.get("ts") or "",
            now if send_result.get("sent") else None,
            "" if send_result.get("sent") else (send_result.get("error") or send_result.get("reason") or "send_failed"),
            now,
        ),
    )


def _handle_material_text_event(
    conn: sqlite3.Connection,
    *,
    mapping: sqlite3.Row,
    event: dict[str, Any],
    event_id: str,
    team_id: str,
    channel_id: str,
) -> dict[str, Any]:
    state = conn.execute(
        "SELECT * FROM slack_material_collection_states WHERE workflow_id=?",
        (mapping["workflow_id"],),
    ).fetchone()
    if not state or state["status"] not in {"pending_confirmation", "awaiting_more_materials"}:
        return {"ok": True, "ignored": True, "reason": "message_without_files", "event_type": "message"}

    intent = _classify_material_reply(str(event.get("text") or ""))
    if not intent:
        return {"ok": True, "ignored": True, "reason": "message_without_files", "event_type": "message"}

    runner_kick_result: dict[str, Any] = {}
    if intent == "more_needed":
        message = _material_more_needed_message()
        material_status = "awaiting_more_materials"
        send_result = _send_progress_message(conn, mapping, message)
        now = _now()
        conn.execute(
            "UPDATE workflow_instances SET current_stage_id='p_material_waiting', assignee=?, updated_at=? WHERE id=? AND current_stage_id='p_material_waiting'",
            (PLANNING_ASSIGNEE, now, mapping["workflow_id"]),
        )
        _upsert_material_state(conn, mapping=mapping, message=message, send_result=send_result, status=material_status)
        _record_slack_activity(
            conn,
            action="slack.material_collection_more_needed",
            workflow_id=mapping["workflow_id"],
            target_id=mapping["id"],
            metadata={"team_id": team_id, "channel_id": channel_id, "event_id": event_id, "dry_run": bool(send_result.get("dry_run"))},
        )
    else:
        _transition_to_research_running(conn, mapping["workflow_id"])
        worker_request = _create_worker_request(
            conn,
            mapping=mapping,
            request_type="research",
            source_event_id=event_id,
        )
        message = _material_confirmed_message()
        material_status = "confirmed"
        send_result = _post_slack_message(mapping["channel_id"], message)
        _upsert_material_state(conn, mapping=mapping, message=message, send_result=send_result, status=material_status)
        runner_kick_result = _kick_worker_runner(worker_request["id"])
        _record_slack_activity(
            conn,
            action="slack.material_collection_confirmed",
            workflow_id=mapping["workflow_id"],
            target_id=mapping["id"],
            metadata={"team_id": team_id, "channel_id": channel_id, "event_id": event_id, "worker_request_id": worker_request["id"], "dry_run": bool(send_result.get("dry_run"))},
        )

    wf = conn.execute("SELECT current_stage_id, assignee FROM workflow_instances WHERE id=?", (mapping["workflow_id"],)).fetchone()
    response = {
        "ok": bool(send_result.get("sent")),
        "workflow_id": mapping["workflow_id"],
        "mapping_id": mapping["id"],
        "channel_id": channel_id,
        "material_status": material_status,
        "current_stage_id": wf["current_stage_id"] if wf else "",
        "assignee": wf["assignee"] if wf else "",
        "message": message,
        "message_sent": bool(send_result.get("sent")),
        "message_ts": send_result.get("ts") or "",
    }
    if runner_kick_result:
        response["worker_runner_scheduled"] = bool(runner_kick_result.get("scheduled"))
        response["worker_runner_mode"] = runner_kick_result.get("mode", "")
    if not send_result.get("sent"):
        response["reason"] = send_result.get("reason") or "send_failed"
    return response


def _message_event_ignore_reason(event: dict[str, Any]) -> str:
    """Return an ignore reason for Slack message events AX should not treat as user replies."""
    subtype = str(event.get("subtype") or "").strip()
    user_id = str(event.get("user") or "").strip()
    bot_user_id = _slack_bot_user_id()
    if event.get("bot_id") or subtype == "bot_message" or (bot_user_id and user_id == bot_user_id):
        return "bot_message"
    if subtype and subtype != "file_share":
        return "unsupported_message_subtype"
    return ""


def _handle_message_files_event(conn: sqlite3.Connection, *, payload: dict[str, Any], event: dict[str, Any], event_id: str, team_id: str, channel_id: str) -> dict[str, Any]:
    ignore_reason = _message_event_ignore_reason(event)
    if ignore_reason:
        return {"ok": True, "ignored": True, "reason": ignore_reason, "event_type": "message", "channel_id": channel_id}

    files = event.get("files") or []
    if not isinstance(files, list):
        files = []

    mapping = conn.execute(
        "SELECT * FROM slack_channel_project_mappings WHERE team_id=? AND channel_id=? AND status='active'",
        (team_id, channel_id),
    ).fetchone()
    if not mapping:
        return {"ok": True, "ignored": True, "reason": "unmapped_channel", "event_type": "message", "channel_id": channel_id}

    review_response = _handle_review_reply_event(
        conn,
        mapping=mapping,
        event=event,
        files=files,
        event_id=event_id,
        team_id=team_id,
        channel_id=channel_id,
    )
    if review_response is not None:
        return review_response

    if not files:
        return _handle_material_text_event(
            conn,
            mapping=mapping,
            event=event,
            event_id=event_id,
            team_id=team_id,
            channel_id=channel_id,
        )

    stage_id = _source_material_stage_id(conn, mapping["workflow_id"])
    stored_files: list[dict[str, Any]] = []
    rejected_files: list[dict[str, Any]] = []
    now = _now()
    for index, file_info in enumerate(files):
        if not isinstance(file_info, dict):
            continue
        slack_file_id = str(file_info.get("id") or f"{event_id}:{index}").strip()
        existing = conn.execute(
            "SELECT * FROM slack_workflow_source_files WHERE mapping_id=? AND slack_file_id=?",
            (mapping["id"], slack_file_id),
        ).fetchone()
        if existing:
            target = stored_files if existing["status"] == "stored" else rejected_files
            target.append(row_to_dict(existing))
            continue

        filename = str(file_info.get("name") or file_info.get("title") or slack_file_id).strip()
        title = str(file_info.get("title") or filename).strip()
        mimetype = str(file_info.get("mimetype") or file_info.get("mime_type") or "").strip()
        if index >= _slack_max_files_per_message():
            supported, rejection_reason = False, f"file_count_limit_exceeded:{_slack_max_files_per_message()}"
        else:
            supported, rejection_reason = _slack_file_supported(file_info)
        artifact_id = ""
        status = "stored" if supported else "rejected"
        if supported:
            artifact_id = _create_slack_source_artifact(
                conn,
                workflow_id=mapping["workflow_id"],
                stage_id=stage_id,
                file_info=file_info,
                filename=filename,
                title=title,
                mimetype=mimetype,
            )
        source_id = _uuid("sfs_")
        conn.execute(
            """INSERT INTO slack_workflow_source_files
               (id, mapping_id, workflow_id, artifact_id, slack_file_id, filename, title, mimetype, size,
                url_private, url_private_download, uploaded_user, uploaded_ts, status, rejection_reason,
                metadata_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_id,
                mapping["id"],
                mapping["workflow_id"],
                artifact_id or None,
                slack_file_id,
                filename,
                title,
                mimetype,
                int(file_info.get("size") or 0),
                str(file_info.get("url_private") or ""),
                str(file_info.get("url_private_download") or ""),
                str(file_info.get("user") or file_info.get("user_id") or event.get("user") or ""),
                str(file_info.get("created") or file_info.get("timestamp") or event.get("ts") or ""),
                status,
                rejection_reason,
                _slack_file_metadata_json(file_info),
                now,
                now,
            ),
        )
        row = {
            "id": source_id,
            "mapping_id": mapping["id"],
            "workflow_id": mapping["workflow_id"],
            "artifact_id": artifact_id,
            "slack_file_id": slack_file_id,
            "filename": filename,
            "title": title,
            "mimetype": mimetype,
            "status": status,
            "rejection_reason": rejection_reason,
        }
        (stored_files if supported else rejected_files).append(row)

    if stored_files:
        _transition_to_material_waiting(conn, mapping["workflow_id"])
    message = _material_confirmation_message(stored_files, rejected_files)
    send_result = _send_progress_message(conn, mapping, message)
    _upsert_material_state(conn, mapping=mapping, message=message, send_result=send_result)
    _record_slack_activity(
        conn,
        action="slack.material_files_collected",
        workflow_id=mapping["workflow_id"],
        target_id=mapping["id"],
        metadata={
            "team_id": team_id,
            "channel_id": channel_id,
            "event_id": event_id,
            "stored_count": len(stored_files),
            "rejected_count": len(rejected_files),
            "dry_run": bool(send_result.get("dry_run")),
        },
    )
    response = {
        "ok": bool(send_result.get("sent")),
        "workflow_id": mapping["workflow_id"],
        "mapping_id": mapping["id"],
        "channel_id": channel_id,
        "stored_count": len(stored_files),
        "rejected_count": len(rejected_files),
        "source_files": stored_files + rejected_files,
        "message": message,
        "message_sent": bool(send_result.get("sent")),
        "message_ts": send_result.get("ts") or "",
    }
    if not send_result.get("sent"):
        response["reason"] = send_result.get("reason") or "send_failed"
    return response


def _receipt_response(conn: sqlite3.Connection, receipt: sqlite3.Row) -> dict[str, Any] | None:
    try:
        response = json.loads(receipt["response_json"] or "{}")
    except Exception:
        response = {}
    if not response and receipt["mapping_id"]:
        mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE id=?", (receipt["mapping_id"],)).fetchone()
        if mapping:
            response = _mapping_response(mapping)
    if response:
        response["duplicate"] = True
        return response
    return None


def _mapping_response(mapping: sqlite3.Row) -> dict[str, Any]:
    return {
        "ok": True,
        "workflow_id": mapping["workflow_id"],
        "mapping_id": mapping["id"],
        "team_id": mapping["team_id"],
        "channel_id": mapping["channel_id"],
        "channel_name": mapping["channel_name"],
        "company_name": mapping["company_name"],
        "project_key": mapping["project_key"],
        "onboarding_message": mapping["onboarding_message"] or _onboarding_message(mapping["company_name"]),
    }


def _record_receipt(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    team_id: str,
    event_type: str,
    channel_id: str,
    body_hash: str,
    request: Request,
) -> sqlite3.Row | None:
    if not event_id:
        return None
    existing = conn.execute("SELECT * FROM slack_event_receipts WHERE event_id=?", (event_id,)).fetchone()
    if existing:
        return existing
    conn.execute(
        """INSERT INTO slack_event_receipts
           (event_id, team_id, event_type, channel_id, retry_num, retry_reason, body_hash, status, received_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            event_id,
            team_id,
            event_type,
            channel_id,
            request.headers.get("X-Slack-Retry-Num", ""),
            request.headers.get("X-Slack-Retry-Reason", ""),
            body_hash,
            "processing",
            _now(),
        ),
    )
    return None


def _finish_receipt(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    status: str,
    response: dict[str, Any],
    mapping_id: str = "",
    workflow_id: str = "",
    error: str = "",
):
    if not event_id:
        return
    conn.execute(
        """UPDATE slack_event_receipts
           SET status=?, mapping_id=?, workflow_id=?, response_json=?, error=?, processed_at=?
           WHERE event_id=?""",
        (status, mapping_id or None, workflow_id or None, json.dumps(response, ensure_ascii=False), error, _now(), event_id),
    )


def _handle_slack_event(payload: dict[str, Any], request: Request, body: bytes) -> dict[str, Any]:
    event = payload.get("event") or {}
    event_type = str(event.get("type") or "").strip()
    team_id = str(payload.get("team_id") or event.get("team") or "").strip()
    enterprise_id = str(payload.get("enterprise_id") or event.get("enterprise") or "").strip()
    event_id = str(payload.get("event_id") or "").strip()
    channel_id, channel_name = _extract_event_channel(event)
    if channel_id and not channel_name and event_type != "message":
        channel_name = _fetch_slack_channel_name(channel_id)
    body_hash = hashlib.sha256(body).hexdigest()

    with get_db() as conn:
        existing_receipt = _record_receipt(
            conn,
            event_id=event_id,
            team_id=team_id,
            event_type=event_type,
            channel_id=channel_id,
            body_hash=body_hash,
            request=request,
        )
        if existing_receipt and existing_receipt["status"] == "succeeded":
            duplicate = _receipt_response(conn, existing_receipt)
            if duplicate:
                return duplicate

        if event_type == "message":
            if not channel_id:
                response = {"ok": False, "reason": "channel_required", "event_type": event_type}
                _finish_receipt(conn, event_id=event_id, status="failed", response=response, error=response["reason"])
                return response
            response = _handle_message_files_event(
                conn,
                payload=payload,
                event=event,
                event_id=event_id,
                team_id=team_id,
                channel_id=channel_id,
            )
            receipt_status = "ignored" if response.get("ignored") else ("succeeded" if response.get("ok") else "failed")
            _finish_receipt(
                conn,
                event_id=event_id,
                status=receipt_status,
                response=response,
                mapping_id=response.get("mapping_id", ""),
                workflow_id=response.get("workflow_id", ""),
                error=response.get("reason", "") if receipt_status == "failed" else "",
            )
            return response

        if event_type not in SUPPORTED_CHANNEL_EVENTS:
            response = {"ok": True, "ignored": True, "reason": "unsupported_event", "event_type": event_type}
            _finish_receipt(conn, event_id=event_id, status="ignored", response=response)
            return response

        bot_user_id = _slack_bot_user_id()
        if event_type == "member_joined_channel":
            if not bot_user_id:
                response = {"ok": True, "ignored": True, "reason": "bot_user_id_required", "event_type": event_type}
                _finish_receipt(conn, event_id=event_id, status="ignored", response=response)
                _record_slack_activity(
                    conn,
                    action="slack.channel_onboarding_ignored",
                    target_id=channel_id or None,
                    metadata={"team_id": team_id, "event_id": event_id, "event_type": event_type, "reason": response["reason"]},
                )
                return response
            if str(event.get("user") or "") != bot_user_id:
                response = {"ok": True, "ignored": True, "reason": "non_bot_member_joined", "event_type": event_type}
                _finish_receipt(conn, event_id=event_id, status="ignored", response=response)
                return response

        if not channel_id or not channel_name:
            response = {"ok": False, "reason": "channel_name_required", "event_type": event_type}
            _finish_receipt(conn, event_id=event_id, status="failed", response=response, error=response["reason"])
            _record_slack_activity(
                conn,
                action="slack.channel_onboarding_failed",
                target_id=channel_id or None,
                metadata={"team_id": team_id, "event_id": event_id, "event_type": event_type, "reason": response["reason"]},
            )
            return response

        mapping, mapping_created, workflow_created = _ensure_mapping(
            conn,
            team_id=team_id,
            enterprise_id=enterprise_id,
            channel_id=channel_id,
            channel_name=channel_name,
            event_id=event_id,
        )
        message_result = _maybe_send_onboarding_message(conn, mapping)
        # Refresh mapping after possible message update.
        mapping = conn.execute("SELECT * FROM slack_channel_project_mappings WHERE id=?", (mapping["id"],)).fetchone()
        response = _mapping_response(mapping)
        send_failed = (
            message_result.get("message_sent") is False
            and message_result.get("message_skipped_reason") not in {None, "already_sent"}
        )
        if send_failed:
            response["ok"] = False
            response["reason"] = message_result.get("message_skipped_reason") or "send_failed"
        response.update(
            {
                "duplicate": False,
                "mapping_created": mapping_created,
                "workflow_created": workflow_created,
                **message_result,
            }
        )
        _finish_receipt(
            conn,
            event_id=event_id,
            status="failed" if send_failed else "succeeded",
            response=response,
            mapping_id=mapping["id"],
            workflow_id=mapping["workflow_id"],
            error=response.get("reason", "") if send_failed else "",
        )
        return response


def _record_worker_result(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("request_id") or "").strip()
    if not request_id:
        raise HTTPException(400, "request_id is required")
    payload_workflow_id = str(payload.get("workflow_id") or "").strip()
    if not payload_workflow_id:
        raise HTTPException(400, "workflow_id is required")

    worker_request = conn.execute("SELECT * FROM planning_worker_requests WHERE id=?", (request_id,)).fetchone()
    if not worker_request:
        raise HTTPException(404, "Worker request not found")
    workflow_id = worker_request["workflow_id"]
    if payload_workflow_id != workflow_id:
        raise HTTPException(400, "workflow_id does not match worker request")
    wf = conn.execute("SELECT * FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
    if not wf:
        raise HTTPException(404, "Workflow not found")
    mapping = _mapping_for_workflow(conn, workflow_id)
    if not mapping:
        raise HTTPException(404, "Slack mapping not found")

    status = str(payload.get("status") or "succeeded").strip().lower()
    terminal_status = "completed" if status in {"succeeded", "completed", "success"} else "failed"
    now = _now()
    if terminal_status == "completed":
        claimed = conn.execute(
            "UPDATE planning_worker_requests SET status='completed', updated_at=?, completed_at=? WHERE id=? AND status='running'",
            (now, now, request_id),
        )
    else:
        claimed = conn.execute(
            "UPDATE planning_worker_requests SET status='failed', updated_at=? WHERE id=? AND status='running'",
            (now, request_id),
        )
    if claimed.rowcount != 1:
        latest = conn.execute("SELECT status FROM planning_worker_requests WHERE id=?", (request_id,)).fetchone()
        latest_status = latest["status"] if latest else "unavailable"
        raise HTTPException(409, f"Worker request is {latest_status}; expected running")

    if terminal_status == "failed":
        error_message = str(payload.get("error") or payload.get("message") or "worker_failed").strip()
        message = "자료조사 작업 중 오류가 발생했습니다. 기획팀 임팀장이 확인 후 다시 안내드리겠습니다."
        send_result = _send_progress_message(conn, mapping, message)
        _upsert_material_state(conn, mapping=mapping, message=message, send_result=send_result, status="worker_failed")
        _record_slack_activity(
            conn,
            action="slack.worker_result_failed",
            workflow_id=workflow_id,
            target_id=request_id,
            metadata={
                "status": status,
                "error": error_message,
                "payload": payload,
                "message_ts": send_result.get("ts") or "",
                "dry_run": bool(send_result.get("dry_run")),
            },
        )
        return {
            "ok": bool(send_result.get("sent")),
            "workflow_id": workflow_id,
            "request_id": request_id,
            "status": "failed",
            "message": message,
            "message_sent": bool(send_result.get("sent")),
            "message_ts": send_result.get("ts") or "",
        }

    title = str(payload.get("title") or f"{_workflow_company_name(wf)} 자료조사 결과").strip()
    content = str(payload.get("content") or payload.get("report_markdown") or "").strip()
    if not content:
        content = json.dumps(payload.get("result") or {}, ensure_ascii=False, indent=2)
    artifact_id = _create_research_report_artifact(conn, workflow_id=workflow_id, title=title, content=content)
    now = _now()
    result_id = _uuid("wres_")
    conn.execute(
        """INSERT INTO planning_worker_results
           (id, request_id, workflow_id, result_type, artifact_id, payload_json, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (result_id, request_id or None, workflow_id, "research_report", artifact_id, json.dumps(payload, ensure_ascii=False), now),
    )
    notebook_id = _payload_notebook_id(payload)
    if notebook_id and _mapping_table_has_column(conn, "notebook_id"):
        conn.execute(
            "UPDATE slack_channel_project_mappings SET notebook_id=?, updated_at=? WHERE id=?",
            (notebook_id, now, mapping["id"]),
        )
    _transition_planning_stage(
        conn,
        workflow_id,
        STAGE_USER_REVIEW_WAITING,
        assignee=PLANNING_ASSIGNEE,
        note="Worker result received",
        status="active",
    )
    message = _review_message_for_result(title)
    send_result = _send_progress_message(conn, mapping, message)
    _upsert_material_state(conn, mapping=mapping, message=message, send_result=send_result, status="review_waiting")
    _record_slack_activity(
        conn,
        action="slack.worker_result_received",
        workflow_id=workflow_id,
        target_id=result_id,
        artifact_id=artifact_id,
        metadata={
            "request_id": request_id,
            "artifact_id": artifact_id,
            "message_ts": send_result.get("ts") or "",
            "dry_run": bool(send_result.get("dry_run")),
        },
    )
    wf_after = conn.execute("SELECT current_stage_id, assignee, status FROM workflow_instances WHERE id=?", (workflow_id,)).fetchone()
    response = {
        "ok": bool(send_result.get("sent")),
        "result_id": result_id,
        "request_id": request_id,
        "workflow_id": workflow_id,
        "artifact_id": artifact_id,
        "current_stage_id": wf_after["current_stage_id"] if wf_after else STAGE_USER_REVIEW_WAITING,
        "assignee": wf_after["assignee"] if wf_after else PLANNING_ASSIGNEE,
        "message": message,
        "message_sent": bool(send_result.get("sent")),
        "message_ts": send_result.get("ts") or "",
    }
    if not send_result.get("sent"):
        response["reason"] = send_result.get("reason") or "send_failed"
    return response


@router.post("/worker/results")
def worker_results(payload: dict[str, Any], request: Request):
    with get_db() as conn:
        _require_authenticated_user(conn, request)
        return _record_worker_result(conn, payload)


@router.post("/slack/events")
async def slack_events(request: Request):
    body = await request.body()
    _verify_slack_signature(dict(request.headers), body)
    payload = _parse_json_body(body)

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}
    if payload.get("type") != "event_callback":
        return {"ok": True, "ignored": True, "reason": "unsupported_payload_type"}
    return _handle_slack_event(payload, request, body)
