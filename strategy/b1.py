"""Strategy b1 — 5-condition pullback screen.

⚠ STATUS (2026-05-15): DISCARDED — no positive alpha sub-region.
Verified over 2024-09 to 2026-05 (20 months, 100K+ signals) via:
  - strategy.b1_backtest (open[t+1] entry, low[t+1] stop, force exit open[t+4])
  - strategy.b1_attribution (each condition individually + b1_mr inverse)
  - strategy.b1_sweep (max_hold ∈ {2..10}, threshold tightening)
Best case (max_hold=2): lift ≈ +0.01%, insufficient to cover transaction costs.
Tightening J/vol thresholds makes lift more negative, not less. The trend-
confirmation conditions (c3/c4/c5) are the source of negative alpha in
this mean-reversion regime — see strategy.b2 (c4 inverted) for the
follow-up hypothesis. Do not iterate on b1 without changing the trend
component fundamentally.

This file remains usable as a screen even though the strategy is discarded;
running it today still produces the 5-condition picks for inspection.

Filters the latest trade_date in the DB (or one passed via CLI) for stocks
satisfying ALL of:

  1. 缩量: vol < MA(vol, 5)                  -- volume below 5-day average
  2. KDJ J < 15                              -- oversold
  3. close > MA(close, 60)                   -- above long-term uptrend
  4. 知行短期趋势线 > 知行多空线              -- short trend above long trend
  5. close > 知行多空线                       -- price above long trend

KDJ and 知行 are read from their pre-computed tables (`indicators.kdj`,
`indicators.zhixing`). MA60 of close and MA5 of vol are computed inline.

Each run:
  - prints a summary + industry distribution + sorted hit table
  - writes `data/signals/b1_<date>.csv` (UTF-8 with BOM for Excel)
  - persists hits into the `signals` table (strategy='b1') for follow-up tracking
  - shows each hit's prior b1 signal date (within a 90-day lookback) and the
    number of trading days since that prior signal, so you can spot stocks
    that keep re-entering the pool

Usage:
    uv run python -m strategy.b1                  # latest trade_date in DB
    uv run python -m strategy.b1 20260514         # specific date
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from indicators import kdj, zhixing
from store import schema as _schema
from store import signals as signals_store
from store.db import connect
from strategy import loader

_schema.init_db()  # ensure `signals` table exists before persist()

VOL_MA_PERIOD = 5
MA60_PERIOD = 60
J_THRESHOLD = 15
LOOKBACK_DAYS = 90       # calendar days for "last signal" lookup
CSV_DIR = Path("data/signals")
STRATEGY_NAME = "b1"


def screen(on_date=None):
    on_date = on_date or loader.latest_trade_date()
    if on_date is None:
        raise RuntimeError("daily table is empty; run ingest.backfill first")

    # Two stacked windows of lookback:
    #   - LOOKBACK_DAYS calendar days back from on_date for the history search
    #   - 1.5 × MA60_PERIOD calendar days before that for MA warm-up
    end_dt = datetime.strptime(on_date, "%Y%m%d").date()
    history_start_dt = end_dt - timedelta(days=LOOKBACK_DAYS)
    load_start_dt = history_start_dt - timedelta(days=int(MA60_PERIOD * 1.5) + 10)
    load_start = load_start_dt.strftime("%Y%m%d")
    history_start = history_start_dt.strftime("%Y%m%d")

    with connect() as conn:
        d = pd.read_sql_query(
            "SELECT ts_code, trade_date, close, vol FROM daily "
            "WHERE trade_date >= ? AND trade_date <= ? "
            "ORDER BY ts_code, trade_date",
            conn, params=[load_start, on_date],
        )

    g = d.groupby("ts_code", sort=False)
    d["ma60"] = g["close"].rolling(MA60_PERIOD, min_periods=MA60_PERIOD).mean().droplevel(0)
    d["vol_ma5"] = g["vol"].rolling(VOL_MA_PERIOD, min_periods=VOL_MA_PERIOD).mean().droplevel(0)
    d["vol_ratio"] = d["vol"] / d["vol_ma5"]

    k = kdj.load(start=history_start, end=on_date)[["ts_code", "trade_date", "j"]]
    z = zhixing.load(start=history_start, end=on_date)[
        ["ts_code", "trade_date", "trend_short", "bull_bear"]
    ]
    df = (d.merge(k, on=["ts_code", "trade_date"], how="inner")
            .merge(z, on=["ts_code", "trade_date"], how="inner"))
    df = df.dropna(
        subset=["ma60", "vol_ma5", "vol_ratio", "j", "trend_short", "bull_bear"]
    )

    df["signal"] = (
        (df["vol_ratio"] < 1.0)
        & (df["j"] < J_THRESHOLD)
        & (df["close"] > df["ma60"])
        & (df["trend_short"] > df["bull_bear"])
        & (df["close"] > df["bull_bear"])
    )

    # Per-condition counts on the target day only
    today = df[df["trade_date"] == on_date]
    counts = {
        "1. 缩量 (vol < MA5)":        int((today["vol_ratio"] < 1.0).sum()),
        "2. KDJ J < 15":              int((today["j"] < J_THRESHOLD).sum()),
        "3. close > MA60":            int((today["close"] > today["ma60"]).sum()),
        "4. trend_short > bull_bear": int((today["trend_short"] > today["bull_bear"]).sum()),
        "5. close > bull_bear":       int((today["close"] > today["bull_bear"]).sum()),
    }

    hits = today[today["signal"]].copy()

    # History columns: latest prior signal date for each ts_code, and
    # trading-days-since computed from the unique trade dates we loaded.
    history = df[(df["trade_date"] < on_date) & df["signal"]]
    last_signal = history.groupby("ts_code")["trade_date"].max()
    hits["last_signal"] = hits["ts_code"].map(last_signal)

    trading_days = sorted(df["trade_date"].unique())
    date_idx = {d: i for i, d in enumerate(trading_days)}
    on_idx = date_idx.get(on_date)

    def _trading_days_since(d):
        if d is None or pd.isna(d) or d not in date_idx or on_idx is None:
            return None
        return on_idx - date_idx[d]

    hits["days_since"] = hits["last_signal"].apply(_trading_days_since).astype("Int64")

    names = loader.stock_names()
    hits = hits.merge(names, on="ts_code", how="left")

    # Sort: industry frequency (desc) → industry mean J (asc, more-oversold
    # industries first when frequencies tie) → J (asc) within industry.
    if not hits.empty:
        ind = hits["industry"].fillna("(unknown)")
        hits = hits.assign(
            _ic=ind.map(ind.value_counts()),
            _imj=hits.groupby(ind)["j"].transform("mean"),
        )
        hits = hits.sort_values(
            by=["_ic", "_imj", "j"],
            ascending=[False, True, True],
            na_position="last",
        ).drop(columns=["_ic", "_imj"])
    return hits, counts, len(today), on_date


_COLUMNS = [
    "ts_code", "name", "industry",
    "close", "vol_ratio", "j", "ma60", "trend_short", "bull_bear",
    "last_signal", "days_since",
]

_ROUND = {
    "close": 2, "vol_ratio": 2, "j": 1, "ma60": 2,
    "trend_short": 2, "bull_bear": 2,
}


def report(hits, counts, universe_n, on_date):
    print(f"Screen on {on_date}")
    print(f"Universe (stocks with all indicator data on {on_date}): {universe_n:,}")
    print()
    print("Individual condition pass counts:")
    for name, n in counts.items():
        print(f"  {name:<32}{n:>6}")
    print()
    print(f"Passing ALL 5 conditions: {len(hits)}")
    if hits.empty:
        return

    print()
    print("Industry distribution (top 10):")
    ind_counts = hits["industry"].fillna("(unknown)").value_counts()
    for industry, n in ind_counts.head(10).items():
        print(f"  {industry:<24}{n:>5}")
    if len(ind_counts) > 10:
        rest_total = int(ind_counts.iloc[10:].sum())
        rest_kinds = len(ind_counts) - 10
        print(f"  {f'others ({rest_kinds} industries)':<24}{rest_total:>5}")

    print()
    print("Stock detail (industry count desc → industry mean J asc → J asc within industry):")
    out = hits[_COLUMNS].round(_ROUND)
    print(out.to_string(index=False, na_rep="—"))


def save_csv(hits, on_date):
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    path = CSV_DIR / f"{STRATEGY_NAME}_{on_date}.csv"
    # utf-8-sig keeps Chinese characters legible in Excel without manual encoding fiddling
    hits[_COLUMNS].round(_ROUND).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def persist(hits, on_date):
    if hits.empty:
        return 0
    rows = ((ts, on_date, c) for ts, c in zip(hits["ts_code"], hits["close"]))
    return signals_store.upsert_many(STRATEGY_NAME, rows)


if __name__ == "__main__":
    on_date = sys.argv[1] if len(sys.argv) > 1 else None
    hits, counts, universe_n, used_date = screen(on_date)
    report(hits, counts, universe_n, used_date)
    print()
    if not hits.empty:
        path = save_csv(hits, used_date)
        print(f"CSV saved: {path}")
    n = persist(hits, used_date)
    print(f"Persisted to `signals` table: {n} rows  (strategy={STRATEGY_NAME}, trade_date={used_date})")
