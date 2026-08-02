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

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

logger = logging.getLogger(__name__)

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

        self.session = requests.Session()
        self._token: dict[str, Any] | None = None

        if token is not None:
            self._set_token(token, persist=False)
        elif self.token_path and self.token_path.exists():
            self._set_token(json.loads(self.token_path.read_text()), persist=False)
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
        token = dict(token)

        # A token freshly issued/refreshed by WHOOP has a relative
        # "expires_in" (seconds). A token reloaded from disk already has
        # our own absolute "expires_at" and must not be recomputed.
        if "expires_at" not in token:
            token["expires_at"] = time.time() + float(token.get("expires_in", 0))

        self._token = token
        self.session.headers["Authorization"] = f"Bearer {token['access_token']}"

        if persist and self.token_path:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(json.dumps(token, indent=2))
