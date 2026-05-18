"""Historical scan of MA golden-cross signals with forward-return evaluation.

For every cross within the scan window, compute forward returns at given horizons
(5/10/20 trading days by default). Compare to a market baseline (the unconditional
mean forward return across all stocks on the same signal dates) to compute *lift*.

Without a baseline, signal mean-returns are uninterpretable — they reflect both
the signal's edge and the general market drift over the window.

Usage:
    uv run python -m strategy.backtest_cross                       # last 180 days, MA20/MA60
    uv run python -m strategy.backtest_cross 20251101 20260331     # custom range
    uv run python -m strategy.backtest_cross 20251101 20260331 5 20  # short=5, long=20
"""
import sys
from datetime import datetime, timedelta

import pandas as pd

from . import loader

DEFAULT_HORIZONS = (5, 10, 20)


def backtest(
    short_window=20,
    long_window=60,
    scan_start=None,
    scan_end=None,
    horizons=DEFAULT_HORIZONS,
):
    latest = loader.latest_trade_date()
    if latest is None:
        raise RuntimeError("daily table is empty; run ingest.backfill first")
    if scan_end is None:
        scan_end = latest
    if scan_start is None:
        scan_start = _shift_calendar(scan_end, -180)

    # Load enough lookback for MA + enough lookahead for max horizon. 1.5× factor
    # converts trading-day horizons to calendar-day approximations.
    load_start = _shift_calendar(scan_start, -int(long_window * 1.5))
    load_end = latest  # always load to latest so forward returns are available
    print(f"loading daily [{load_start} → {load_end}]...")
    df = loader.load_all(start=load_start, end=load_end, columns=("close",))
    print(f"loaded {len(df):,} rows across {df['ts_code'].nunique()} stocks")

    # All vectorized — per-stock operations via groupby preserve (ts_code, trade_date) order.
    g = df.groupby("ts_code", sort=False)["close"]
    df["ma_s"] = g.rolling(short_window, min_periods=short_window).mean().droplevel(0)
    df["ma_l"] = g.rolling(long_window, min_periods=long_window).mean().droplevel(0)
    df["ma_s_prev"] = df.groupby("ts_code", sort=False)["ma_s"].shift(1)
    df["ma_l_prev"] = df.groupby("ts_code", sort=False)["ma_l"].shift(1)
    df["cross"] = (df["ma_s"] > df["ma_l"]) & (df["ma_s_prev"] <= df["ma_l_prev"])

    ret_cols = []
    for h in horizons:
        future_close = df.groupby("ts_code", sort=False)["close"].shift(-h)
        col = f"ret_{h}d"
        df[col] = (future_close - df["close"]) / df["close"]
        ret_cols.append(col)

    in_window = (df["trade_date"] >= scan_start) & (df["trade_date"] <= scan_end)
    signals = df[df["cross"] & in_window].dropna(subset=ret_cols).copy()

    # Baseline: every stock's forward return on the same signal dates
    signal_dates = signals["trade_date"].unique()
    baseline = df[df["trade_date"].isin(signal_dates)].dropna(subset=ret_cols)

    return signals, baseline, ret_cols, scan_start, scan_end


def _shift_calendar(yyyymmdd, days):
    d = datetime.strptime(yyyymmdd, "%Y%m%d").date() + timedelta(days=days)
    return d.strftime("%Y%m%d")


def _stats(series):
    return {
        "n": len(series),
        "mean": series.mean(),
        "median": series.median(),
        "win_rate": (series > 0).mean(),
    }


def report(signals, baseline, ret_cols, scan_start, scan_end, short, long):
    print()
    print(f"MA{short}/MA{long} golden-cross backtest")
    print(f"Scan window:  {scan_start} → {scan_end}")
    print(f"Signals:      {len(signals):,}")
    print(f"Baseline pool:{len(baseline):,}  (all stock-days on signal dates)")
    print()
    print(f"{'horizon':<10}{'signal mean':>14}{'signal median':>16}"
          f"{'signal win%':>14}{'baseline mean':>16}{'lift':>10}")
    print("-" * 80)
    for col in ret_cols:
        s_stats = _stats(signals[col])
        b_stats = _stats(baseline[col])
        lift = s_stats["mean"] - b_stats["mean"]
        print(
            f"{col:<10}"
            f"{s_stats['mean']*100:>13.2f}%"
            f"{s_stats['median']*100:>15.2f}%"
            f"{s_stats['win_rate']*100:>13.1f}%"
            f"{b_stats['mean']*100:>15.2f}%"
            f"{lift*100:>+9.2f}%"
        )


if __name__ == "__main__":
    args = sys.argv[1:]
    scan_start = args[0] if len(args) >= 1 else None
    scan_end = args[1] if len(args) >= 2 else None
    short = int(args[2]) if len(args) >= 3 else 20
    long = int(args[3]) if len(args) >= 4 else 60

    signals, baseline, ret_cols, scan_start, scan_end = backtest(
        short_window=short,
        long_window=long,
        scan_start=scan_start,
        scan_end=scan_end,
    )
    report(signals, baseline, ret_cols, scan_start, scan_end, short, long)
