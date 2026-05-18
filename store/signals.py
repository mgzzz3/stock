"""Append-only log of strategy signals.

Each row records: this strategy fired for this stock on this trade_date.
Primary key is (strategy, ts_code, trade_date) — re-running a screen for
the same date is idempotent.
"""
from datetime import UTC, datetime

from .db import connect

_UPSERT = """
INSERT INTO signals (strategy, ts_code, trade_date, close, created_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(strategy, ts_code, trade_date) DO UPDATE SET
  close=excluded.close, created_at=excluded.created_at
"""


def upsert_many(strategy, rows):
    """Upsert signal rows.
    `rows`: iterable of (ts_code, trade_date, close) tuples.
    Returns the number of rows persisted.
    """
    now = datetime.now(UTC).isoformat()
    payload = [(strategy, ts, td, float(c) if c is not None else None, now)
               for ts, td, c in rows]
    with connect() as conn:
        conn.executemany(_UPSERT, payload)
    return len(payload)


def history(strategy, ts_code=None, start=None, end=None):
    """Read past signals. With `ts_code` returns rows for that stock; without,
    returns all signals for the strategy. Optional `start`/`end` (YYYYMMDD)."""
    import pandas as pd
    sql = "SELECT strategy, ts_code, trade_date, close, created_at FROM signals WHERE strategy = ?"
    params = [strategy]
    if ts_code:
        sql += " AND ts_code = ?"
        params.append(ts_code)
    if start:
        sql += " AND trade_date >= ?"
        params.append(start)
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)
    sql += " ORDER BY ts_code, trade_date"
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def count(strategy, trade_date=None):
    """Count signals for a strategy. Optionally for one trade_date."""
    sql = "SELECT COUNT(*) FROM signals WHERE strategy = ?"
    params = [strategy]
    if trade_date:
        sql += " AND trade_date = ?"
        params.append(trade_date)
    with connect() as conn:
        return conn.execute(sql, params).fetchone()[0]
