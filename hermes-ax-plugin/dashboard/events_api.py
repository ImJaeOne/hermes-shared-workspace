"""Event polling routes extracted from plugin_api."""

from __future__ import annotations

from fastapi import APIRouter, Query

try:
    from .db import get_db
    from .rows import rows_to_list
except ImportError:
    from db import get_db
    from rows import rows_to_list

router = APIRouter()


@router.get("/events")
def get_events(since: int = Query(0), limit: int = Query(200)):
    with get_db() as conn:
        events = rows_to_list(
            conn.execute(
                "SELECT * FROM ax_events WHERE id > ? ORDER BY id LIMIT ?", (since, limit)
            ).fetchall()
        )
        cursor = events[-1]["id"] if events else since

    return {"events": events, "cursor": cursor}
