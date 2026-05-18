"""Backfill daily bars for the last year (or a custom range).

Usage:
    uv run python -m ingest.backfill                       # default: today - 365d → today
    uv run python -m ingest.backfill 20250101 20260101     # custom YYYYMMDD range
"""
import sys
from datetime import date, datetime, timedelta

from .daily import fetch_range


def backfill(start_date=None, end_date=None):
    end = date.today() if end_date is None else _parse(end_date)
    start = (end - timedelta(days=365)) if start_date is None else _parse(start_date)
    fetch_range(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))


def _parse(s):
    return datetime.strptime(s, "%Y%m%d").date()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        backfill()
    elif len(sys.argv) == 3:
        backfill(sys.argv[1], sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
