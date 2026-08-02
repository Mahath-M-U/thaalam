"""Service layer: turns repository data into report-ready content.

See `thaalam.services.report_service` for the implementation.
"""

from thaalam.services.report_service import (
    ReportData,
    build_charts,
    build_summary_stats,
    load_report_data,
)

__all__ = [
    "ReportData",
    "build_charts",
    "build_summary_stats",
    "load_report_data",
]
