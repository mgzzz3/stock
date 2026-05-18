"""知行合一 indicator family — adapted from a 通达信 (TDX) script.

Two lines, both persisted in the `zhixing` table:

  - **trend_short** (知行短期趋势线)
        EMA(EMA(close, 10), 10)
        TDX EMA matches pandas `ewm(span=N, adjust=False).mean()`:
            EMA[i] = (2·X[i] + (N-1)·EMA[i-1]) / (N+1),  EMA[0] = X[0]

  - **bull_bear** (知行多空线)
        mean of 4 simple MAs over `BULL_BEAR_PERIODS` = (14, 28, 57, 114).
        Valid only after the longest period — bars before bar #114 are NaN.

Skipped from the original TDX script (display-only, not indicator values):
  - 滴滴战法 DRAWLINE / DRAWICON annotations
  - DRAWTEXT_FIX with HYBLOCK / DYBLOCK / GNBLOCK 板块文字

Usage:
    uv run python -m indicators.zhixing
"""
import numpy as np
import pandas as pd
from tqdm import tqdm

from store import schema
from store.db import connect

TREND_EMA_PERIOD = 10
BULL_BEAR_PERIODS = (14, 28, 57, 114)


def compute_one(
    close,
    ema_period=TREND_EMA_PERIOD,
    bb_periods=BULL_BEAR_PERIODS,
):
    """Return (trend_short, bull_bear) numpy arrays for one stock.
    `close` is array-like, sorted by trade_date ascending.
    """
    s = pd.Series(np.asarray(close, dtype=float))
    ema1 = s.ewm(span=ema_period, adjust=False).mean()
    trend = ema1.ewm(span=ema_period, adjust=False).mean()
    mas = [s.rolling(p, min_periods=p).mean() for p in bb_periods]
    bull_bear = sum(mas) / len(mas)
    return trend.to_numpy(), bull_bear.to_numpy()


_UPSERT = """
INSERT INTO zhixing (ts_code, trade_date, trend_short, bull_bear)
VALUES (?, ?, ?, ?)
ON CONFLICT(ts_code, trade_date) DO UPDATE SET
  trend_short=excluded.trend_short, bull_bear=excluded.bull_bear
"""


def _na(x):
    return None if (isinstance(x, float) and np.isnan(x)) else float(x)


def rebuild():
    """Recompute zhixing lines for every stock from scratch. Idempotent."""
    schema.init_db()
    with connect() as conn:
        df = pd.read_sql_query(
            "SELECT ts_code, trade_date, close FROM daily "
            "ORDER BY ts_code, trade_date",
            conn,
        )
    print(f"loaded {len(df):,} daily rows for {df['ts_code'].nunique()} stocks")

    all_rows = []
    for ts_code, g in tqdm(df.groupby("ts_code", sort=False),
                           unit="stock", desc="zhixing"):
        if len(g) == 0:
            continue
        trend, bull_bear = compute_one(g["close"])
        # Keep every bar where at least one of the two indicators is valid.
        # trend_short is valid from bar 0; bull_bear only after bar 113.
        valid = ~(np.isnan(trend) & np.isnan(bull_bear))
        if not valid.any():
            continue
        dates = g["trade_date"].to_numpy()[valid]
        all_rows.extend([
            (ts_code, d, _na(t), _na(b))
            for d, t, b in zip(dates.tolist(), trend[valid], bull_bear[valid])
        ])

    print(f"upserting {len(all_rows):,} zhixing rows...")
    with connect() as conn:
        conn.executemany(_UPSERT, all_rows)
    print("done")


def load(ts_code=None, start=None, end=None):
    """Read 知行合一 indicators from the DB.

    - With `ts_code`: DataFrame indexed by trade_date, columns (trend_short, bull_bear).
    - Without: long-format (ts_code, trade_date, trend_short, bull_bear).
    """
    if ts_code:
        sql = ("SELECT trade_date, trend_short, bull_bear FROM zhixing "
               "WHERE ts_code = ?")
        params = [ts_code]
    else:
        sql = ("SELECT ts_code, trade_date, trend_short, bull_bear FROM zhixing "
               "WHERE 1=1")
        params = []
    if start:
        sql += " AND trade_date >= ?"
        params.append(start)
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)
    sql += " ORDER BY trade_date" if ts_code else " ORDER BY ts_code, trade_date"
    with connect() as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    if ts_code:
        df = df.set_index("trade_date")
    return df


if __name__ == "__main__":
    rebuild()
