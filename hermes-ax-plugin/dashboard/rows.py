from __future__ import annotations

import sqlite3


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows: list) -> list[dict]:
    return [dict(r) for r in rows]
