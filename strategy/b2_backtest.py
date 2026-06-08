"""b2 backtest with realistic execution model.

Strategy b2 signal: trend_short < bull_bear (from `indicators.zhixing`).
Tests whether the historical +20d lift seen in b1_attribution survives under
the realistic short-horizon execution model.

Trading rules (identical to strategy.b1_backtest):
  - Signal computed at close of day t.
  - Buy at open[t+1].
  - Stop reference price = low[t+1] (the low of the buy day).
  - During holding:
      if open[t+2] < low[t+1] → sell at open[t+2]
      elif open[t+3] < low[t+1] → sell at open[t+3]
      else                      → sell at open[t+4]  (forced)

Usage:
    uv run python -m strategy.b2_backtest                       # last 180 days
    uv run python -m strategy.b2_backtest 20240901 20260514     # custom range
"""
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from indicators import zhixing
from store.db import connect
from strategy import loader


def _shift(yyyymmdd, days):
    d = datetime.strptime(yyyymmdd, "%Y%m%d").date() + timedelta(days=days)
    return d.strftime("%Y%m%d")


def backtest(scan_start=None, scan_end=None):
    latest = loader.latest_trade_date()
    if scan_end is None:
        scan_end = latest
    if scan_start is None:
        scan_start = _shift(scan_end, -180)

    # 120 calendar days of lookback for indicator warm-up isn't required since
    # zhixing is already persisted, but we still need forward bars for execution.
    load_start = scan_start
    load_end = latest

    print(f"loading daily [{load_start} → {load_end}]...")
    with connect() as conn:
        d = pd.read_sql_query(
            "SELECT ts_code, trade_date, open, low FROM daily "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY ts_code, trade_date",
            conn, params=[load_start, load_end],
        )
    print(f"loaded {len(d):,} rows / {d['ts_code'].nunique()} stocks")

    g = d.groupby("ts_code", sort=False)
    d["open_t1"] = g["open"].shift(-1)
    d["low_t1"]  = g["low"].shift(-1)
    d["open_t2"] = g["open"].shift(-2)
    d["open_t3"] = g["open"].shift(-3)
    d["open_t4"] = g["open"].shift(-4)

    stop_t2 = d["open_t2"] < d["low_t1"]
    stop_t3 = (~stop_t2) & (d["open_t3"] < d["low_t1"])
    d["exit_price"] = np.where(
        stop_t2, d["open_t2"],
        np.where(stop_t3, d["open_t3"], d["open_t4"])
    )
    d["exit_kind"] = np.where(
        stop_t2, "stop_t2",
        np.where(stop_t3, "stop_t3", "force_t4")
    )
    d["holding_days"] = np.where(stop_t2, 1, np.where(stop_t3, 2, 3))
    d["actual_ret"] = (d["exit_price"] - d["open_t1"]) / d["open_t1"]

    print("loading zhixing + merging...")
    z = zhixing.load(start=load_start, end=load_end)[
        ["ts_code", "trade_date", "trend_short", "bull_bear"]
    ]
    df = d.merge(z, on=["ts_code", "trade_date"], how="inner")
    df["signal"] = df["trend_short"] < df["bull_bear"]

    needed = ["open_t1", "low_t1", "open_t2", "open_t3", "open_t4",
              "trend_short", "bull_bear"]
    df = df.dropna(subset=needed)

    in_window = (df["trade_date"] >= scan_start) & (df["trade_date"] <= scan_end)
    signals = df[df["signal"] & in_window].copy()

    if signals.empty:
        return signals, df.iloc[0:0], scan_start, scan_end

    signal_dates = signals["trade_date"].unique()
    baseline = df[df["trade_date"].isin(signal_dates)]
    return signals, baseline, scan_start, scan_end


def report(signals, baseline, scan_start, scan_end):
    print()
    print("b2 strategy backtest (realistic execution)")
    print(f"Signal:          trend_short < bull_bear")
    print(f"Scan window:     {scan_start} → {scan_end}")
    print(f"Signals:         {len(signals):,}")
    print(f"Baseline pool:   {len(baseline):,}")
    if not signals.empty:
        dates = signals["trade_date"].nunique()
        print(f"Signal dates:    {dates}  (avg {len(signals)/max(dates,1):.0f} signals/day)")
    print()
    if signals.empty:
        print("no signals in window")
        return

    s = signals["actual_ret"]
    b = baseline["actual_ret"]
    print(f"{'metric':<22}{'signal':>13}{'baseline':>13}{'diff':>12}")
    print("-" * 60)
    print(f"{'mean return':<22}"
          f"{s.mean()*100:>+12.2f}%{b.mean()*100:>+12.2f}%"
          f"{(s.mean()-b.mean())*100:>+11.2f}%")
    print(f"{'median return':<22}"
          f"{s.median()*100:>+12.2f}%{b.median()*100:>+12.2f}%"
          f"{(s.median()-b.median())*100:>+11.2f}%")
    print(f"{'win rate':<22}"
          f"{(s>0).mean()*100:>+12.1f}%{(b>0).mean()*100:>+12.1f}%"
          f"{((s>0).mean()-(b>0).mean())*100:>+11.1f}%")
    print(f"{'avg holding days':<22}"
          f"{signals['holding_days'].mean():>13.2f}"
          f"{baseline['holding_days'].mean():>13.2f}"
          f"{signals['holding_days'].mean()-baseline['holding_days'].mean():>+11.2f}")
    print()
    print("Exit-kind breakdown:")
    print(f"  {'kind':<12}{'signals':>10}{'sig %':>10}{'baseline %':>14}")
    s_kinds = signals["exit_kind"].value_counts()
    b_kinds = baseline["exit_kind"].value_counts()
    for kind in ["stop_t2", "stop_t3", "force_t4"]:
        sn = int(s_kinds.get(kind, 0))
        sp = sn / len(signals) * 100
        bp = int(b_kinds.get(kind, 0)) / len(baseline) * 100
        print(f"  {kind:<12}{sn:>10,}{sp:>9.1f}%{bp:>13.1f}%")


if __name__ == "__main__":
    args = sys.argv[1:]
    scan_start = args[0] if len(args) >= 1 else None
    scan_end = args[1] if len(args) >= 2 else None
    signals, baseline, ss, se = backtest(scan_start=scan_start, scan_end=scan_end)
    report(signals, baseline, ss, se)
