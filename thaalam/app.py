"""Composition root: authenticate with WHOOP and run a full historical sync.

Run with `uv run main.py` (or `python main.py`) from the project root. The
first run walks you through a one-time interactive authorization; the
resulting token is cached to disk under `data/` and refreshed automatically
on later runs.
"""

import logging
import sys
from pathlib import Path

from thaalam.config import get_settings
from thaalam.logging_config import setup_logging
from thaalam.sync import sync_all_historical_data
from thaalam.whoop_client.auth import AUTHORIZE_URL, REVOKE_URL, TOKEN_URL
from thaalam.whoop_client.client import WhoopClient

setup_logging()
logger = logging.getLogger(__name__)

_settings = get_settings()
client_id = _settings.client_id
client_secret = _settings.client_secret
redirect_uri = _settings.redirect_uri
authorization_url = _settings.authorization_url or AUTHORIZE_URL
token_url = _settings.token_url or TOKEN_URL
revoke_url = _settings.revoke_url or REVOKE_URL

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TOKEN_PATH = DATA_DIR / "whoop_token.json"
DB_PATH = DATA_DIR / "whoop.duckdb"


def _authenticate(client: WhoopClient) -> None:
    """Run the one-time interactive OAuth2 flow if there's no cached token."""
    if not redirect_uri:
        logger.error(
            "REDIRECT_URI is not set in .env. Set it to the redirect URI you "
            "registered for this app in the WHOOP Developer Dashboard, then "
            "re-run this script."
        )
        sys.exit(1)

    logger.info("No cached token found; starting interactive authorization.")
    url, _state = client.authorization_url()
    print("Open this URL in a browser and approve access to your WHOOP data:\n")
    print(url)
    print(
        "\nWHOOP will then redirect your browser to your redirect URI. That "
        "page may fail to load -- that's expected. Copy the full URL from "
        "the address bar (it contains '?code=...') and paste it below.\n"
    )
    redirect_response = input("Redirect URL (or just the 'code' value): ").strip()

    if redirect_response.startswith("http"):
        client.fetch_token(authorization_response=redirect_response)
    else:
        client.fetch_token(code=redirect_response)

    logger.info("Authorization successful; token cached for future runs.")


def main() -> None:
    if not client_id or not client_secret:
        logger.error("CLIENT_ID and CLIENT_SECRET must be set in .env.")
        sys.exit(1)

    logger.info("Using token cache: %s", TOKEN_PATH)
    logger.info("Using database: %s", DB_PATH)

    client = WhoopClient(
        client_id,
        client_secret,
        redirect_uri,
        authorize_url=authorization_url,
        token_url=token_url,
        revoke_url=revoke_url,
        token_path=TOKEN_PATH,
    )

    try:
        if not client.is_authenticated():
            _authenticate(client)

        sync_all_historical_data(client, DB_PATH)
    finally:
        client.close()


if __name__ == "__main__":
    main()