"""b1 parameter sweep — holding period + signal-threshold sensitivity.

Same execution model as `strategy.b1_backtest`:
  - buy at open[t+1]
  - stop reference price = low[t+1]
  - check stop at open[t+2], open[t+3], …, open[t+max_hold-1]
  - force exit at open[t+max_hold]

Two sweeps in one run:
  A. Vary max_hold ∈ {2..10}, fix default b1 thresholds (J<15, vol_ratio<1.0).
  B. Vary J cutoff, vol_ratio cutoff, optional minimum 成交额 (千元); fix max_hold=4.

Usage:
    uv run python -m strategy.b1_sweep                       # last 180 days
    uv run python -m strategy.b1_sweep 20240901 20260514     # custom range
"""
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from indicators import kdj, zhixing
from store.db import connect
from strategy import loader

VOL_MA_PERIOD = 5
MA60_PERIOD = 60
MAX_HOLD_CAP = 10  # how many forward bars to precompute


def _shift(yyyymmdd, days):
    d = datetime.strptime(yyyymmdd, "%Y%m%d").date() + timedelta(days=days)
    return d.strftime("%Y%m%d")


def _load(scan_start):
    latest = loader.latest_trade_date()
    load_start = _shift(scan_start, -int(MA60_PERIOD * 1.5) - 10)
    load_end = latest

    print(f"loading daily [{load_start} → {load_end}]...")
    with connect() as conn:
        d = pd.read_sql_query(
            "SELECT ts_code, trade_date, open, low, close, vol, amount FROM daily "
            "WHERE trade_date BETWEEN ? AND ? ORDER BY ts_code, trade_date",
            conn, params=[load_start, load_end],
        )
    print(f"loaded {len(d):,} rows / {d['ts_code'].nunique()} stocks")

    g = d.groupby("ts_code", sort=False)
    d["ma60"] = g["close"].rolling(MA60_PERIOD, min_periods=MA60_PERIOD).mean().droplevel(0)
    d["vol_ma5"] = g["vol"].rolling(VOL_MA_PERIOD, min_periods=VOL_MA_PERIOD).mean().droplevel(0)
    d["vol_ratio"] = d["vol"] / d["vol_ma5"]

    d["open_t1"] = g["open"].shift(-1)
    d["low_t1"] = g["low"].shift(-1)
    for k in range(2, MAX_HOLD_CAP + 1):
        d[f"open_t{k}"] = g["open"].shift(-k)

    print("loading indicators + merging...")
    k = kdj.load(start=load_start, end=load_end)[["ts_code", "trade_date", "j"]]
    z = zhixing.load(start=load_start, end=load_end)[
        ["ts_code", "trade_date", "trend_short", "bull_bear"]
    ]
    return (d.merge(k, on=["ts_code", "trade_date"], how="inner")
              .merge(z, on=["ts_code", "trade_date"], how="inner"))


def _exit(df, max_hold):
    """Return (actual_ret, holding_days) numpy arrays for a given max_hold (>=2)."""
    entry = df["open_t1"].to_numpy()
    # Default: forced exit at open[t+max_hold]
    exit_price = df[f"open_t{max_hold}"].to_numpy(copy=True)
    holding = np.full(len(df), max_hold - 1, dtype=float)
    # Earlier stops override later ones — iterate large-to-small so the smallest k wins
    low_t1 = df["low_t1"].to_numpy()
    for k in range(max_hold - 1, 1, -1):
        op_k = df[f"open_t{k}"].to_numpy()
        stop = op_k < low_t1  # NaN-safe: NaN < x → False
        exit_price = np.where(stop, op_k, exit_price)
        holding = np.where(stop, k - 1, holding)
    return (exit_price - entry) / entry, holding


def _signal(df, j_thr, vol_thr, amount_min):
    sig = ((df["vol_ratio"] < vol_thr)
           & (df["j"] < j_thr)
           & (df["close"] > df["ma60"])
           & (df["trend_short"] > df["bull_bear"])
           & (df["close"] > df["bull_bear"]))
    if amount_min is not None:
        sig &= df["amount"] > amount_min
    return sig.to_numpy()


def _stats(df, signal_mask, in_window, actual_ret, max_hold):
    needed_cols = ["open_t1", "low_t1"] + [f"open_t{k}" for k in range(2, max_hold + 1)]
    valid = df[needed_cols].notna().all(axis=1).to_numpy()

    sig_mask = signal_mask & in_window & valid
    if not sig_mask.any():
        return None
    sig_rets = actual_ret[sig_mask]
    sig_dates = df.loc[sig_mask, "trade_date"].unique()
    base_mask = df["trade_date"].isin(sig_dates).to_numpy() & valid
    base_rets = actual_ret[base_mask]

    return {
        "n_sig":      int(sig_mask.sum()),
        "n_base":     int(base_mask.sum()),
        "sig_mean":   float(np.nanmean(sig_rets)),
        "sig_win":    float(np.mean(sig_rets > 0)),
        "base_mean":  float(np.nanmean(base_rets)),
        "base_win":   float(np.mean(base_rets > 0)),
        "lift":       float(np.nanmean(sig_rets) - np.nanmean(base_rets)),
    }


def sweep_max_hold(df, scan_start, scan_end):
    print()
    print("Sweep A: holding period (b1 default thresholds: J<15, vol_ratio<1.0)")
    print(f"{'max_hold':>10}{'n_sig':>10}{'sig%':>11}{'base%':>11}{'lift':>11}"
          f"{'win%':>8}{'b_win%':>9}{'avg_days':>10}")
    print("-" * 80)
    in_window = ((df["trade_date"] >= scan_start) & (df["trade_date"] <= scan_end)).to_numpy()
    sig = _signal(df, j_thr=15, vol_thr=1.0, amount_min=None)
    for h in (2, 3, 4, 5, 7, 10):
        ret, hold_days = _exit(df, h)
        st = _stats(df, sig, in_window, ret, h)
        if st is None:
            print(f"{h:>10}  (no signals)")
            continue
        avg_hold = float(np.nanmean(hold_days[sig & in_window]))
        print(f"{h:>10}{st['n_sig']:>10,}{st['sig_mean']*100:>+10.2f}%"
              f"{st['base_mean']*100:>+10.2f}%{st['lift']*100:>+10.2f}%"
              f"{st['sig_win']*100:>7.1f}%{st['base_win']*100:>8.1f}%{avg_hold:>10.2f}")


def sweep_thresholds(df, scan_start, scan_end, max_hold=4):
    print()
    print(f"Sweep B: threshold tightness (max_hold={max_hold})")
    print(f"{'J<':>5}{'vol<':>7}{'amt>(千元)':>12}{'n_sig':>10}{'sig%':>11}"
          f"{'base%':>11}{'lift':>11}{'win%':>8}")
    print("-" * 76)
    in_window = ((df["trade_date"] >= scan_start) & (df["trade_date"] <= scan_end)).to_numpy()
    ret, _ = _exit(df, max_hold)

    # 30000 千元 = 3000 万 (modest liquidity); 100000 = 1 亿 (good liquidity)
    configs = [
        (15, 1.0, None),    # b1 default
        (10, 1.0, None),
        (5,  1.0, None),
        (15, 0.8, None),
        (15, 0.7, None),
        (15, 0.5, None),
        (5,  0.7, None),
        (5,  0.5, None),
        (15, 1.0, 30000),
        (15, 0.7, 30000),
        (5,  0.7, 30000),
        (5,  0.5, 30000),
        (5,  0.5, 100000),
    ]
    for j, vol, amt in configs:
        sig = _signal(df, j_thr=j, vol_thr=vol, amount_min=amt)
        st = _stats(df, sig, in_window, ret, max_hold)
        amt_str = f"{amt:,}" if amt else "—"
        if st is None:
            print(f"{j:>5}{vol:>7.2f}{amt_str:>12}  (no signals)")
            continue
        print(f"{j:>5}{vol:>7.2f}{amt_str:>12}{st['n_sig']:>10,}"
              f"{st['sig_mean']*100:>+10.2f}%{st['base_mean']*100:>+10.2f}%"
              f"{st['lift']*100:>+10.2f}%{st['sig_win']*100:>7.1f}%")


def main(scan_start=None, scan_end=None):
    latest = loader.latest_trade_date()
    if scan_end is None:
        scan_end = latest
    if scan_start is None:
        scan_start = _shift(scan_end, -180)

    df = _load(scan_start)
    print(f"\nScan window: {scan_start} → {scan_end}")

    sweep_max_hold(df, scan_start, scan_end)
    sweep_thresholds(df, scan_start, scan_end)


if __name__ == "__main__":
    args = sys.argv[1:]
    scan_start = args[0] if len(args) >= 1 else None
    scan_end = args[1] if len(args) >= 2 else None
    main(scan_start, scan_end)
