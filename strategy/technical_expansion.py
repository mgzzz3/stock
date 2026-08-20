"""Trailing-only features for breakout and multi-horizon trend strategies."""

from __future__ import annotations

import pandas as pd


BREAKOUT_LOOKBACK = 55
BREAKOUT_VOLUME_MULTIPLE = 1.5
TREND_FAST = 20
TREND_MID = 60
TREND_SLOW = 120
MIN_AMOUNT_20 = 100_000
PORTFOLIO_SIZE = 20
HOLDING_DAYS = 20


def add_features(frame: pd.DataFrame, *, copy: bool = True) -> pd.DataFrame:
    """Add price-adjusted features without looking beyond each row."""
    data = frame.copy() if copy else frame
    data["tech_adjusted_high"] = (
        data["r1_adjusted_close_index"] * data["high"] / data["close"]
    )
    grouped = data.groupby("ts_code", sort=False)
    previous_high = (
        grouped["tech_adjusted_high"]
        .rolling(BREAKOUT_LOOKBACK, min_periods=BREAKOUT_LOOKBACK)
        .max()
        .droplevel(0)
        .groupby(data["ts_code"], sort=False)
        .shift(1)
    )
    data["breakout_previous_high"] = previous_high
    data["breakout_volume_ratio"] = data["vol"] / (
        grouped["vol"].rolling(20, min_periods=20).mean().droplevel(0)
    )
    breakout_condition = (
        data["r1_adjusted_close_index"].gt(data["breakout_previous_high"])
        & data["breakout_volume_ratio"].ge(BREAKOUT_VOLUME_MULTIPLE)
        & data["r1_amount_20"].ge(MIN_AMOUNT_20)
        & data["r1_market_median_20"].gt(0)
    )
    previous_breakout = breakout_condition.groupby(data["ts_code"], sort=False).shift(1)
    data["breakout_signal"] = breakout_condition & ~previous_breakout.fillna(False).astype(bool)
    data["breakout_strength_pct"] = (
        data["r1_adjusted_close_index"] / data["breakout_previous_high"] - 1
    ) * 100

    for window in (TREND_FAST, TREND_MID, TREND_SLOW):
        data[f"trend_ma{window}"] = (
            grouped["r1_adjusted_close_index"]
            .rolling(window, min_periods=window)
            .mean()
            .droplevel(0)
        )
    data["trend_return_120"] = (
        data["r1_adjusted_close_index"]
        / grouped["r1_adjusted_close_index"].shift(TREND_SLOW)
        - 1
    )
    data["trend_volatility_20"] = (
        pd.to_numeric(data["pct_chg"], errors="coerce")
        .div(100)
        .groupby(data["ts_code"], sort=False)
        .rolling(20, min_periods=20)
        .std()
        .droplevel(0)
    )
    data["trend_ma120_prev20"] = grouped["trend_ma120"].shift(20)
    trend_condition = (
        data["trend_ma20"].gt(data["trend_ma60"])
        & data["trend_ma60"].gt(data["trend_ma120"])
        & data["trend_ma120"].gt(data["trend_ma120_prev20"])
        & data["trend_return_120"].gt(0)
        & data["r1_amount_20"].ge(MIN_AMOUNT_20)
        & data["r1_market_median_20"].gt(0)
    )
    previous_trend = trend_condition.groupby(data["ts_code"], sort=False).shift(1)
    data["trend_signal"] = trend_condition & ~previous_trend.fillna(False).astype(bool)
    data["trend_score"] = (
        data["trend_return_120"] / data["trend_volatility_20"].clip(lower=0.005)
    )
    return data


def cap_daily_signals(
    frame: pd.DataFrame,
    signal_column: str,
    score_column: str,
    limit: int = PORTFOLIO_SIZE,
) -> pd.Series:
    """Keep the strongest liquid signals per day with deterministic ties."""
    candidates = frame[frame[signal_column].fillna(False)].copy()
    if candidates.empty:
        return pd.Series(False, index=frame.index, dtype=bool)
    chosen = (
        candidates.sort_values(
            ["trade_date", score_column, "r1_amount_20", "ts_code"],
            ascending=[True, False, False, True],
        )
        .groupby("trade_date", sort=False)
        .head(limit)
    )
    return pd.Series(frame.index.isin(chosen.index), index=frame.index, dtype=bool)
