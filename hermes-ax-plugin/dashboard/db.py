from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
PLUGIN_DATA_DIR = HERMES_HOME / "plugins" / "hermes-ax-plugin"
DB_DIR = PLUGIN_DATA_DIR
DB_PATH = DB_DIR / "ax.db"
ARTIFACTS_DIR = DB_DIR / "artifacts"


@contextmanager
def get_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
