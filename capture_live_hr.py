"""Capture live per-beat heart rate over Bluetooth from WHOOP's HR Broadcast.

This is separate from `main.py`'s historical API sync: WHOOP's public API
never exposes raw/second-wise heart rate or HRV (only per-cycle/recovery/
workout aggregates). The one official way to get real beat-by-beat data is
WHOOP's "HR Broadcast" feature, which turns the strap into a standard
Bluetooth Heart Rate Service peripheral -- this script connects to that
broadcast directly and logs samples to `data/whoop.duckdb`
(`hr_broadcast_samples` table).

Before running:
1. Open the WHOOP app -> Settings -> Strap Settings -> turn on HR Broadcast.
2. Make sure this computer's Bluetooth is on and the strap is nearby.

Run with `uv run capture_live_hr.py` from the project root. Stop with
Ctrl+C (or let it stop on its own via --duration); buffered samples are
flushed to the database before exit either way.
"""

import argparse
import asyncio

from thaalam.ble_stream import run_live_capture
from thaalam.logging_config import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name-filter",
        default=None,
        help="Only match devices whose advertised name contains this text "
        "(default: match any device advertising the standard Heart Rate Service).",
    )
    parser.add_argument(
        "--address",
        default=None,
        help="Connect directly to a known BLE address instead of scanning.",
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=10.0,
        help="Seconds to scan for a broadcasting device before giving up (default: 10).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop automatically after this many seconds (default: run until Ctrl+C).",
    )
    args = parser.parse_args()

    setup_logging()
    session_id = asyncio.run(
        run_live_capture(
            name_filter=args.name_filter,
            address=args.address,
            scan_timeout=args.scan_timeout,
            duration=args.duration,
        )
    )
    print(f"Session {session_id} stored in data/whoop.duckdb (hr_broadcast_samples table).")


if __name__ == "__main__":
    main()
