"""SQLite data layer for ExecConnect."""
import os
import sqlite3

DB_PATH = os.environ.get("EXECCONNECT_DB", os.path.join(os.path.dirname(__file__), "execconnect.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT UNIQUE NOT NULL,          -- private, never sent to other users
    password_hash   TEXT NOT NULL,
    real_name       TEXT NOT NULL,                 -- private until both sides agree to reveal
    alias           TEXT NOT NULL,                 -- public pseudonym
    headline        TEXT DEFAULT '',
    bio             TEXT DEFAULT '',
    company         TEXT DEFAULT '',
    company_domain  TEXT DEFAULT '',
    linkedin_url    TEXT DEFAULT '',
    industry        TEXT DEFAULT '',
    seniority       TEXT DEFAULT '',
    function        TEXT DEFAULT '',
    country         TEXT DEFAULT '',
    city            TEXT DEFAULT '',
    hiring          INTEGER DEFAULT 0,
    investment_focus TEXT DEFAULT '',
    board_experience INTEGER DEFAULT 0,
    interests       TEXT DEFAULT '',               -- comma separated areas of interest
    email_verified  INTEGER DEFAULT 0,
    email_code      TEXT,
    linkedin_status TEXT DEFAULT 'none',           -- none | pending | verified
    company_verified INTEGER DEFAULT 0,
    totp_secret     TEXT,
    mfa_enabled     INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'active',         -- active | review | blocked
    risk_score      INTEGER DEFAULT 0,
    risk_category   TEXT DEFAULT 'ok',
    risk_reasons    TEXT DEFAULT '',
    is_premium      INTEGER DEFAULT 0,
    is_admin        INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS intents (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    intent  TEXT NOT NULL,
    PRIMARY KEY (user_id, intent)
);
CREATE TABLE IF NOT EXISTS connections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    requester   INTEGER NOT NULL REFERENCES users(id),
    recipient   INTEGER NOT NULL REFERENCES users(id),
    status      TEXT DEFAULT 'pending',            -- pending | accepted | declined
    score       REAL DEFAULT 0,
    reason      TEXT DEFAULT '',
    note        TEXT DEFAULT '',
    reveal_requester INTEGER DEFAULT 0,
    reveal_recipient INTEGER DEFAULT 0,
    room        TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (requester, recipient)
);
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    sender_id     INTEGER NOT NULL REFERENCES users(id),
    body          TEXT NOT NULL,
    flagged       INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ratings (
    rater           INTEGER NOT NULL REFERENCES users(id),
    ratee           INTEGER NOT NULL REFERENCES users(id),
    responsiveness  INTEGER NOT NULL,
    intro_quality   INTEGER NOT NULL,
    mentoring       INTEGER NOT NULL,
    events          INTEGER NOT NULL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (rater, ratee)
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    user_id    INTEGER,
    detail     TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def log_event(conn, kind, user_id=None, detail=""):
    conn.execute("INSERT INTO events(kind, user_id, detail) VALUES (?,?,?)", (kind, user_id, detail))
    conn.commit()
