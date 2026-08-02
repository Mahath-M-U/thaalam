"""Service layer: turns repository data into report-ready content.

See `thaalam.services.report_service` for the implementation.
"""

from thaalam.services.brief_service import (
    EXPLAINERS,
    BriefSnapshot,
    answer_explainer,
    build_snapshot,
    compose_brief,
)
from thaalam.services.report_service import (
    ReportData,
    build_charts,
    build_summary_stats,
    load_report_data,
)

__all__ = [
    "EXPLAINERS",
    "BriefSnapshot",
    "ReportData",
    "answer_explainer",
    "build_charts",
    "build_summary_stats",
    "build_snapshot",
    "compose_brief",
    "load_report_data",
]
