"""b1 + 黄金坑 backtest — b1's 5 conditions AND gp_signal=1.

Same realistic execution model as `strategy.b1_backtest`:
  - Signal computed at close of day t.
  - Buy at open[t+1]. Stop reference = low[t+1].
  - if open[t+2] < low[t+1] → sell at open[t+2]  (held 1 day)
  - elif open[t+3] < low[t+1] → sell at open[t+3] (held 2 days)
  - else                      → sell at open[t+4] (forced exit, held 3 days)

Comparisons reported:
  1. b1_gp signals vs market baseline (every stock-day on the same signal dates)
  2. b1_gp signals vs plain b1 (the marginal effect of adding the gp filter)

The second comparison is the one to read: does adding gp_signal=1 improve
b1's edge, or just shrink the sample?

Usage:
    uv run python -m strategy.b1_gp_backtest                       # last 180 days
    uv run python -m strategy.b1_gp_backtest 20240901 20260514     # custom range
"""
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from indicators import golden_pit, kdj, zhixing
from store.db import connect
from strategy import loader

VOL_MA_PERIOD = 5
MA60_PERIOD = 60
J_THRESHOLD = 15


def _shift(yyyymmdd, days):
    d = datetime.strptime(yyyymmdd, "%Y%m%d").date() + timedelta(days=days)
    return d.strftime("%Y%m%d")


def backtest(scan_start=None, scan_end=None):
    latest = loader.latest_trade_date()
    if scan_end is None:
        scan_end = latest
    if scan_start is None:
        scan_start = _shift(scan_end, -180)

    load_start = _shift(scan_start, -int(MA60_PERIOD * 1.5) - 10)
    load_end = latest

    print(f"loading daily [{load_start} → {load_end}]...")
    with connect() as conn:
        d = pd.read_sql_query(
            "SELECT ts_code, trade_date, open, low, close, vol FROM daily "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY ts_code, trade_date",
            conn, params=[load_start, load_end],
        )
    print(f"loaded {len(d):,} rows / {d['ts_code'].nunique()} stocks")

    g = d.groupby("ts_code", sort=False)
    d["ma60"] = g["close"].rolling(MA60_PERIOD, min_periods=MA60_PERIOD).mean().droplevel(0)
    d["vol_ma5"] = g["vol"].rolling(VOL_MA_PERIOD, min_periods=VOL_MA_PERIOD).mean().droplevel(0)
    d["vol_ratio"] = d["vol"] / d["vol_ma5"]

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

    print("loading indicators + merging...")
    k = kdj.load(start=load_start, end=load_end)[["ts_code", "trade_date", "j"]]
    z = zhixing.load(start=load_start, end=load_end)[
        ["ts_code", "trade_date", "trend_short", "bull_bear"]
    ]
    gp = golden_pit.load(start=load_start, end=load_end)[
        ["ts_code", "trade_date", "signal"]
    ].rename(columns={"signal": "gp_signal"})

    df = (d.merge(k, on=["ts_code", "trade_date"], how="inner")
            .merge(z, on=["ts_code", "trade_date"], how="inner")
            .merge(gp, on=["ts_code", "trade_date"], how="inner"))

    b1_core = (
        (df["vol_ratio"] < 1.0)
        & (df["j"] < J_THRESHOLD)
        & (df["close"] > df["ma60"])
        & (df["trend_short"] > df["bull_bear"])
        & (df["close"] > df["bull_bear"])
    )
    df["b1_signal"] = b1_core
    df["b1_gp_signal"] = b1_core & (df["gp_signal"] == 1)

    needed = ["open_t1", "low_t1", "open_t2", "open_t3", "open_t4"]
    df = df.dropna(subset=needed)

    in_window = (df["trade_date"] >= scan_start) & (df["trade_date"] <= scan_end)
    b1_gp = df[df["b1_gp_signal"] & in_window].copy()
    b1_plain = df[df["b1_signal"] & in_window].copy()

    if b1_gp.empty:
        return b1_gp, b1_plain, df.iloc[0:0], scan_start, scan_end

    # Baseline: every stock-day on the dates where b1_gp fired (apples-to-apples
    # market drift control). Same as b1_backtest.py's baseline definition.
    signal_dates = b1_gp["trade_date"].unique()
    baseline = df[df["trade_date"].isin(signal_dates)]
    return b1_gp, b1_plain, baseline, scan_start, scan_end


def _stats(s):
    return {
        "n": len(s),
        "mean": s["actual_ret"].mean(),
        "median": s["actual_ret"].median(),
        "win": (s["actual_ret"] > 0).mean() if len(s) else float("nan"),
        "hold": s["holding_days"].mean() if len(s) else float("nan"),
    }


def _row(label, st, ref=None):
    diff_mean = f"{(st['mean']-ref['mean'])*100:>+9.2f}%" if ref else " " * 10
    diff_win = f"{(st['win']-ref['win'])*100:>+9.1f}%" if ref else " " * 10
    print(f"{label:<22}{st['n']:>10,}{st['mean']*100:>+10.2f}%"
          f"{st['median']*100:>+10.2f}%{st['win']*100:>+9.1f}%"
          f"{st['hold']:>9.2f}{diff_mean}{diff_win}")


def report(b1_gp, b1_plain, baseline, scan_start, scan_end):
    print()
    print("b1 + 黄金坑 backtest (realistic execution: buy open[t+1], stop low[t+1], force exit open[t+4])")
    print(f"Scan window:     {scan_start} → {scan_end}")
    print(f"b1+gp signals:   {len(b1_gp):,}")
    print(f"plain b1:        {len(b1_plain):,}  (b1+gp ⊆ plain b1, intersection = b1+gp)")
    print(f"Baseline pool:   {len(baseline):,}  (every stock-day on b1+gp signal dates)")
    if not b1_gp.empty:
        dates = b1_gp["trade_date"].nunique()
        print(f"Signal dates:    {dates}  (avg {len(b1_gp)/max(dates,1):.1f} b1+gp signals/day)")
    print()
    if b1_gp.empty:
        print("no b1+gp signals in window")
        return

    st_gp = _stats(b1_gp)
    st_b1 = _stats(b1_plain)
    st_base = _stats(baseline)

    print(f"{'cohort':<22}{'n':>10}{'mean':>11}{'median':>11}{'win':>10}{'hold':>9}"
          f"{'Δmean vs b1':>11}{'Δwin vs b1':>11}")
    print("-" * 95)
    _row("b1+gp (5 + gp=1)", st_gp, st_b1)
    _row("plain b1 (5 conds)", st_b1)
    _row("market baseline", st_base)

    print()
    print("Lift columns:")
    print(f"  b1+gp vs plain b1   mean: {(st_gp['mean']-st_b1['mean'])*100:+.2f}%   "
          f"win: {(st_gp['win']-st_b1['win'])*100:+.1f}%   "
          f"(marginal effect of the gp filter)")
    print(f"  b1+gp vs market     mean: {(st_gp['mean']-st_base['mean'])*100:+.2f}%   "
          f"win: {(st_gp['win']-st_base['win'])*100:+.1f}%   "
          f"(absolute edge over drift)")
    print(f"  plain b1 vs market  mean: {(st_b1['mean']-st_base['mean'])*100:+.2f}%   "
          f"win: {(st_b1['win']-st_base['win'])*100:+.1f}%   "
          f"(prior result: b1 is discarded, expected near-zero/negative)")

    print()
    print("Exit-kind breakdown (b1+gp signals vs baseline):")
    print(f"  {'kind':<12}{'b1+gp':>10}{'b1+gp %':>11}{'baseline %':>13}")
    s_kinds = b1_gp["exit_kind"].value_counts()
    b_kinds = baseline["exit_kind"].value_counts()
    for kind in ["stop_t2", "stop_t3", "force_t4"]:
        sn = int(s_kinds.get(kind, 0))
        sp = sn / len(b1_gp) * 100
        bp = int(b_kinds.get(kind, 0)) / len(baseline) * 100
        print(f"  {kind:<12}{sn:>10,}{sp:>10.1f}%{bp:>12.1f}%")


if __name__ == "__main__":
    args = sys.argv[1:]
    scan_start = args[0] if len(args) >= 1 else None
    scan_end = args[1] if len(args) >= 2 else None
    b1_gp, b1_plain, baseline, ss, se = backtest(scan_start=scan_start, scan_end=scan_end)
    report(b1_gp, b1_plain, baseline, ss, se)
