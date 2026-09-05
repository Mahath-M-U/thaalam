"""SQLite storage for accounts, sessions, audit trail, and login attempts.

Deliberately a different database from ``data/whoop.duckdb``. DuckDB allows a
single writer, and the API holds one process-wide writable connection, so
sharing that file would let a 90-day WHOOP backfill block logins. Keeping the
security tables in SQLite also means they can be backed up and rotated
separately from health data.

Schema is applied on every connect, matching the additive
``CREATE TABLE IF NOT EXISTS`` convention already used by ``thaalam.db``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from thaalam.config import get_settings

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_VIEWER)

#: How far back failed logins count toward a lockout.
LOGIN_WINDOW_MINUTES = 15

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        email                TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash        TEXT NOT NULL,
        role                 TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
        is_active            INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL,
        last_login_at        TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        token_hash   TEXT NOT NULL UNIQUE,
        csrf_token   TEXT NOT NULL,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at   TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        expires_at   TEXT NOT NULL,
        revoked_at   TEXT,
        client_ip    TEXT,
        user_agent   TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at  TEXT NOT NULL,
        event       TEXT NOT NULL,
        user_id     INTEGER,
        actor_email TEXT,
        client_ip   TEXT,
        request_id  TEXT,
        detail      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS login_attempts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        email      TEXT,
        client_ip  TEXT,
        succeeded  INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_login_attempts_created ON login_attempts(created_at DESC)",
)


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def to_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def resolve_db_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else get_settings().resolved_auth_db_path


def apply_schema(con: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        con.execute(statement)
    con.commit()


@contextmanager
def connect(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open the auth database with the schema applied.

    A fresh connection per operation rather than a shared one: WAL mode makes
    that cheap, and it keeps request threads from serialising on a global lock.
    """
    resolved = resolve_db_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(resolved, timeout=10.0)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=10000")
        apply_schema(con)
        yield con
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def normalise_email(email: str) -> str:
    return email.strip().lower()


def create_user(
    con: sqlite3.Connection,
    *,
    email: str,
    password_hash: str,
    role: str,
    must_change_password: bool = False,
) -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    now = to_iso(utcnow())
    cursor = con.execute(
        """
        INSERT INTO users (email, password_hash, role, is_active,
                           must_change_password, created_at, updated_at)
        VALUES (?, ?, ?, 1, ?, ?, ?)
        """,
        (normalise_email(email), password_hash, role, int(must_change_password), now, now),
    )
    con.commit()
    return int(cursor.lastrowid)


def get_user_by_email(con: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM users WHERE email = ?", (normalise_email(email),)
    ).fetchone()


def get_user(con: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def list_users(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM users ORDER BY created_at").fetchall()


def count_users(con: sqlite3.Connection) -> int:
    return int(con.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def count_active_admins(con: sqlite3.Connection, *, excluding: int | None = None) -> int:
    sql = "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
    params: list[Any] = []
    if excluding is not None:
        sql += " AND id != ?"
        params.append(excluding)
    return int(con.execute(sql, params).fetchone()[0])


def update_user(con: sqlite3.Connection, user_id: int, **fields: Any) -> None:
    allowed = {
        "password_hash",
        "role",
        "is_active",
        "must_change_password",
        "last_login_at",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"cannot update {sorted(unknown)}")
    if not fields:
        return
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = [*fields.values(), to_iso(utcnow()), user_id]
    con.execute(f"UPDATE users SET {assignments}, updated_at = ? WHERE id = ?", values)
    con.commit()


def record_login(con: sqlite3.Connection, user_id: int) -> None:
    con.execute(
        "UPDATE users SET last_login_at = ? WHERE id = ?", (to_iso(utcnow()), user_id)
    )
    con.commit()


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def record_audit(
    con: sqlite3.Connection,
    event: str,
    *,
    user_id: int | None = None,
    actor_email: str | None = None,
    client_ip: str | None = None,
    request_id: str | None = None,
    detail: str | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO audit_log (created_at, event, user_id, actor_email,
                               client_ip, request_id, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            to_iso(utcnow()),
            event,
            user_id,
            actor_email,
            client_ip,
            request_id,
            detail,
        ),
    )
    con.commit()


def list_audit(
    con: sqlite3.Connection,
    *,
    limit: int = 50,
    offset: int = 0,
    event: str | None = None,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM audit_log"
    params: list[Any] = []
    if event:
        sql += " WHERE event = ?"
        params.append(event)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return con.execute(sql, params).fetchall()


def count_audit(con: sqlite3.Connection, *, event: str | None = None) -> int:
    sql = "SELECT COUNT(*) FROM audit_log"
    params: list[Any] = []
    if event:
        sql += " WHERE event = ?"
        params.append(event)
    return int(con.execute(sql, params).fetchone()[0])


# ---------------------------------------------------------------------------
# Login attempts / throttling
# ---------------------------------------------------------------------------


def record_login_attempt(
    con: sqlite3.Connection,
    *,
    email: str | None,
    client_ip: str | None,
    succeeded: bool,
) -> None:
    con.execute(
        "INSERT INTO login_attempts (created_at, email, client_ip, succeeded) VALUES (?, ?, ?, ?)",
        (
            to_iso(utcnow()),
            normalise_email(email) if email else None,
            client_ip,
            int(succeeded),
        ),
    )
    con.commit()


def recent_failures(
    con: sqlite3.Connection,
    *,
    email: str | None = None,
    client_ip: str | None = None,
    window_minutes: int = LOGIN_WINDOW_MINUTES,
) -> int:
    """Failed logins in the window, counted since the last success.

    Counting since the last success means a legitimate login clears the slate,
    so a user who mistypes twice a day never drifts into a lockout.
    """
    since = to_iso(utcnow() - timedelta(minutes=window_minutes))
    sql = "SELECT created_at, succeeded FROM login_attempts WHERE created_at >= ?"
    params: list[Any] = [since]
    if email is not None:
        sql += " AND email = ?"
        params.append(normalise_email(email))
    if client_ip is not None:
        sql += " AND client_ip = ?"
        params.append(client_ip)
    sql += " ORDER BY id DESC"

    failures = 0
    for row in con.execute(sql, params):
        if row["succeeded"]:
            break
        failures += 1
    return failures


def purge_login_attempts(con: sqlite3.Connection, *, older_than_minutes: int = 1440) -> None:
    cutoff = to_iso(utcnow() - timedelta(minutes=older_than_minutes))
    con.execute("DELETE FROM login_attempts WHERE created_at < ?", (cutoff,))
    con.commit()
