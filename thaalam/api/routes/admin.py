"""Administrator surface: accounts, sessions, audit trail, and system health.

Every route here is admin-only via the router dependency, so a route added
later is guarded by default.
"""

from __future__ import annotations

import logging
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field

from thaalam.api.scheduler import scheduler_state
from thaalam.api.deps import (
    DB_PATH,
    client_ip,
    get_auth_db,
    is_whoop_connected,
    require_admin,
)
from thaalam.auth import passwords
from thaalam.auth import sessions as session_store
from thaalam.auth import store as auth_store
from thaalam.auth.sessions import AuthenticatedUser
from thaalam.auth.store import ROLES
from thaalam.config import get_settings
from thaalam.logging_config import request_id_var

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class UserRow(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    must_change_password: bool
    created_at: str
    last_login_at: str | None = None


class CreateUserRequest(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|viewer)$")


class UpdateUserRequest(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|viewer)$")
    is_active: bool | None = None


class CreatedUserResponse(BaseModel):
    user: UserRow
    temporary_password: str


def _to_row(row: sqlite3.Row) -> UserRow:
    return UserRow(
        id=row["id"],
        email=row["email"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        must_change_password=bool(row["must_change_password"]),
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


def _audit(
    con: sqlite3.Connection,
    request: Request,
    actor: AuthenticatedUser,
    event: str,
    detail: str | None = None,
    *,
    user_id: int | None = None,
) -> None:
    auth_store.record_audit(
        con,
        event,
        user_id=user_id if user_id is not None else actor.id,
        actor_email=actor.email,
        client_ip=client_ip(request),
        request_id=request_id_var.get(),
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users", response_model=list[UserRow])
def list_users(con: sqlite3.Connection = Depends(get_auth_db)) -> list[UserRow]:
    return [_to_row(row) for row in auth_store.list_users(con)]


@router.post("/users", response_model=CreatedUserResponse, status_code=201)
def create_user(
    payload: CreateUserRequest,
    request: Request,
    actor: AuthenticatedUser = Depends(require_admin),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> CreatedUserResponse:
    """Invite an account with a generated password it must replace.

    The administrator never chooses another person's password, so there is no
    moment where one account's credential is known to someone else beyond the
    single handover.
    """
    if auth_store.get_user_by_email(con, payload.email) is not None:
        raise HTTPException(status_code=409, detail="An account with that email exists")

    temporary = secrets.token_urlsafe(18)
    user_id = auth_store.create_user(
        con,
        email=payload.email,
        password_hash=passwords.hash_password(temporary),
        role=payload.role,
        must_change_password=True,
    )
    _audit(con, request, actor, "user.created", f"role={payload.role}", user_id=user_id)
    logger.info("Account created", extra={"user": actor.email})

    row = auth_store.get_user(con, user_id)
    return CreatedUserResponse(user=_to_row(row), temporary_password=temporary)


@router.patch("/users/{user_id}", response_model=UserRow)
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    request: Request,
    actor: AuthenticatedUser = Depends(require_admin),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> UserRow:
    row = auth_store.get_user(con, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such account")

    losing_admin = (payload.role is not None and payload.role != "admin") or (
        payload.is_active is False
    )
    if (
        losing_admin
        and row["role"] == "admin"
        and auth_store.count_active_admins(con, excluding=user_id) == 0
    ):
        # Otherwise the deployment locks itself out and only a shell can fix it.
        raise HTTPException(
            status_code=409,
            detail="This is the last active administrator; promote another first",
        )

    fields: dict[str, Any] = {}
    if payload.role is not None and payload.role in ROLES:
        fields["role"] = payload.role
    if payload.is_active is not None:
        fields["is_active"] = int(payload.is_active)

    if fields:
        auth_store.update_user(con, user_id, **fields)
        if payload.is_active is False:
            # Disabling must take effect now, not when the session lapses.
            session_store.revoke_user_sessions(con, user_id)
        _audit(
            con,
            request,
            actor,
            "user.updated",
            ", ".join(f"{k}={v}" for k, v in fields.items()),
            user_id=user_id,
        )

    return _to_row(auth_store.get_user(con, user_id))


@router.post("/users/{user_id}/reset-password", response_model=CreatedUserResponse)
def reset_password(
    user_id: int,
    request: Request,
    actor: AuthenticatedUser = Depends(require_admin),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> CreatedUserResponse:
    row = auth_store.get_user(con, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such account")

    temporary = secrets.token_urlsafe(18)
    auth_store.update_user(
        con,
        user_id,
        password_hash=passwords.hash_password(temporary),
        must_change_password=1,
    )
    # A reset is also the response to a suspected compromise.
    session_store.revoke_user_sessions(con, user_id)
    _audit(con, request, actor, "user.password_reset", user_id=user_id)

    return CreatedUserResponse(
        user=_to_row(auth_store.get_user(con, user_id)), temporary_password=temporary
    )


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


class CreateInviteRequest(BaseModel):
    role: str = Field(pattern="^(admin|viewer)$")
    email: EmailStr | None = None


@router.get("/invites")
def list_invites(con: sqlite3.Connection = Depends(get_auth_db)) -> list[dict[str, Any]]:
    """Invite metadata only -- the token itself is shown once, at creation."""
    return [dict(row) for row in auth_store.list_invites(con)]


@router.post("/invites", status_code=201)
def create_invite(
    payload: CreateInviteRequest,
    request: Request,
    actor: AuthenticatedUser = Depends(require_admin),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> dict[str, Any]:
    """Mint a single-use invite link.

    Only the token's hash is stored, so this response is the one and only
    time the token exists in readable form.
    """
    invite_id, token = auth_store.create_invite(
        con,
        role=payload.role,
        created_by=actor.id,
        email=payload.email,
    )
    _audit(
        con,
        request,
        actor,
        "invite.created",
        f"role={payload.role}{f', email={payload.email}' if payload.email else ''}",
    )
    return {
        "id": invite_id,
        "token": token,
        "role": payload.role,
        "email": payload.email,
        "expires_in_hours": auth_store.INVITE_TTL_HOURS,
    }


@router.delete("/invites/{invite_id}", status_code=204)
def revoke_invite(
    invite_id: int,
    request: Request,
    actor: AuthenticatedUser = Depends(require_admin),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> None:
    auth_store.revoke_invite(con, invite_id)
    _audit(con, request, actor, "invite.revoked", f"invite_id={invite_id}")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.get("/sessions")
def list_sessions(con: sqlite3.Connection = Depends(get_auth_db)) -> list[dict[str, Any]]:
    return [dict(row) for row in session_store.list_active_sessions(con)]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: int,
    request: Request,
    actor: AuthenticatedUser = Depends(require_admin),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> None:
    session_store.revoke_session_by_id(con, session_id)
    _audit(con, request, actor, "session.revoked", f"session_id={session_id}")


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


@router.get("/audit")
def list_audit(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event: str | None = Query(default=None),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> dict[str, Any]:
    return {
        "total": auth_store.count_audit(con, event=event),
        "entries": [
            dict(row) for row in auth_store.list_audit(con, limit=limit, offset=offset, event=event)
        ],
    }


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _last_recompute() -> dict[str, Any] | None:
    """Most recent derived recompute, or None if there is nothing to read."""
    from thaalam.api.deps import get_readonly_connection

    generator = get_readonly_connection()
    try:
        con = next(generator)
    except (StopIteration, Exception):
        return None
    try:
        row = con.execute(
            "SELECT trigger, created_at FROM derived_recompute_log "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {"trigger": row[0], "at": str(row[1])}
    except Exception:
        return None
    finally:
        generator.close()


@router.get("/system")
def system_health(con: sqlite3.Connection = Depends(get_auth_db)) -> dict[str, Any]:
    settings = get_settings()
    auth_path = settings.resolved_auth_db_path
    data_path = Path(DB_PATH)

    return {
        "environment": settings.app_env,
        "whoop_connected": is_whoop_connected(),
        "secure_cookies": settings.secure_cookies,
        "session_ttl_minutes": settings.session_ttl_minutes,
        "database": {
            "path": data_path.name,
            "exists": data_path.exists(),
            "size_bytes": _file_size(data_path),
        },
        "auth_database": {
            "path": auth_path.name,
            "size_bytes": _file_size(auth_path),
        },
        "accounts": {
            "total": auth_store.count_users(con),
            "active_admins": auth_store.count_active_admins(con),
            "active_sessions": len(session_store.list_active_sessions(con)),
        },
        "last_recompute": _last_recompute(),
        "nightly_job": {
            "enabled": settings.nightly_job_enabled,
            "hour": settings.nightly_job_hour,
            **scheduler_state(),
        },
    }
