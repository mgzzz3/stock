"""黄金坑 (Golden Pit) indicator — adapted from a 通达信 副图 公式.

Stored in the `golden_pit` table per (ts_code, trade_date):

  - var2z  : SMA(SMA(CROSS(金坑买入, 0), 8, 1), 8, 1)   — 主指标线
  - var3z  : SMA(VAR2Z, 10, 1)                          — 信号线
  - signal : 1 when VAR2Z crosses up through VAR3Z AND VAR2Z < 40, else 0

Composite oscillator:
  金坑买入 = (RSI5 + ADX) + (RSI5 - WR10)
    RSI5 = 5-period RSI on CLOSE (uses the source script's SMA convention)
    ADX  = MA(|MDI-PDI|/(MDI+PDI)*100, 5), with PDI/MDI from 10-bar directional sums
    WR10 = 100 * (HHV(HIGH,60)-CLOSE) / (HHV(HIGH,60)-LLV(LOW,60))

Note: the source script's `SMA(x, N, M=1)` is `sum(window)*M / N` (windowed
mean with a scalar weight), *not* the recursive 通达信 SMA. Preserved as-is
for fidelity to the original 副图 公式.

Usage:
    uv run python -m indicators.golden_pit
"""
import numpy as np
import pandas as pd
from tqdm import tqdm

from store import schema
from store.db import connect

# 60-bar HHV/LLV warm-up — no value of VAR2Z exists before this.
MIN_BARS = 60


def _sma(series, n, m=1):
    return series.rolling(n).apply(
        lambda x: np.sum(x * m) / n if len(x) == n else np.nan, raw=True
    )


def _cross(s1, s2):
    return (s1 > s2) & (s1.shift(1) <= s2.shift(1))


def compute_one(high, low, close):
    """Return DataFrame(var2z, var3z, signal) for one stock's time series.

    Inputs array-like, sorted by trade_date ascending. Output aligned to input length;
    early rows are NaN/0 during rolling-window warm-up.
    """
    close = pd.Series(np.asarray(close, dtype=float))
    high = pd.Series(np.asarray(high, dtype=float))
    low = pd.Series(np.asarray(low, dtype=float))

    lcf = close.shift(1)
    diff = close - lcf
    rsi5 = _sma(diff.clip(lower=0), 5) / _sma(diff.abs(), 5) * 100

    hl = high - low
    hc = (high - lcf).abs()
    lc = (low - lcf).abs()
    tr1f = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(10).sum()

    hd = high - high.shift(1)
    ld = low.shift(1) - low
    dmp = ((hd > 0) & (hd > ld)).astype(float) * hd
    dmm = ((ld > 0) & (ld > hd)).astype(float) * ld
    pdi = dmp.rolling(10).sum() * 100 / tr1f
    mdi = dmm.rolling(10).sum() * 100 / tr1f
    adx = ((mdi - pdi).abs() / (mdi + pdi) * 100).rolling(5).mean()

    hhv60 = high.rolling(60).max()
    llv60 = low.rolling(60).min()
    wr10 = 100 * (hhv60 - close) / (hhv60 - llv60)

    golden_buy = (rsi5 + adx) + (rsi5 - wr10)
    buy_signal = ((golden_buy > 0) & (golden_buy.shift(1) <= 0)).astype(float)

    var1z = _sma(buy_signal, 8)
    var2z = _sma(var1z, 8)
    var3z = _sma(var2z, 10)
    signal = (_cross(var2z, var3z) & (var2z < 40)).astype(int)

    return pd.DataFrame({
        "var2z": var2z.to_numpy(),
        "var3z": var3z.to_numpy(),
        "signal": signal.to_numpy(),
    })


_UPSERT = """
INSERT INTO golden_pit (ts_code, trade_date, var2z, var3z, signal)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(ts_code, trade_date) DO UPDATE SET
  var2z=excluded.var2z, var3z=excluded.var3z, signal=excluded.signal
"""


def _na(x):
    return None if (isinstance(x, float) and np.isnan(x)) else float(x)


def rebuild():
    """Recompute golden_pit for every stock from scratch and upsert. Idempotent."""
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
                           unit="stock", desc="golden_pit"):
        if len(g) < MIN_BARS:
            continue
        out = compute_one(g["high"], g["low"], g["close"])
        v2 = out["var2z"].to_numpy()
        v3 = out["var3z"].to_numpy()
        sig = out["signal"].to_numpy()
        valid = ~(np.isnan(v2) & np.isnan(v3))
        if not valid.any():
            continue
        dates = g["trade_date"].to_numpy()[valid]
        all_rows.extend([
            (ts_code, d, _na(a), _na(b), int(s))
            for d, a, b, s in zip(dates.tolist(), v2[valid], v3[valid], sig[valid])
        ])

    print(f"upserting {len(all_rows):,} golden_pit rows...")
    with connect() as conn:
        conn.executemany(_UPSERT, all_rows)
    print("done")


def load(ts_code=None, start=None, end=None):
    """Read golden_pit values from the DB.

    - With `ts_code`: DataFrame indexed by trade_date, columns (var2z, var3z, signal).
    - Without: long-format (ts_code, trade_date, var2z, var3z, signal).
    """
    if ts_code:
        sql = ("SELECT trade_date, var2z, var3z, signal FROM golden_pit "
               "WHERE ts_code = ?")
        params = [ts_code]
    else:
        sql = ("SELECT ts_code, trade_date, var2z, var3z, signal FROM golden_pit "
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
