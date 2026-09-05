"""Start the Thaalam FastAPI server.

    uv run run_api.py
    # or: uv run uvicorn thaalam.api.main:app --reload --port 8000
"""

from __future__ import annotations
from thaalam.app import main as run_whoop_sync
import uvicorn

def main() -> None:
    uvicorn.run(
        "thaalam.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()




