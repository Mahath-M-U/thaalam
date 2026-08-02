"""Ensure the repo root is on sys.path so `import thaalam` works.

This project isn't packaged/installed (no [build-system] in pyproject.toml),
same reason `scripts/tests_dbdata.py` needs an explicit sys.path shim.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
