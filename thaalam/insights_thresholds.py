"""Tunable thresholds for the rule-based daily insight brief.

Every cutoff used by `thaalam.services.brief_service` lives here (env-var
overridable, same convention as `thaalam.sync.MIN_SYNC_INTERVAL_MINUTES`) so
sensitivity can be tuned without touching rule logic.
"""

from __future__ import annotations

import os

ACWR_HIGH_RISK = float(os.getenv("ACWR_HIGH_RISK", "1.5"))
ACWR_ELEVATED = float(os.getenv("ACWR_ELEVATED", "1.3"))
ACWR_LOW_BOUND = float(os.getenv("ACWR_LOW_BOUND", "0.8"))

HRV_SUPPRESSION_PCT = float(os.getenv("HRV_SUPPRESSION_PCT", "-10.0"))
RHR_ELEVATION_BPM = float(os.getenv("RHR_ELEVATION_BPM", "3.0"))

SLEEP_DEBT_ALERT_HOURS = float(os.getenv("SLEEP_DEBT_ALERT_HOURS", "1.5"))
NOTABLE_ZONE_STREAK_DAYS = int(os.getenv("NOTABLE_ZONE_STREAK_DAYS", "3"))

RESPIRATORY_RATE_ELEVATION = float(os.getenv("RESPIRATORY_RATE_ELEVATION", "1.0"))
SKIN_TEMP_ELEVATION_C = float(os.getenv("SKIN_TEMP_ELEVATION_C", "0.3"))
