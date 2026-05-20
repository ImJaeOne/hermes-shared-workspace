from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

try:
    from .auth import get_bootstrap_admin_config, hash_password
except ImportError:
    from auth import get_bootstrap_admin_config, hash_password


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _upsert_bootstrap_admin(conn: sqlite3.Connection):
    config = get_bootstrap_admin_config()
    if not config:
        return

    now = _now()
    password_hash = hash_password(config["password"])
    existing = conn.execute(
        "SELECT id FROM users WHERE username=?",
        (config["username"],),
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE users
               SET display_name=?, password_hash=?, role='admin', is_active=1, updated_at=?
               WHERE id=?""",
            (config["display_name"], password_hash, now, existing["id"]),
        )
        return

    conn.execute(
        """INSERT INTO users
           (id, username, display_name, password_hash, role, is_active, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            _uuid("usr_"),
            config["username"],
            config["display_name"],
            password_hash,
            "admin",
            1,
            now,
            now,
        ),
    )
