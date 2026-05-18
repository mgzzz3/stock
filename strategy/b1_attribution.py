"""Per-condition alpha attribution for strategy b1.

Runs each of b1's 5 conditions as a standalone signal and measures forward-return
lift over the market baseline, plus the full 5-way intersection for comparison.
Identifies which conditions are alpha-positive vs negative — i.e. which ones
are pulling b1's combined lift down.

Baseline is per-condition: for each row, baseline = mean forward return across
all stocks on dates where that condition fires somewhere in the universe.

Usage:
    uv run python -m strategy.b1_attribution                       # default 20mo window
    uv run python -m strategy.b1_attribution 20240901 20260514     # custom range
"""
import sys
from datetime import datetime, timedelta

import pandas as pd

from indicators import kdj, zhixing
from store.db import connect
from strategy import loader

DEFAULT_HORIZONS = (5, 10, 20)
VOL_MA_PERIOD = 5
MA60_PERIOD = 60
J_THRESHOLD = 15


def _shift(yyyymmdd, days):
    d = datetime.strptime(yyyymmdd, "%Y%m%d").date() + timedelta(days=days)
    return d.strftime("%Y%m%d")


def _build_df(scan_start, horizons):
    latest = loader.latest_trade_date()
    load_start = _shift(scan_start, -int(MA60_PERIOD * 1.5) - 10)
    load_end = latest

    print(f"loading daily [{load_start} → {load_end}]...")
    with connect() as conn:
        d = pd.read_sql_query(
            "SELECT ts_code, trade_date, close, vol FROM daily "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY ts_code, trade_date",
            conn, params=[load_start, load_end],
        )
    print(f"loaded {len(d):,} rows / {d['ts_code'].nunique()} stocks")

    g_close = d.groupby("ts_code", sort=False)["close"]
    g_vol = d.groupby("ts_code", sort=False)["vol"]
    d["ma60"] = g_close.rolling(MA60_PERIOD, min_periods=MA60_PERIOD).mean().droplevel(0)
    d["vol_ma5"] = g_vol.rolling(VOL_MA_PERIOD, min_periods=VOL_MA_PERIOD).mean().droplevel(0)
    d["vol_ratio"] = d["vol"] / d["vol_ma5"]

    ret_cols = []
    for h in horizons:
        future_close = d.groupby("ts_code", sort=False)["close"].shift(-h)
        col = f"ret_{h}d"
        d[col] = (future_close - d["close"]) / d["close"]
        ret_cols.append(col)

    print("loading indicators + merging...")
    k = kdj.load(start=load_start, end=load_end)[["ts_code", "trade_date", "j"]]
    z = zhixing.load(start=load_start, end=load_end)[
        ["ts_code", "trade_date", "trend_short", "bull_bear"]
    ]
    df = (d.merge(k, on=["ts_code", "trade_date"], how="inner")
            .merge(z, on=["ts_code", "trade_date"], how="inner"))

    df["c1"] = df["vol_ratio"] < 1.0
    df["c2"] = df["j"] < J_THRESHOLD
    df["c3"] = df["close"] > df["ma60"]
    df["c4"] = df["trend_short"] > df["bull_bear"]
    df["c5"] = df["close"] > df["bull_bear"]
    df["b1"] = df["c1"] & df["c2"] & df["c3"] & df["c4"] & df["c5"]
    return df, ret_cols


def _evaluate(df, mask, scan_start, scan_end, ret_cols):
    in_window = (df["trade_date"] >= scan_start) & (df["trade_date"] <= scan_end)
    signals = df[mask & in_window].dropna(subset=ret_cols)
    if len(signals) == 0:
        return None
    signal_dates = signals["trade_date"].unique()
    baseline = df[df["trade_date"].isin(signal_dates)].dropna(subset=ret_cols)
    return {
        "n": len(signals),
        "n_dates": len(signal_dates),
        "means":  {c: signals[c].mean() for c in ret_cols},
        "lifts":  {c: signals[c].mean() - baseline[c].mean() for c in ret_cols},
    }


def attribute(scan_start=None, scan_end=None, horizons=DEFAULT_HORIZONS):
    latest = loader.latest_trade_date()
    if scan_end is None:
        scan_end = latest
    if scan_start is None:
        scan_start = _shift(scan_end, -600)  # ~20 months

    df, ret_cols = _build_df(scan_start, horizons)

    # b1_mr (mean reversion): keep c1, c2; invert c3, c4, c5
    b1_mr = df["c1"] & df["c2"] & ~df["c3"] & ~df["c4"] & ~df["c5"]
    conditions = [
        ("c1: 缩量 (vol < MA5)",         df["c1"]),
        ("c2: KDJ J < 15",               df["c2"]),
        ("c3: close > MA60",             df["c3"]),
        ("c4: trend > bull_bear",        df["c4"]),
        ("c5: close > bull_bear",        df["c5"]),
        ("b1: ALL 5 conditions",         df["b1"]),
        (None, None),  # visual separator
        ("c3_inv: close < MA60",         ~df["c3"]),
        ("c4_inv: trend < bull_bear",    ~df["c4"]),
        ("c5_inv: close < bull_bear",    ~df["c5"]),
        ("b1_mr: c1+c2+!c3+!c4+!c5",     b1_mr),
    ]

    print()
    print(f"b1 per-condition attribution  [{scan_start} → {scan_end}]")
    print()
    header = f"{'condition':<28}{'n':>11}{'sig/day':>9}"
    for c in ret_cols:
        header += f"{c+' mean':>13}{c+' lift':>13}"
    print(header)
    print("-" * len(header))
    for name, mask in conditions:
        if name is None:
            print("-" * len(header))
            continue
        r = _evaluate(df, mask, scan_start, scan_end, ret_cols)
        if r is None:
            print(f"{name:<28}  (no signals in window)")
            continue
        row = f"{name:<28}{r['n']:>11,}{r['n']/max(r['n_dates'],1):>9.0f}"
        for c in ret_cols:
            row += f"{r['means'][c]*100:>+12.2f}%"
            row += f"{r['lifts'][c]*100:>+12.2f}%"
        print(row)


if __name__ == "__main__":
    args = sys.argv[1:]
    scan_start = args[0] if len(args) >= 1 else None
    scan_end = args[1] if len(args) >= 2 else None
    attribute(scan_start=scan_start, scan_end=scan_end)
