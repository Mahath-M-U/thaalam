"""Login, logout, identity, and self-service password change.

Sessions live in a cookie, not a bearer token in JS-reachable storage: the
frontend is same-origin, and an HttpOnly cookie keeps the credential out of
reach of any script that manages to run on the page.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, EmailStr, Field

from thaalam.api.deps import client_ip, get_auth_db, get_current_user
from thaalam.auth import passwords
from thaalam.auth import sessions as session_store
from thaalam.auth import store as auth_store
from thaalam.auth.sessions import AuthenticatedUser
from thaalam.config import get_settings
from thaalam.logging_config import request_id_var

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: Deliberately identical for "no such account" and "wrong password".
_BAD_CREDENTIALS = "Incorrect email or password"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=passwords.MAX_PASSWORD_LENGTH)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=passwords.MAX_PASSWORD_LENGTH)
    invite_token: str | None = Field(default=None, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=passwords.MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=1, max_length=passwords.MAX_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    email: str
    role: str
    must_change_password: bool
    csrf_token: str


def _user_response(user: AuthenticatedUser) -> UserResponse:
    return UserResponse(
        email=user.email,
        role=user.role,
        must_change_password=user.must_change_password,
        csrf_token=user.csrf_token,
    )


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    settings = get_settings()
    max_age = settings.session_ttl_minutes * 60
    response.set_cookie(
        session_store.SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    # Not HttpOnly: the frontend has to read this to echo it back as a header.
    response.set_cookie(
        session_store.CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    for name in (session_store.SESSION_COOKIE, session_store.CSRF_COOKIE):
        response.delete_cookie(name, path="/")


@router.get("/registration")
def registration_status(
    invite: str | None = Query(default=None, max_length=256),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> dict[str, Any]:
    """What, if anything, /register will accept right now.

    Reveals only whether the instance has been set up yet and whether a given
    token is redeemable -- never who holds accounts, and never a token.
    """
    first_run = auth_store.count_users(con) == 0
    return {
        "first_run": first_run,
        "invite_required": not first_run,
        "invite_valid": bool(invite) and auth_store.get_usable_invite(con, invite) is not None,
    }


@router.post("/register", response_model=UserResponse, status_code=201)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    con: sqlite3.Connection = Depends(get_auth_db),
) -> UserResponse:
    """Create an account, in exactly two situations.

    Before any account exists, the first visitor claims the owner account --
    the window closes permanently once it is taken. After that, an unused
    invite from an administrator is required. There is no open signup: a
    viewer here reads the owner's health data, so anyone who could register
    freely could read it.
    """
    ip = client_ip(request)
    settings = get_settings()
    first_run = auth_store.count_users(con) == 0

    invite = None
    if first_run:
        role = auth_store.ROLE_ADMIN
    else:
        invite = auth_store.get_usable_invite(con, payload.invite_token or "")
        if invite is None:
            auth_store.record_audit(
                con,
                "register.rejected",
                actor_email=payload.email,
                client_ip=ip,
                request_id=request_id_var.get(),
                detail="missing, spent, revoked or expired invite",
            )
            logger.warning("Registration refused: no usable invite", extra={"client_ip": ip})
            raise HTTPException(
                status_code=403, detail="Registration is by invitation only"
            )
        if invite["email"] and invite["email"] != auth_store.normalise_email(payload.email):
            raise HTTPException(
                status_code=403, detail="This invitation is for a different email address"
            )
        role = invite["role"]

    if auth_store.get_user_by_email(con, payload.email) is not None:
        raise HTTPException(status_code=409, detail="An account with that email exists")

    try:
        password_hash = passwords.hash_password(payload.password)
    except passwords.WeakPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # They chose this password themselves, so there is nothing to rotate.
    user_id = auth_store.create_user(
        con,
        email=payload.email,
        password_hash=password_hash,
        role=role,
        must_change_password=False,
    )
    if invite is not None:
        auth_store.accept_invite(con, invite["id"], user_id)

    auth_store.record_audit(
        con,
        "register.succeeded",
        user_id=user_id,
        actor_email=payload.email,
        client_ip=ip,
        request_id=request_id_var.get(),
        detail=f"role={role}, {'first run' if first_run else 'invited'}",
    )
    logger.info(
        "Account registered (%s)", "first run" if first_run else "invited",
        extra={"user": payload.email, "client_ip": ip},
    )

    token, csrf_token = session_store.create_session(
        con,
        user_id=user_id,
        ttl_minutes=settings.session_ttl_minutes,
        client_ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    auth_store.record_login(con, user_id)
    _set_session_cookies(response, token, csrf_token)

    return UserResponse(
        email=auth_store.normalise_email(payload.email),
        role=role,
        must_change_password=False,
        csrf_token=csrf_token,
    )


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    con: sqlite3.Connection = Depends(get_auth_db),
) -> UserResponse:
    settings = get_settings()
    ip = client_ip(request)
    email = payload.email

    # Throttle on the account and on the source address independently, so
    # neither spraying one password across accounts nor hammering one account
    # from many requests gets a free pass.
    for scope in ({"email": email}, {"client_ip": ip} if ip else None):
        if scope is None:
            continue
        if auth_store.recent_failures(con, **scope) >= settings.login_max_attempts:
            auth_store.record_audit(
                con,
                "login.throttled",
                actor_email=email,
                client_ip=ip,
                request_id=request_id_var.get(),
            )
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. Try again later.",
                headers={"Retry-After": str(auth_store.LOGIN_WINDOW_MINUTES * 60)},
            )

    user_row = auth_store.get_user_by_email(con, email)

    if user_row is None:
        # Spend the same CPU a real verification would, so a missing account
        # is not distinguishable by response time.
        passwords.waste_time()
        _record_failure(con, email, ip, "login.failed.unknown_account")
        raise HTTPException(status_code=401, detail=_BAD_CREDENTIALS)

    if not passwords.verify_password(user_row["password_hash"], payload.password):
        _record_failure(con, email, ip, "login.failed.bad_password", user_id=user_row["id"])
        raise HTTPException(status_code=401, detail=_BAD_CREDENTIALS)

    if not user_row["is_active"]:
        _record_failure(con, email, ip, "login.failed.disabled", user_id=user_row["id"])
        # Same message as a bad password: whether an account exists but is
        # disabled is not something an unauthenticated caller should learn.
        raise HTTPException(status_code=401, detail=_BAD_CREDENTIALS)

    if passwords.needs_rehash(user_row["password_hash"]):
        auth_store.update_user(
            con,
            user_row["id"],
            password_hash=passwords.hash_password(payload.password),
        )

    token, csrf_token = session_store.create_session(
        con,
        user_id=user_row["id"],
        ttl_minutes=settings.session_ttl_minutes,
        client_ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    auth_store.record_login(con, user_row["id"])
    auth_store.record_login_attempt(con, email=email, client_ip=ip, succeeded=True)
    auth_store.record_audit(
        con,
        "login.succeeded",
        user_id=user_row["id"],
        actor_email=user_row["email"],
        client_ip=ip,
        request_id=request_id_var.get(),
    )
    logger.info("Login succeeded", extra={"user": user_row["email"], "client_ip": ip})

    _set_session_cookies(response, token, csrf_token)
    return UserResponse(
        email=user_row["email"],
        role=user_row["role"],
        must_change_password=bool(user_row["must_change_password"]),
        csrf_token=csrf_token,
    )


def _record_failure(
    con: sqlite3.Connection,
    email: str,
    ip: str | None,
    event: str,
    *,
    user_id: int | None = None,
) -> None:
    auth_store.record_login_attempt(con, email=email, client_ip=ip, succeeded=False)
    auth_store.record_audit(
        con,
        event,
        user_id=user_id,
        actor_email=email,
        client_ip=ip,
        request_id=request_id_var.get(),
    )
    logger.warning("Login failed (%s)", event, extra={"client_ip": ip})


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    con: sqlite3.Connection = Depends(get_auth_db),
) -> Response:
    """Drop the current session.

    Deliberately succeeds whether or not a valid session was presented, so a
    client can always return itself to a known signed-out state.
    """
    token = request.cookies.get(session_store.SESSION_COOKIE, "")
    if token:
        user = session_store.lookup_session(
            con, token, ttl_minutes=get_settings().session_ttl_minutes
        )
        session_store.revoke_session(con, token)
        if user is not None:
            auth_store.record_audit(
                con,
                "logout",
                user_id=user.id,
                actor_email=user.email,
                client_ip=client_ip(request),
                request_id=request_id_var.get(),
            )
    _clear_session_cookies(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=UserResponse)
def me(user: AuthenticatedUser = Depends(get_current_user)) -> UserResponse:
    return _user_response(user)


@router.post("/password", response_model=UserResponse)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    con: sqlite3.Connection = Depends(get_auth_db),
) -> UserResponse:
    row = auth_store.get_user(con, user.id)
    if row is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not passwords.verify_password(row["password_hash"], payload.current_password):
        auth_store.record_audit(
            con,
            "password.change_failed",
            user_id=user.id,
            actor_email=user.email,
            client_ip=client_ip(request),
            request_id=request_id_var.get(),
        )
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=400, detail="New password must differ from the current one"
        )

    try:
        new_hash = passwords.hash_password(payload.new_password)
    except passwords.WeakPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    auth_store.update_user(
        con, user.id, password_hash=new_hash, must_change_password=0
    )

    # A password change is also how a user reacts to a suspected compromise,
    # so every other session for this account goes with it.
    revoked = session_store.revoke_user_sessions(
        con, user.id, except_session_id=user.session_id
    )
    auth_store.record_audit(
        con,
        "password.changed",
        user_id=user.id,
        actor_email=user.email,
        client_ip=client_ip(request),
        request_id=request_id_var.get(),
        detail=f"revoked {revoked} other session(s)",
    )
    logger.info("Password changed", extra={"user": user.email})

    return UserResponse(
        email=user.email,
        role=user.role,
        must_change_password=False,
        csrf_token=user.csrf_token,
    )
