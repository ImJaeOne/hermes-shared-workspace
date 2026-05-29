"""Queued planning research worker runner for the AX dashboard."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import HTTPException

try:
    from .activity import _record_activity
    from .common import _now
    from .research_adapters import (
        DEFAULT_RESEARCH_SKILL_ID,
        ResearchAdapterFailure,
        configured_research_engine,
        run_research_adapter,
    )
    from .slack_onboarding_api import _record_worker_result
except ImportError:
    from activity import _record_activity
    from common import _now
    from research_adapters import (
        DEFAULT_RESEARCH_SKILL_ID,
        ResearchAdapterFailure,
        configured_research_engine,
        run_research_adapter,
    )
    from slack_onboarding_api import _record_worker_result


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()} if row else {}


def load_research_prompt(conn: sqlite3.Connection, skill_id: str = DEFAULT_RESEARCH_SKILL_ID) -> dict[str, Any]:
    """Load the prompt/skill version used by the planning research worker."""
    row = conn.execute(
        "SELECT id, name, description, content, updated_at FROM skills WHERE id=?",
        (skill_id,),
    ).fetchone()
    if not row:
        return {
            "source": "skills",
            "skill_id": skill_id,
            "name": "기획 자료조사 결과 정리",
            "description": "",
            "content": "",
            "version": "",
        }
    return {
        "source": "skills",
        "skill_id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "content": row["content"],
        "version": row["updated_at"],
    }


def _load_payload(request_row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(request_row["payload_json"] or "{}")
    except Exception as exc:
        raise HTTPException(400, "Worker request payload is invalid") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Worker request payload must be an object")
    return payload


def _enrich_source_files(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Attach artifact metadata/content for adapters without persisting secrets back."""

    def _enrich_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched_items: list[dict[str, Any]] = []
        for source in items:
            if not isinstance(source, dict):
                continue
            item = dict(source)
            artifact_id = str(item.get("artifact_id") or "").strip()
            if artifact_id:
                artifact = conn.execute(
                    """SELECT id, title, content, content_type, file_path, file_size, mime_type,
                              storage_backend, storage_key, original_filename, version, is_latest
                       FROM artifacts WHERE id=?""",
                    (artifact_id,),
                ).fetchone()
                if artifact:
                    item["artifact"] = _row_to_dict(artifact)
            enriched_items.append(item)
        return enriched_items

    cloned = dict(payload)
    source_files = payload.get("source_files") if isinstance(payload.get("source_files"), list) else []
    cloned["source_files"] = _enrich_items(source_files)

    revision = payload.get("revision") if isinstance(payload.get("revision"), dict) else None
    if revision is not None:
        revision_cloned = dict(revision)
        attachments = revision.get("attachments") if isinstance(revision.get("attachments"), list) else []
        revision_cloned["attachments"] = _enrich_items(attachments)
        cloned["revision"] = revision_cloned

    return cloned


def _record_worker_activity(
    conn: sqlite3.Connection,
    *,
    action: str,
    workflow_id: str,
    request_id: str,
    metadata: dict[str, Any] | None = None,
):
    _record_activity(
        conn,
        action=action,
        target_type="planning_worker_request",
        actor_kind="agent",
        actor_label="planning_material_research_worker",
        workflow_id=workflow_id,
        target_id=request_id,
        metadata=metadata or {},
    )


def _request_status(conn: sqlite3.Connection, request_id: str) -> str:
    row = conn.execute("SELECT status FROM planning_worker_requests WHERE id=?", (request_id,)).fetchone()
    return row["status"] if row else ""


def run_worker_request(conn: sqlite3.Connection, request_id: str) -> dict[str, Any]:
    """Run one queued worker request and store the result through /worker/results logic."""
    request_row = conn.execute("SELECT * FROM planning_worker_requests WHERE id=?", (request_id,)).fetchone()
    if not request_row:
        raise HTTPException(404, "Worker request not found")
    if request_row["status"] != "queued":
        raise HTTPException(409, f"Worker request is already {request_row['status']}")

    payload = _load_payload(request_row)
    workflow_id = str(payload.get("workflow_id") or request_row["workflow_id"]).strip()
    if not workflow_id:
        raise HTTPException(400, "workflow_id is required")

    engine = str(payload.get("research_engine") or configured_research_engine())
    prompt_meta = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
    prompt = load_research_prompt(conn, str(prompt_meta.get("skill_id") or DEFAULT_RESEARCH_SKILL_ID))
    enriched_payload = _enrich_source_files(conn, payload)

    now = _now()
    claimed = conn.execute(
        "UPDATE planning_worker_requests SET status='running', updated_at=? WHERE id=? AND status='queued'",
        (now, request_id),
    )
    if claimed.rowcount != 1:
        latest_status = _request_status(conn, request_id)
        raise HTTPException(409, f"Worker request is already {latest_status or 'unavailable'}")
    _record_worker_activity(
        conn,
        action="worker.request_running",
        workflow_id=workflow_id,
        request_id=request_id,
        metadata={"engine": engine, "request_type": request_row["request_type"]},
    )
    conn.commit()

    try:
        adapter_result = run_research_adapter(enriched_payload, prompt, engine=engine)
    except ResearchAdapterFailure as exc:
        failure_payload = {
            "request_id": request_id,
            "workflow_id": workflow_id,
            "status": "failed",
            "error": exc.safe_message,
            "diagnostics": {"code": exc.code, **exc.diagnostics},
        }
        response = _record_worker_result(conn, failure_payload)
        response.update(
            {
                "engine_used": engine,
                "request_status": _request_status(conn, request_id),
                "safe_message": exc.safe_message,
            }
        )
        _record_worker_activity(
            conn,
            action="worker.request_failed",
            workflow_id=workflow_id,
            request_id=request_id,
            metadata={"engine": engine, "code": exc.code, "diagnostics": exc.diagnostics},
        )
        conn.commit()
        return response
    except Exception as exc:
        safe_message = "자료조사 실행 중 일시적인 문제가 발생했습니다. 담당자가 확인 후 다시 안내드리겠습니다."
        failure_payload = {
            "request_id": request_id,
            "workflow_id": workflow_id,
            "status": "failed",
            "error": safe_message,
            "diagnostics": {"code": "unexpected_worker_error", "exception_type": type(exc).__name__},
        }
        response = _record_worker_result(conn, failure_payload)
        response.update(
            {
                "engine_used": engine,
                "request_status": _request_status(conn, request_id),
                "safe_message": safe_message,
            }
        )
        _record_worker_activity(
            conn,
            action="worker.request_failed",
            workflow_id=workflow_id,
            request_id=request_id,
            metadata={"engine": engine, "code": "unexpected_worker_error", "exception_type": type(exc).__name__},
        )
        conn.commit()
        return response

    result_payload = {
        "request_id": request_id,
        "workflow_id": workflow_id,
        "status": "succeeded",
        "title": adapter_result.title,
        "content": adapter_result.content,
        "result": adapter_result.metadata,
    }
    response = _record_worker_result(conn, result_payload)
    request_status = _request_status(conn, request_id)
    response.update(
        {
            "engine_used": adapter_result.engine,
            "request_status": request_status,
            "fallback_from": adapter_result.metadata.get("fallback_from", ""),
        }
    )
    _record_worker_activity(
        conn,
        action="worker.request_completed",
        workflow_id=workflow_id,
        request_id=request_id,
        metadata={
            "engine": adapter_result.engine,
            "fallback_from": adapter_result.metadata.get("fallback_from", ""),
            "artifact_id": response.get("artifact_id", ""),
            "result_id": response.get("result_id", ""),
        },
    )
    conn.commit()
    return response


def _next_queued_request(conn: sqlite3.Connection, request_type: str | None = None) -> sqlite3.Row | None:
    if request_type:
        return conn.execute(
            """SELECT * FROM planning_worker_requests
               WHERE status='queued' AND request_type=?
               ORDER BY created_at, id LIMIT 1""",
            (request_type,),
        ).fetchone()
    return conn.execute(
        """SELECT * FROM planning_worker_requests
           WHERE status='queued'
           ORDER BY created_at, id LIMIT 1"""
    ).fetchone()


def run_queued_worker_requests(
    conn: sqlite3.Connection,
    *,
    limit: int = 1,
    request_type: str | None = None,
) -> dict[str, Any]:
    """Run up to ``limit`` queued requests for cron/manual operations."""
    safe_limit = max(0, min(int(limit or 1), 10))
    results: list[dict[str, Any]] = []
    for _ in range(safe_limit):
        request_row = _next_queued_request(conn, request_type=request_type)
        if not request_row:
            break
        results.append(run_worker_request(conn, request_row["id"]))
    return {"ok": True, "processed_count": len(results), "results": results}


__all__ = ["load_research_prompt", "run_queued_worker_requests", "run_worker_request"]
