"""WHOOP v2 API client, built from scratch against the official REST API
(https://developer.whoop.com/api).

Inspired by the design of https://github.com/hedgertronic/whoop, but
implemented independently on top of plain `requests` -- the `whoop` PyPI
package is not installed or used.
"""

from thaalam.whoop_client.auth import DEFAULT_SCOPES, WhoopAuth
from thaalam.whoop_client.client import WhoopClient

__all__ = ["DEFAULT_SCOPES", "WhoopAuth", "WhoopClient"]
