"""SQLite persistence for app state — single-row JSON blob."""

import json, os, sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'call_scheduler.db')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);
INSERT OR IGNORE INTO app_state (id, data) VALUES (1, '{}');
"""


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_conn()
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def load_state() -> dict:
    conn = _get_conn()
    row = conn.execute("SELECT data FROM app_state WHERE id = 1").fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return {}


def save_state(data: dict) -> None:
    conn = _get_conn()
    conn.execute("UPDATE app_state SET data = ? WHERE id = 1", (json.dumps(data),))
    conn.commit()
    conn.close()
