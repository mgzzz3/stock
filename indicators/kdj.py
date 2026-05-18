"""KDJ stochastic oscillator (N=9 default, A-share SMA convention).

Persists computed values to the `kdj` table so strategies can read them without
recomputing on every run.

Formula (standard 通达信/A 股 convention):
    RSV(t) = (close(t) - min(low, N)) / (max(high, N) - min(low, N)) × 100
    K(t)   = (2/3)·K(t-1) + (1/3)·RSV(t),   K(0) = 50
    D(t)   = (2/3)·D(t-1) + (1/3)·K(t),     D(0) = 50
    J(t)   = 3·K(t) - 2·D(t)

Usage:
    uv run python -m indicators.kdj            # full rebuild from daily table
"""
import sys

import numpy as np
import pandas as pd
from tqdm import tqdm

from store import schema
from store.db import connect

N = 9
INITIAL_K = 50.0
INITIAL_D = 50.0


def compute_one(high, low, close, n=N, k0=INITIAL_K, d0=INITIAL_D):
    """Compute K/D/J arrays for one stock's time series.

    Inputs are array-likes of equal length, sorted by trade_date ascending.
    Returns three numpy arrays (k, d, j) of the same length. Indices before
    the N-th observation are NaN (rolling-window warm-up).
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)

    high_n = pd.Series(high).rolling(n, min_periods=n).max().to_numpy()
    low_n = pd.Series(low).rolling(n, min_periods=n).min().to_numpy()
    denom = high_n - low_n
    rsv = np.where(denom > 0, (close - low_n) / denom * 100, np.nan)

    k = np.full_like(close, np.nan)
    d = np.full_like(close, np.nan)
    k_prev, d_prev = k0, d0
    for i in range(len(close)):
        if np.isnan(rsv[i]):
            continue
        k_prev = (2 * k_prev + rsv[i]) / 3
        d_prev = (2 * d_prev + k_prev) / 3
        k[i] = k_prev
        d[i] = d_prev
    j = 3 * k - 2 * d
    return k, d, j


_UPSERT = """
INSERT INTO kdj (ts_code, trade_date, k, d, j)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(ts_code, trade_date) DO UPDATE SET
  k=excluded.k, d=excluded.d, j=excluded.j
"""


def rebuild():
    """Recompute KDJ for every stock from scratch and upsert. Idempotent."""
    schema.init_db()
    with connect() as conn:
        df = pd.read_sql_query(
            "SELECT ts_code, trade_date, high, low, close FROM daily "
            "ORDER BY ts_code, trade_date",
            conn,
        )
    print(f"loaded {len(df):,} daily rows for {df['ts_code'].nunique()} stocks")

    all_rows = []
    for ts_code, g in tqdm(df.groupby("ts_code", sort=False),
                           unit="stock", desc="KDJ"):
        if len(g) < N:
            continue
        k, d, j = compute_one(g["high"], g["low"], g["close"])
        valid = ~np.isnan(k)
        if not valid.any():
            continue
        dates = g["trade_date"].to_numpy()[valid]
        all_rows.extend(zip(
            [ts_code] * valid.sum(),
            dates.tolist(),
            k[valid].tolist(),
            d[valid].tolist(),
            j[valid].tolist(),
        ))

    print(f"upserting {len(all_rows):,} KDJ rows...")
    with connect() as conn:
        conn.executemany(_UPSERT, all_rows)
    print("done")


def load(ts_code=None, start=None, end=None):
    """Read KDJ from the DB.

    - With `ts_code`: returns DataFrame indexed by trade_date, columns (k, d, j).
    - Without: returns long-format (ts_code, trade_date, k, d, j) ordered by both.
    """
    if ts_code:
        sql = "SELECT trade_date, k, d, j FROM kdj WHERE ts_code = ?"
        params = [ts_code]
    else:
        sql = "SELECT ts_code, trade_date, k, d, j FROM kdj WHERE 1=1"
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
