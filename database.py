"""SQLite connection and schema helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS teachers (
    teacher_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    department TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    roll_number TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    semester INTEGER,
    department TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    session_token TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL,
    subject_code TEXT NOT NULL,
    classroom_lat REAL NOT NULL,
    classroom_lon REAL NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_token TEXT NOT NULL,
    student_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    client_ip TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    accuracy REAL,
    device_fingerprint TEXT,
    is_flagged INTEGER NOT NULL DEFAULT 0 CHECK(is_flagged IN (0, 1)),
    flag_reason TEXT,
    FOREIGN KEY (session_token) REFERENCES sessions(session_token) ON DELETE RESTRICT,
    FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE RESTRICT,
    UNIQUE(session_token, student_id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    session_token TEXT,
    student_id TEXT,
    client_ip TEXT,
    details TEXT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_token) REFERENCES sessions(session_token) ON DELETE SET NULL,
    FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_teacher_created ON sessions(teacher_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_student_time ON attendance(student_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance(session_token);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_logs(session_token, timestamp DESC);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path, timeout=10, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 10000")
    return g.db


def close_db(_error=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    get_db().executescript(SCHEMA)


def log_event(event_type: str, *, session_token=None, student_id=None, client_ip=None, details="{}") -> None:
    get_db().execute(
        """INSERT INTO audit_logs (event_type, session_token, student_id, client_ip, details)
           VALUES (?, ?, ?, ?, ?)""",
        (event_type, session_token, student_id, client_ip, details),
    )
