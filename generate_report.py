"""Generate the WHOOP data HTML report from the local DuckDB database.

Run with `uv run generate_report.py`. Reads `data/whoop.duckdb` (synced
via `uv run main.py`) and writes a self-contained `data/report.html`.
"""

from thaalam.logging_config import setup_logging
from thaalam.report import build_report


def main() -> None:
    setup_logging()
    output_path = build_report()
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
