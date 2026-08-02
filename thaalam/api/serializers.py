"""Convert pandas DataFrames / scalars into JSON-safe Python values."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd


def _cell(value: Any) -> Any:
    """Normalize a single cell for JSON (NaN/NaT -> None, timestamps -> ISO)."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    # pandas / numpy scalar types
    if hasattr(value, "item"):
        try:
            item = value.item()
            if isinstance(item, float) and item != item:
                return None
            return item
        except (ValueError, AttributeError):
            pass
    if pd.isna(value):
        return None
    return value


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Turn a DataFrame into a list of JSON-safe dicts (one per row)."""
    if df.empty:
        return []
    records: list[dict[str, Any]] = []
    for row in df.to_dict(orient="records"):
        records.append({key: _cell(val) for key, val in row.items()})
    return records


def first_record(df: pd.DataFrame) -> dict[str, Any] | None:
    """Return the first row as a dict, or None if empty."""
    records = dataframe_to_records(df)
    return records[0] if records else None
