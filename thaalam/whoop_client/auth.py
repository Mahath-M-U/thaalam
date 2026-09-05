"""OAuth2 authentication for the WHOOP API.

Implements WHOOP's OAuth2 authorization-code flow as described at
https://developer.whoop.com/docs/developing/oauth:

1. Build an authorization URL and send the user there to grant access.
2. Exchange the authorization code WHOOP redirects back with for an
   access token (and a refresh token, via the ``offline`` scope).
3. Automatically refresh the access token using the refresh token
   before it expires.

Tokens are cached to disk (when ``token_path`` is given) so a headless
script can reuse them across runs without repeating the interactive
consent step.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from thaalam.config import is_non_dev as config_is_non_dev

logger = logging.getLogger(__name__)

# Encrypted-at-rest token files start with this prefix so we can still
# detect and migrate the older plaintext JSON cache in one pass.
TOKEN_FILE_PREFIX = b"THAALAM1."

AUTHORIZE_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
REVOKE_URL = "https://api.prod.whoop.com/developer/v2/user/access"

DEFAULT_SCOPES = [
    "read:profile",
    "read:body_measurement",
    "read:cycles",
    "read:recovery",
    "read:sleep",
    "read:workout",
    "offline",
]

# Refresh a little before the access token actually expires so a request
# started right at the boundary doesn't fail with a 401.
EXPIRY_SKEW_SECONDS = 60


class WhoopAuth:
    """Owns the OAuth2 token lifecycle for the WHOOP API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str | None = None,
        *,
        scopes: list[str] | None = None,
        token: dict[str, Any] | None = None,
        token_path: str | Path | None = None,
        token_key: str | bytes | None = None,
        token_key_path: str | Path | None = None,
        authorize_url: str = AUTHORIZE_URL,
        token_url: str = TOKEN_URL,
        revoke_url: str = REVOKE_URL,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes if scopes is not None else list(DEFAULT_SCOPES)
        self.authorize_url = authorize_url
        self.token_url = token_url
        self.revoke_url = revoke_url
        self.token_path = Path(token_path) if token_path else None
        self.token_key_path = Path(token_key_path) if token_key_path else None

        self.session = requests.Session()
        self._token: dict[str, Any] | None = None
        self._token_key = _resolve_token_key(
            token_key, self.token_key_path, persist_path=self.token_path
        )

        if token is not None:
            self._set_token(token, persist=False)
        elif self.token_path and self.token_path.exists():
            loaded, migrated = _load_token_file(self.token_path, self._token_key)
            self._set_token(loaded, persist=migrated)
            logger.debug("Loaded cached WHOOP token from %s", self.token_path)

    def __enter__(self) -> WhoopAuth:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    @property
    def token(self) -> dict[str, Any] | None:
        """The current OAuth2 token, suitable for persisting and later reuse."""
        return self._token

    def is_authenticated(self) -> bool:
        """Whether the client currently holds a token (not necessarily a valid one)."""
        return self._token is not None

    def authorization_url(self, state: str | None = None) -> tuple[str, str]:
        """Build the URL a user visits to grant this app access to their WHOOP data.

        After the user grants access, WHOOP redirects them to
        ``redirect_uri`` with an authorization code in the query string.
        Pass that redirect URL (or the bare code) to ``fetch_token()``.
        """
        if not self.redirect_uri:
            raise ValueError("redirect_uri is required to build an authorization URL.")

        # WHOOP requires a self-generated state to be exactly 8 characters.
        state = state or secrets.token_hex(4)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
        }
        return f"{self.authorize_url}?{urlencode(params)}", state

    def fetch_token(
        self,
        *,
        code: str | None = None,
        authorization_response: str | None = None,
    ) -> dict[str, Any]:
        """Exchange an authorization code for an access token.

        Provide either the full ``authorization_response`` redirect URL the
        user landed on, or the bare ``code`` extracted from its query string.
        """
        if authorization_response and not code:
            query = parse_qs(urlparse(authorization_response).query)
            codes = query.get("code")
            if not codes:
                raise ValueError("No 'code' parameter found in authorization_response.")
            code = codes[0]

        if not code:
            raise ValueError("Provide either 'code' or 'authorization_response'.")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
        }
        response = self.session.post(self.token_url, data=data)
        response.raise_for_status()
        token: dict[str, Any] = response.json()
        self._set_token(token)
        logger.info("Authorized with WHOOP; access token expires in %ss", token.get("expires_in"))
        return token

    def refresh_access_token(self) -> dict[str, Any]:
        """Use the stored refresh token to obtain a new access token.

        WHOOP rotates the refresh token on every use; the new one is
        stored automatically so the next refresh keeps working.
        """
        if not self._token or not self._token.get("refresh_token"):
            raise RuntimeError("No refresh token available; run the authorization flow again.")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._token["refresh_token"],
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "offline",
        }
        response = self.session.post(self.token_url, data=data)
        response.raise_for_status()
        token: dict[str, Any] = response.json()
        # WHOOP rotates the refresh token; persist the replacement atomically
        # so a crash between exchange and write cannot strand the old token.
        self._set_token(token)
        logger.info("Refreshed WHOOP access token; expires in %ss", token.get("expires_in"))
        return token

    def ensure_fresh_token(self) -> None:
        """Refresh the access token if it's missing or close to expiring."""
        if not self._token:
            raise RuntimeError("Not authenticated. Run the authorization flow first.")

        if time.time() >= self._token["expires_at"] - EXPIRY_SKEW_SECONDS:
            self.refresh_access_token()

    def revoke_access(self) -> None:
        """Revoke this user's OAuth grant (also stops any webhook deliveries)."""
        self.ensure_fresh_token()
        response = self.session.delete(self.revoke_url)
        response.raise_for_status()
        logger.info("Revoked WHOOP OAuth access.")

    def _set_token(self, token: dict[str, Any], *, persist: bool = True) -> None:
        incoming = dict(token)
        # Keep the previous refresh token if a response omits it; WHOOP's
        # rotating grant normally includes a replacement, which then wins.
        if self._token:
            merged = dict(self._token)
            merged.update(incoming)
            token = merged
        else:
            token = incoming

        # A token freshly issued/refreshed by WHOOP has a relative
        # "expires_in" (seconds). A token reloaded from disk already has
        # our own absolute "expires_at" and must not be recomputed.
        if "expires_at" not in incoming:
            token["expires_at"] = time.time() + float(token.get("expires_in", 0))

        self._token = token
        self.session.headers["Authorization"] = f"Bearer {token['access_token']}"

        if persist and self.token_path:
            _persist_token_file(self.token_path, token, self._token_key)


def default_token_key_path() -> Path:
    from thaalam.config import clean_env_value

    env_file = clean_env_value(os.getenv("WHOOP_TOKEN_KEY_FILE"))
    if env_file:
        return Path(env_file)
    return Path.home() / ".thaalam" / "whoop_token.key"


def _is_non_dev() -> bool:
    return config_is_non_dev()


def _resolve_token_key(
    explicit: str | bytes | None,
    key_path: Path | None,
    *,
    persist_path: Path | None,
) -> bytes:
    """32-byte master key from the constructor, WHOOP_TOKEN_KEY, or a key file.

    The key file is never stored next to the token ciphertext. Non-dev
    environments must set WHOOP_TOKEN_KEY; local/dev may generate a 0600
    file once under ~/.thaalam (or WHOOP_TOKEN_KEY_FILE).
    """
    if isinstance(explicit, bytes) and explicit:
        if len(explicit) != 32:
            raise ValueError("token_key bytes must be 32 bytes")
        return explicit
    if isinstance(explicit, str) and explicit.strip():
        return _parse_token_key(explicit)

    env_key = os.getenv("WHOOP_TOKEN_KEY")
    if env_key and env_key.strip():
        return _parse_token_key(env_key)

    if persist_path is None and key_path is None:
        return os.urandom(32)

    if _is_non_dev():
        raise RuntimeError(
            "WHOOP_TOKEN_KEY must be set outside local development "
            "(or pass token_key=). Refusing to mint a key beside the token file."
        )

    resolved = key_path or default_token_key_path()
    _maybe_relocate_legacy_sibling_key(persist_path, resolved)

    if resolved.exists():
        key = _parse_token_key(resolved.read_text(encoding="utf-8"))
        _chmod_private(resolved)
        return key

    key = os.urandom(32)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(base64.urlsafe_b64encode(key).decode("ascii") + "\n", encoding="utf-8")
    _chmod_private(resolved)
    return key


def _maybe_relocate_legacy_sibling_key(token_path: Path | None, dest: Path) -> None:
    """Move an old data/whoop_token.key away from the ciphertext, once."""
    if token_path is None or dest.exists():
        return
    legacy = token_path.with_name("whoop_token.key")
    if not legacy.exists() or legacy.resolve() == dest.resolve():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(legacy.read_bytes())
    _chmod_private(dest)
    try:
        legacy.unlink()
    except OSError:
        logger.warning("Moved token key to %s; delete leftover %s", dest, legacy)
        return
    logger.info("Moved token key from %s to %s", legacy, dest)


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _sealed_marker(token_path: Path) -> Path:
    return token_path.with_name(token_path.name + ".sealed")


def _mark_encrypted(token_path: Path) -> None:
    marker = _sealed_marker(token_path)
    marker.write_text("1\n", encoding="utf-8")


def _parse_token_key(value: str) -> bytes:
    text = value.strip()
    # Tolerate Dokploy-pasted quotes: WHOOP_TOKEN_KEY='"abc..."' would
    # otherwise fail base64 decoding with a confusing error.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    if len(text) == 64 and all(c in "0123456789abcdefABCDEF" for c in text):
        return bytes.fromhex(text)
    padded = text + "=" * (-len(text) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    if len(raw) != 32:
        raise ValueError("WHOOP_TOKEN_KEY must decode to 32 bytes")
    return raw


def _derive_keys(master: bytes) -> tuple[bytes, bytes]:
    enc_key = hmac.new(master, b"thaalam-token-ctr", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"thaalam-token-mac", hashlib.sha256).digest()
    return enc_key, mac_key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(enc_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _encrypt_token_blob(plaintext: bytes, key: bytes) -> bytes:
    enc_key, mac_key = _derive_keys(key)
    nonce = os.urandom(16)
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, _keystream(enc_key, nonce, len(plaintext))))
    tag = hmac.new(mac_key, b"enc" + nonce + ciphertext, hashlib.sha256).digest()
    return TOKEN_FILE_PREFIX + base64.urlsafe_b64encode(nonce + ciphertext + tag)


def _decrypt_token_blob(blob: bytes, key: bytes) -> bytes:
    enc_key, mac_key = _derive_keys(key)
    payload = blob[len(TOKEN_FILE_PREFIX) :] if blob.startswith(TOKEN_FILE_PREFIX) else blob
    raw = base64.urlsafe_b64decode(payload)
    if len(raw) < 48:
        raise ValueError("Encrypted token file is truncated")
    nonce, ciphertext, tag = raw[:16], raw[16:-32], raw[-32:]
    expected = hmac.new(mac_key, b"enc" + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise ValueError("Token file authentication failed")
    return bytes(a ^ b for a, b in zip(ciphertext, _keystream(enc_key, nonce, len(ciphertext))))


def _allow_plaintext_migration() -> bool:
    flag = (os.getenv("WHOOP_MIGRATE_PLAINTEXT_TOKEN") or "").strip().lower()
    return flag in ("1", "true", "yes")


def _load_token_file(path: Path, key: bytes) -> tuple[dict[str, Any], bool]:
    """Return `(token, migrated)` — `migrated` is True when plaintext was rewritten encrypted."""
    raw = path.read_bytes()
    if raw.startswith(TOKEN_FILE_PREFIX):
        return json.loads(_decrypt_token_blob(raw, key)), False

    if _sealed_marker(path).exists() and not _allow_plaintext_migration():
        raise ValueError(
            f"Refusing plaintext WHOOP token at {path} after encrypted storage was enabled"
        )

    token = json.loads(raw.decode("utf-8"))
    if not isinstance(token, dict):
        raise ValueError(f"Token file {path} did not contain a JSON object")
    logger.info("Migrating plaintext WHOOP token cache at %s to encrypted storage", path)
    return token, True


def _persist_token_file(path: Path, token: dict[str, Any], key: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = _encrypt_token_blob(json.dumps(token, indent=2).encode("utf-8"), key)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_bytes(blob)
    os.replace(tmp_path, path)
    _mark_encrypted(path)
