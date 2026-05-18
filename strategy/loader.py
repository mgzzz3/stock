"""Read-only access to the `daily` and `stock_basic` tables as pandas DataFrames.

Strategies should never touch `store.*.upsert_many` — only the loader functions here.
"""
import pandas as pd

from store import daily as daily_store
from store.db import connect


def load_one(ts_code, start=None, end=None):
    """One stock's daily bars, indexed by trade_date (YYYYMMDD string, ascending).
    Columns: open, high, low, close, pre_close, change, pct_chg, vol, amount.
    """
    sql = [
        "SELECT trade_date, open, high, low, close, pre_close,",
        "       change, pct_chg, vol, amount",
        "FROM daily WHERE ts_code = ?",
    ]
    params = [ts_code]
    if start:
        sql.append("AND trade_date >= ?")
        params.append(start)
    if end:
        sql.append("AND trade_date <= ?")
        params.append(end)
    sql.append("ORDER BY trade_date")
    with connect() as conn:
        return pd.read_sql_query(
            " ".join(sql), conn, params=params, index_col="trade_date"
        )


def load_all(start=None, end=None, columns=("close",)):
    """Long-format DataFrame for every stock. Columns: ts_code, trade_date, then `columns`.
    Ordered (ts_code, trade_date) so `groupby('ts_code').apply(...)` preserves order.
    Restrict `columns` for large ranges to control memory.
    """
    cols = ", ".join(["ts_code", "trade_date", *columns])
    sql = f"SELECT {cols} FROM daily"
    where, params = [], []
    if start:
        where.append("trade_date >= ?")
        params.append(start)
    if end:
        where.append("trade_date <= ?")
        params.append(end)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ts_code, trade_date"
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def latest_trade_date():
    return daily_store.last_global_trade_date()


def stock_names():
    """ts_code → (name, industry) lookup as a DataFrame."""
    with connect() as conn:
        return pd.read_sql_query(
            "SELECT ts_code, name, industry FROM stock_basic", conn
        )
