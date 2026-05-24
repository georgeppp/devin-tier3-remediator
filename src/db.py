"""SQLite persistence for session run state."""
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DEVIN_DB_PATH", "data.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    issue_node_id TEXT PRIMARY KEY,
    issue_number INTEGER,
    issue_title TEXT,
    issue_type TEXT,
    repo TEXT,
    session_id TEXT,
    session_url TEXT,
    status TEXT,
    pr_url TEXT,
    pr_state TEXT,
    acu_consumed REAL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    last_polled_at TEXT,
    follow_ups_sent INTEGER DEFAULT 0,
    last_ci_signature TEXT
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.commit()
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
