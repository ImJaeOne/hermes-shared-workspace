"""Worker runner routes for AX planning research requests."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

try:
    from .auth_sessions import _require_authenticated_user
    from .db import get_db
    from .research_worker import run_queued_worker_requests, run_worker_request
except ImportError:
    from auth_sessions import _require_authenticated_user
    from db import get_db
    from research_worker import run_queued_worker_requests, run_worker_request

router = APIRouter()


@router.post("/worker/requests/{request_id}/run")
def run_worker_request_endpoint(request_id: str, request: Request):
    with get_db() as conn:
        _require_authenticated_user(conn, request)
        return run_worker_request(conn, request_id)


@router.post("/worker/run-queued")
def run_queued_worker_requests_endpoint(
    request: Request,
    limit: int = Query(default=1, ge=1, le=10),
    request_type: str = "",
):
    with get_db() as conn:
        _require_authenticated_user(conn, request)
        return run_queued_worker_requests(conn, limit=limit, request_type=request_type or None)
