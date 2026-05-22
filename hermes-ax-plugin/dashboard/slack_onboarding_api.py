"""Slack channel onboarding routes for the AX planning MVP."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException, Request

try:
    from .activity import _record_activity
    from .common import _now, _uuid
    from .db import get_db
    from .events import _emit_event
    from .rows import row_to_dict
except ImportError:
    from activity import _record_activity
    from common import _now, _uuid
    from db import get_db
    from events import _emit_event
    from rows import row_to_dict

router = APIRouter()

PLANNING_TEMPLATE_ID = "planning_research_mvp_v1"
PLANNING_ASSIGNEE = "기획팀 임팀장"
SUPPORTED_CHANNEL_EVENTS = {"channel_created", "channel_joined", "channel_rename", "member_joined_channel"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


def _onboarding_message(company_name: str) -> str:
    return _message_template().format(company_name=company_name)


def _record_slack_activity(
    conn: sqlite3.Connection,
    *,
    action: str,
    workflow_id: str | None = None,
    target_id: str | None = None,
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


def _post_onboarding_message(channel_id: str, message: str) -> dict[str, Any]:
    if _env_bool("HERMES_AX_SLACK_DRY_RUN"):
        return {"sent": True, "ts": f"dry-run-{int(time.time())}", "dry_run": True}

    token = _slack_bot_token()
    if not token:
        return {"sent": False, "reason": "missing_bot_token"}

    payload = json.dumps({"channel": channel_id, "text": message}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
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
        return {"sent": False, "reason": "slack_api_error", "error": str(exc)}

    if not data.get("ok"):
        return {"sent": False, "reason": "slack_api_rejected", "error": str(data.get("error") or "unknown_error")}
    return {"sent": True, "ts": str(data.get("ts") or "")}


def _maybe_send_onboarding_message(conn: sqlite3.Connection, mapping: sqlite3.Row) -> dict[str, Any]:
    if mapping["onboarding_message_sent_at"]:
        return {"message_sent": False, "message_skipped_reason": "already_sent"}

    message = mapping["onboarding_message"] or _onboarding_message(mapping["company_name"])
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
    if channel_id and not channel_name:
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
