"""Server-side sessions.

The cookie carries an opaque 256-bit random token. Only its SHA-256 is stored,
so a database leak yields nothing usable -- and because the token is already
high-entropy random, a plain digest is the right primitive here; a slow KDF
would only add per-request cost against an input that cannot be guessed.

Each session also carries a CSRF token. It is handed to the client in a
readable cookie and must come back as a header on unsafe requests
(double-submit), which a cross-site caller cannot do.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from thaalam.auth.store import from_iso, to_iso, utcnow

SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 32

#: HttpOnly -- the session token must stay out of reach of page scripts.
SESSION_COOKIE = "thaalam_session"
#: Readable by the frontend on purpose: it has to echo this back as a header.
CSRF_COOKIE = "thaalam_csrf"
CSRF_HEADER = "X-CSRF-Token"

#: Methods that cannot change state, and so need no CSRF token.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

#: Skip the sliding-expiry write unless the session has gone this long without
#: one, so a dashboard firing ten parallel reads doesn't write ten times.
RENEW_AFTER_SECONDS = 60


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    email: str
    role: str
    must_change_password: bool
    session_id: int
    csrf_token: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(
    con: sqlite3.Connection,
    *,
    user_id: int,
    ttl_minutes: int,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str]:
    """Create a session; returns the (session token, CSRF token) pair.

    The session token is returned to the caller and never stored in the clear.
    """
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
    now = utcnow()
    con.execute(
        """
        INSERT INTO sessions (token_hash, csrf_token, user_id, created_at,
                              last_seen_at, expires_at, client_ip, user_agent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            hash_token(token),
            csrf_token,
            user_id,
            to_iso(now),
            to_iso(now),
            to_iso(now + timedelta(minutes=ttl_minutes)),
            client_ip,
            user_agent,
        ),
    )
    con.commit()
    return token, csrf_token


def lookup_session(
    con: sqlite3.Connection, token: str, *, ttl_minutes: int
) -> AuthenticatedUser | None:
    """Resolve a session token, or None if it is unusable for any reason.

    Unusable covers: unknown, revoked, expired, or belonging to an account
    that has since been disabled -- so disabling an account takes effect on
    that account's next request rather than when its session happens to lapse.
    """
    if not token:
        return None

    row = con.execute(
        """
        SELECT s.id            AS session_id,
               s.expires_at    AS expires_at,
               s.revoked_at    AS revoked_at,
               s.last_seen_at  AS last_seen_at,
               s.csrf_token    AS csrf_token,
               u.id            AS user_id,
               u.email         AS email,
               u.role          AS role,
               u.is_active     AS is_active,
               u.must_change_password AS must_change_password
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ?
        """,
        (hash_token(token),),
    ).fetchone()

    if row is None or row["revoked_at"] is not None or not row["is_active"]:
        return None

    now = utcnow()
    if from_iso(row["expires_at"]) <= now:
        return None

    if (now - from_iso(row["last_seen_at"])).total_seconds() >= RENEW_AFTER_SECONDS:
        con.execute(
            "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
            (
                to_iso(now),
                to_iso(now + timedelta(minutes=ttl_minutes)),
                row["session_id"],
            ),
        )
        con.commit()

    return AuthenticatedUser(
        id=row["user_id"],
        email=row["email"],
        role=row["role"],
        must_change_password=bool(row["must_change_password"]),
        session_id=row["session_id"],
        csrf_token=row["csrf_token"],
    )


def revoke_session(con: sqlite3.Connection, token: str) -> None:
    con.execute(
        "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
        (to_iso(utcnow()), hash_token(token)),
    )
    con.commit()


def revoke_session_by_id(con: sqlite3.Connection, session_id: int) -> None:
    con.execute(
        "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (to_iso(utcnow()), session_id),
    )
    con.commit()


def revoke_user_sessions(
    con: sqlite3.Connection, user_id: int, *, except_session_id: int | None = None
) -> int:
    """Revoke every live session for a user; returns how many were revoked."""
    sql = "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL"
    params: list[object] = [to_iso(utcnow()), user_id]
    if except_session_id is not None:
        sql += " AND id != ?"
        params.append(except_session_id)
    cursor = con.execute(sql, params)
    con.commit()
    return cursor.rowcount


def list_active_sessions(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT s.id, s.user_id, s.created_at, s.last_seen_at, s.expires_at,
               s.client_ip, s.user_agent, u.email, u.role
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.revoked_at IS NULL AND s.expires_at > ?
        ORDER BY s.last_seen_at DESC
        """,
        (to_iso(utcnow()),),
    ).fetchall()


def purge_expired(con: sqlite3.Connection) -> int:
    cursor = con.execute("DELETE FROM sessions WHERE expires_at < ?", (to_iso(utcnow()),))
    con.commit()
    return cursor.rowcount
