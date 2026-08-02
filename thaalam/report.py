"""Builds the WHOOP HTML report: repositories -> services -> Jinja2 -> HTML.

Opens a **read-only** DuckDB connection (a plain `duckdb.connect(...,
read_only=True)`, not `thaalam.db.get_connection()`, since that helper
runs `CREATE TABLE IF NOT EXISTS` DDL that a read-only connection can't
execute) so this can safely run even if `main.py` is mid-sync. Data
loading and derived content (charts, summary stats) are delegated to
`thaalam.services.report_service`; this module only owns I/O -- the DB
connection lifecycle and rendering/writing the final HTML file (charts
embedded as base64 PNGs, no separate image assets) to `data/report.html`
by default.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import duckdb
from jinja2 import Environment, FileSystemLoader, select_autoescape

from thaalam.db import DEFAULT_DB_PATH
from thaalam.services import report_service

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_OUTPUT_PATH = DEFAULT_DB_PATH.parent / "report.html"


def build_report(
    db_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Query the WHOOP database, build charts, and write the HTML report.

    Returns the path the report was written to.
    """
    db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    output_path = Path(output_path) if output_path is not None else DEFAULT_OUTPUT_PATH

    if not db_path.exists():
        raise FileNotFoundError(
            f"No database found at {db_path}. Run `uv run main.py` at least once "
            "to sync WHOOP data before generating a report."
        )

    logger.info("Opening read-only connection to %s", db_path)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        data = report_service.load_report_data(con)
    finally:
        con.close()

    charts = report_service.build_charts(data)
    summary_stats = report_service.build_summary_stats(data)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html")
    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        summary_stats=summary_stats,
        charts=charts,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Report written to %s", output_path)
    return output_path
