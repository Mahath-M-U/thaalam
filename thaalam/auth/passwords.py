"""Password hashing.

Argon2id via argon2-cffi, at the library's current defaults. Hashes carry
their own salt and parameters, so a later parameter change is picked up by
:func:`needs_rehash` and applied transparently on the next successful login.
"""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: Long enough to resist offline guessing of a hash that leaked with the
#: database; the app is invite-only, so this trades no signup conversion.
MIN_PASSWORD_LENGTH = 12

#: Argon2 hashes its input, but an unbounded body would still burn CPU before
#: reaching the hasher.
MAX_PASSWORD_LENGTH = 1024

_hasher = PasswordHasher()


class WeakPasswordError(ValueError):
    """Raised when a password fails policy."""


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        )


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, VerificationError):
        return True


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("thaalam-timing-equalisation-placeholder")


def waste_time() -> None:
    """Burn one verification's worth of CPU for an account that doesn't exist.

    Without this, a missing account returns visibly faster than a wrong
    password, which turns the login form into an account-enumeration oracle.
    """
    try:
        _hasher.verify(_dummy_hash(), "not-the-password")
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass
