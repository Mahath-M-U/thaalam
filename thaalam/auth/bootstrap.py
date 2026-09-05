"""Create the first administrator account.

    uv run -m thaalam.auth.bootstrap
    docker compose exec app python -m thaalam.auth.bootstrap

There are no default credentials anywhere in the app: an account only exists
once someone runs this. The password can be supplied non-interactively for
container use, in which case the account is flagged to force a change at first
login, since a password passed through an environment variable or argv has
been exposed to the process table and shell history.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

from thaalam.auth import passwords, store
from thaalam.auth.store import ROLE_ADMIN, ROLE_VIEWER


def _prompt_password() -> str:
    while True:
        first = getpass.getpass("Password: ")
        try:
            passwords.validate_password(first)
        except passwords.WeakPasswordError as exc:
            print(f"  {exc}", file=sys.stderr)
            continue
        if first != getpass.getpass("Confirm password: "):
            print("  Passwords did not match.", file=sys.stderr)
            continue
        return first


def create_account(
    email: str,
    password: str | None,
    *,
    role: str = ROLE_ADMIN,
    force_change: bool = False,
) -> tuple[str, str | None]:
    """Create an account. Returns (email, generated password or None)."""
    generated: str | None = None
    if password is None:
        generated = secrets.token_urlsafe(18)
        password = generated

    with store.connect() as con:
        if store.get_user_by_email(con, email) is not None:
            raise SystemExit(f"An account already exists for {email}.")

        user_id = store.create_user(
            con,
            email=email,
            password_hash=passwords.hash_password(password),
            role=role,
            must_change_password=force_change or generated is not None,
        )
        store.record_audit(
            con,
            "user.created",
            user_id=user_id,
            actor_email=email,
            detail=f"bootstrap role={role}",
        )
    return email, generated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a Thaalam account.")
    parser.add_argument("--email", help="Account email address")
    parser.add_argument(
        "--role",
        choices=(ROLE_ADMIN, ROLE_VIEWER),
        default=ROLE_ADMIN,
        help="Account role (default: admin)",
    )
    parser.add_argument(
        "--generate-password",
        action="store_true",
        help="Print a generated password instead of prompting. The account "
        "must change it at first login.",
    )
    args = parser.parse_args(argv)

    email = args.email or input("Email: ").strip()
    if not email:
        parser.error("An email address is required.")

    if args.generate_password:
        password = None
    else:
        password = _prompt_password()

    _, generated = create_account(
        email, password, role=args.role, force_change=args.generate_password
    )

    print(f"\nCreated {args.role} account: {email}")
    if generated:
        print(f"Temporary password: {generated}")
        print("It must be changed at first login.")
    return 0


if __name__ == "__main__":
    import thaalam.config  # noqa: F401  -- importing loads .env

    from thaalam.logging_config import setup_logging

    setup_logging()
    raise SystemExit(main())
