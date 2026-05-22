"""Authentication routes extracted from plugin_api."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

try:
    from .activity import _record_user_activity
    from .auth import (
        AX_SESSION_COOKIE,
        hash_session_token,
    )
    from .auth_sessions import (
        _get_authenticated_session,
        _get_parent_dashboard_token,
        _get_request_session_token,
        _upsert_parent_dashboard_user,
    )
    from .db import get_db
except ImportError:
    from activity import _record_user_activity
    from auth import (
        AX_SESSION_COOKIE,
        hash_session_token,
    )
    from auth_sessions import (
        _get_authenticated_session,
        _get_parent_dashboard_token,
        _get_request_session_token,
        _upsert_parent_dashboard_user,
    )
    from db import get_db

router = APIRouter()


@router.post("/auth/login")
def login():
    raise HTTPException(410, "AX login is disabled; use Hermes dashboard authentication")


@router.get("/auth/session")
def get_auth_session(request: Request, response: Response):
    if _get_parent_dashboard_token(request):
        with get_db() as conn:
            user = _upsert_parent_dashboard_user(conn)
        return {"authenticated": True, "user": user, "expires_at": None}

    response.delete_cookie(key=AX_SESSION_COOKIE, path="/")
    return {"authenticated": False, "user": None, "expires_at": None}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = _get_request_session_token(request)
    with get_db() as conn:
        auth = _get_authenticated_session(conn, token) if token else None
        if token:
            conn.execute(
                "DELETE FROM auth_sessions WHERE session_token_hash=?",
                (hash_session_token(token),),
            )
        if auth:
            _record_user_activity(
                conn,
                user=auth["user"],
                action="auth.logout",
                target_type="session",
                target_id=auth["session"]["id"],
                metadata={"username": auth["user"]["username"]},
            )

    response.delete_cookie(key=AX_SESSION_COOKIE, path="/")
    return {"ok": True}
