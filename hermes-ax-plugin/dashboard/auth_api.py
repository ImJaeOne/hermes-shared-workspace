"""Authentication routes extracted from plugin_api."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

try:
    from .activity import _record_user_activity
    from .auth import (
        AUTH_SESSION_TTL_SECONDS,
        AX_SESSION_COOKIE,
        AX_SESSION_COOKIE_SECURE_ENV,
        env_flag,
        hash_session_token,
        normalize_username,
        serialize_user,
        verify_password,
    )
    from .auth_sessions import (
        _create_auth_session,
        _get_authenticated_session,
        _get_request_session_token,
    )
    from .db import get_db
    from .schemas import LoginBody
except ImportError:
    from activity import _record_user_activity
    from auth import (
        AUTH_SESSION_TTL_SECONDS,
        AX_SESSION_COOKIE,
        AX_SESSION_COOKIE_SECURE_ENV,
        env_flag,
        hash_session_token,
        normalize_username,
        serialize_user,
        verify_password,
    )
    from auth_sessions import (
        _create_auth_session,
        _get_authenticated_session,
        _get_request_session_token,
    )
    from db import get_db
    from schemas import LoginBody

router = APIRouter()


@router.post("/auth/login")
def login(body: LoginBody, response: Response):
    username = normalize_username(body.username)
    password = body.password.strip()
    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
            raise HTTPException(401, "Invalid username or password")

        session = _create_auth_session(conn, user["id"])
        _record_user_activity(
            conn,
            user=user,
            action="auth.login",
            target_type="session",
            target_id=session["id"],
            metadata={"username": user["username"]},
        )

    response.set_cookie(
        key=AX_SESSION_COOKIE,
        value=session["token"],
        httponly=True,
        samesite="lax",
        secure=env_flag(AX_SESSION_COOKIE_SECURE_ENV, default=False),
        max_age=AUTH_SESSION_TTL_SECONDS,
        path="/",
    )
    return {
        "ok": True,
        "token": session["token"],
        "expires_at": session["expires_at"],
        "user": serialize_user(user),
    }


@router.get("/auth/session")
def get_auth_session(request: Request, response: Response):
    token = _get_request_session_token(request)
    with get_db() as conn:
        auth = _get_authenticated_session(conn, token)

    if not auth:
        response.delete_cookie(key=AX_SESSION_COOKIE, path="/")
        return {"authenticated": False, "user": None, "expires_at": None}

    return {
        "authenticated": True,
        "user": auth["user"],
        "expires_at": auth["session"]["expires_at"],
    }


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
