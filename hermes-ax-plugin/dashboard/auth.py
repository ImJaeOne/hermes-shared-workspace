"""Authentication helpers for the Hermes AX dashboard API."""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime

BOOTSTRAP_ADMIN_USERNAME_ENV = "HERMES_AX_BOOTSTRAP_ADMIN_USERNAME"
BOOTSTRAP_ADMIN_PASSWORD_ENV = "HERMES_AX_BOOTSTRAP_ADMIN_PASSWORD"
BOOTSTRAP_ADMIN_DISPLAY_NAME_ENV = "HERMES_AX_BOOTSTRAP_ADMIN_DISPLAY_NAME"
AX_SESSION_COOKIE_SECURE_ENV = "HERMES_AX_SESSION_COOKIE_SECURE"
PASSWORD_HASH_ITERATIONS = 390_000
AX_SESSION_COOKIE = "hermes_ax_session"
AUTH_SESSION_TTL_SECONDS = 60 * 60 * 24 * 7


def normalize_username(username: str) -> str:
    return username.strip().lower()


def hash_password(password: str, *, salt: str | None = None, iterations: int = PASSWORD_HASH_ITERATIONS) -> str:
    normalized = password.strip()
    if not normalized:
        raise ValueError("Password must not be empty")
    password_salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        password_salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${password_salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, digest = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hash_password(password, salt=salt, iterations=int(iterations))
        return hmac.compare_digest(candidate, f"{algorithm}${iterations}${salt}${digest}")
    except ValueError:
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))


def serialize_user(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_bootstrap_admin_config() -> dict[str, str] | None:
    username = normalize_username(os.environ.get(BOOTSTRAP_ADMIN_USERNAME_ENV, ""))
    password = os.environ.get(BOOTSTRAP_ADMIN_PASSWORD_ENV, "").strip()
    display_name = os.environ.get(BOOTSTRAP_ADMIN_DISPLAY_NAME_ENV, "").strip()

    if not username and not password:
        return None
    if not username or not password:
        raise RuntimeError(
            f"{BOOTSTRAP_ADMIN_USERNAME_ENV} and {BOOTSTRAP_ADMIN_PASSWORD_ENV} must be set together"
        )

    return {
        "username": username,
        "password": password,
        "display_name": display_name or username,
    }
