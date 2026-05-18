"""Incrementally update daily bars from the last date in DB to today.

If the DB is empty, run `uv run python -m ingest.backfill` first.

Usage:
    uv run python -m ingest.incremental
"""
from datetime import date, datetime, timedelta

from store import daily as daily_store

from .daily import fetch_range


def incremental_update():
    last = daily_store.last_global_trade_date()
    if last is None:
        print(
            "daily table is empty; run `uv run python -m ingest.backfill` first"
        )
        return
    last_dt = datetime.strptime(last, "%Y%m%d").date()
    start = last_dt + timedelta(days=1)
    end = date.today()
    if start > end:
        print(f"already current (latest in DB: {last})")
        return
    print(
        f"incremental: latest in DB = {last}; "
        f"fetching {start.strftime('%Y%m%d')} → {end.strftime('%Y%m%d')}"
    )
    fetch_range(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))


if __name__ == "__main__":
    incremental_update()
