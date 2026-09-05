"""Start the Thaalam API server.

Thin alias for `run_api.py`, kept because the README and launch config both
point here.

    uv run main.py

The WHOOP sync itself lives in `thaalam/app.py` (interactive OAuth + full
historical sync) and runs from the API via the nightly job, webhooks, and the
Refresh button.
"""

from __future__ import annotations

from run_api import main

if __name__ == "__main__":
    main()
