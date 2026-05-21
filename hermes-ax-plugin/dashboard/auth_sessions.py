"""Auth session helpers shared across dashboard routes."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request

try:
    from .auth import AUTH_SESSION_TTL_SECONDS, AX_SESSION_COOKIE, hash_session_token, parse_timestamp
    from .common import _now, _uuid
except ImportError:
    from auth import AUTH_SESSION_TTL_SECONDS, AX_SESSION_COOKIE, hash_session_token, parse_timestamp
    from common import _now, _uuid


def _get_request_session_token(request: Request) -> str:
    header_token = request.headers.get("X-Hermes-Session-Token", "").strip()
    if header_token:
        return header_token
    return request.cookies.get(AX_SESSION_COOKIE, "").strip()



def _get_authenticated_session(conn: sqlite3.Connection, token: str) -> dict[str, Any] | None:
    if not token:
        return None

    row = conn.execute(
        """SELECT
               s.id,
               s.user_id,
               s.expires_at,
               s.created_at,
               s.last_seen_at,
               u.username,
               u.display_name,
               u.role,
               u.is_active,
               u.created_at AS user_created_at,
               u.updated_at AS user_updated_at
           FROM auth_sessions s
           JOIN users u ON u.id = s.user_id
           WHERE s.session_token_hash=?""",
        (hash_session_token(token),),
    ).fetchone()
    if not row:
        return None

    if not row["is_active"]:
        conn.execute("DELETE FROM auth_sessions WHERE id=?", (row["id"],))
        return None

    if parse_timestamp(row["expires_at"]) <= datetime.now(timezone.utc):
        conn.execute("DELETE FROM auth_sessions WHERE id=?", (row["id"],))
        return None

    last_seen_at = _now()
    conn.execute("UPDATE auth_sessions SET last_seen_at=? WHERE id=?", (last_seen_at, row["id"]))
    return {
        "session": {
            "id": row["id"],
            "user_id": row["user_id"],
            "expires_at": row["expires_at"],
            "created_at": row["created_at"],
            "last_seen_at": last_seen_at,
        },
        "user": {
            "id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "created_at": row["user_created_at"],
            "updated_at": row["user_updated_at"],
        },
    }



def _require_authenticated_user(conn: sqlite3.Connection, request: Request) -> dict[str, Any]:
    token = _get_request_session_token(request)
    auth = _get_authenticated_session(conn, token)
    if not auth:
        raise HTTPException(401, "Authentication required")
    return auth["user"]



def _create_auth_session(conn: sqlite3.Connection, user_id: str) -> dict[str, str]:
    now_dt = datetime.now(timezone.utc)
    expires_dt = now_dt + timedelta(seconds=AUTH_SESSION_TTL_SECONDS)
    session_token = secrets.token_urlsafe(32)
    session_id = _uuid("axs_")
    now = now_dt.isoformat()
    expires_at = expires_dt.isoformat()
    conn.execute(
        """INSERT INTO auth_sessions
           (id, user_id, session_token_hash, expires_at, created_at, last_seen_at)
           VALUES (?,?,?,?,?,?)""",
        (session_id, user_id, hash_session_token(session_token), expires_at, now, now),
    )
    return {
        "id": session_id,
        "token": session_token,
        "expires_at": expires_at,
        "created_at": now,
        "last_seen_at": now,
    }
