"""Build the strategy decision dashboard consumed by the static web app.

The dashboard deliberately separates executable strategies from research
candidates.  Backtest statistics use only signals known at the close of day t
and executable prices from t+1 onward.

Run directly when a standalone payload is useful::

    python -m strategy.dashboard --output web/data/strategies.json
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import r1_reversal, technical_expansion, value_quality, zb1


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "stock.db"
DEFAULT_OUTPUT_PATH = ROOT / "web" / "data" / "strategies.json"
BACKTEST_CALENDAR_DAYS = 720
WARMUP_CALENDAR_DAYS = 220
ROUND_TRIP_COST = 0.002
MAX_RECOMMENDATIONS = 8
HISTORICAL_CASES_PER_OUTCOME = 4
WALK_FORWARD_TRAIN_DAYS = 252
WALK_FORWARD_TEST_DAYS = 21

WALK_FORWARD_GATES: dict[str, dict[str, float | int | bool]] = {
    "ma20_ma60": {
        "min_signal_count": 1_000,
        "min_net_mean": 0.0,
        "min_excess": 0.0,
        "min_win_rate": 0.50,
    },
    "b2_reversion": {
        "min_signal_count": 50_000,
        "min_net_mean": 0.0015,
        "min_excess": 0.001,
        "min_win_rate": 0.48,
    },
    "b1_pullback": {
        "min_signal_count": 5_000,
        "min_net_mean": 0.001,
        "min_excess": 0.001,
        "min_win_rate": 0.48,
    },
    "r1_reversal": {
        "min_signal_count": 60,
        "min_net_mean": 0.0,
        "min_excess": 0.0,
        "min_win_rate": 0.45,
    },
    "breakout_55": {
        "min_signal_count": 200,
        "min_net_mean": 0.0,
        "min_excess": 0.0,
        "min_win_rate": 0.48,
    },
    "trend_alignment": {
        "min_signal_count": 200,
        "min_net_mean": 0.0,
        "min_excess": 0.0,
        "min_win_rate": 0.48,
    },
    "value_quality": {
        "min_signal_count": 40,
        "min_net_mean": 0.0,
        "min_excess": 0.0,
        "min_win_rate": 0.50,
    },
}


def _shift_date(value: str, days: int) -> str:
    date = datetime.strptime(value, "%Y%m%d").date() + timedelta(days=days)
    return date.strftime("%Y%m%d")


def _round(value: object, digits: int = 2) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _add_curve_leg(
    aggregates: list[pd.DataFrame],
    dates: pd.Series,
    returns: pd.Series,
    mask: pd.Series,
) -> None:
    valid = mask & dates.notna() & returns.notna() & np.isfinite(returns)
    if not valid.any():
        return
    leg = pd.DataFrame(
        {
            "trade_date": dates.loc[valid].astype(str).to_numpy(),
            "return": returns.loc[valid].astype(float).to_numpy(),
        }
    )
    aggregates.append(
        leg.groupby("trade_date", sort=True)["return"]
        .agg(return_sum="sum", position_count="count")
    )


def _curve_from_aggregates(aggregates: list[pd.DataFrame]) -> dict[str, object]:
    if not aggregates:
        return {"points": [], "max_drawdown_pct": None, "latest_nav": None}

    combined = pd.concat(aggregates).groupby(level=0).sum().sort_index()
    daily_return = combined["return_sum"] / combined["position_count"]
    daily_return = daily_return.clip(lower=-0.95)
    nav = (1 + daily_return).cumprod()
    # Starting cash (NAV=1.0) is a real peak.  Without this floor, a strategy
    # that loses money from its very first trade would incorrectly report 0%
    # drawdown until it later made a new local high.
    drawdown = nav / nav.cummax().clip(lower=1.0) - 1
    points = [
        {
            "date": str(date),
            "nav": round(float(nav.loc[date]), 6),
            "drawdown_pct": round(float(drawdown.loc[date]) * 100, 3),
            "daily_return_pct": round(float(daily_return.loc[date]) * 100, 3),
        }
        for date in nav.index
    ]
    return {
        "points": points,
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
        "latest_nav": round(float(nav.iloc[-1]), 4),
    }


def _fixed_holding_curve(
    frame: pd.DataFrame,
    signal_mask: pd.Series,
    scan_start: str,
    holding_days: int,
) -> dict[str, object]:
    """Return a daily equal-weight curve for next-open/fixed-close trades."""
    grouped = frame.groupby("ts_code", sort=False)
    aggregates: list[pd.DataFrame] = []
    base_mask = signal_mask & frame["trade_date"].between(scan_start, frame["trade_date"].max())
    previous_close: pd.Series | None = None

    for offset in range(1, holding_days + 1):
        close_at_offset = grouped["close"].shift(-offset)
        target_dates = grouped["trade_date"].shift(-offset)
        if offset == 1:
            denominator = grouped["open"].shift(-1)
            leg_return = close_at_offset / denominator - 1 - ROUND_TRIP_COST
        else:
            if previous_close is None:
                raise AssertionError("previous close must exist after the first holding day")
            leg_return = close_at_offset / previous_close - 1
        _add_curve_leg(aggregates, target_dates, leg_return, base_mask)
        previous_close = close_at_offset

    return _curve_from_aggregates(aggregates)


def _open_exit_curve(
    frame: pd.DataFrame,
    signal_mask: pd.Series,
    scan_start: str,
    holding_days: int,
    *,
    open_column: str = "open",
    close_column: str = "close",
) -> dict[str, object]:
    """Daily curve for next-open entry and open exit after N full days."""
    grouped = frame.groupby("ts_code", sort=False)
    aggregates: list[pd.DataFrame] = []
    base_mask = signal_mask & frame["trade_date"].between(scan_start, frame["trade_date"].max())
    previous_close: pd.Series | None = None
    for offset in range(1, holding_days + 1):
        close_at_offset = grouped[close_column].shift(-offset)
        target_dates = grouped["trade_date"].shift(-offset)
        if offset == 1:
            denominator = grouped[open_column].shift(-1)
            leg_return = close_at_offset / denominator - 1 - ROUND_TRIP_COST
        else:
            if previous_close is None:
                raise AssertionError("previous close must exist after the first holding day")
            leg_return = close_at_offset / previous_close - 1
        _add_curve_leg(aggregates, target_dates, leg_return, base_mask)
        previous_close = close_at_offset

    exit_open = grouped[open_column].shift(-(holding_days + 1))
    exit_date = grouped["trade_date"].shift(-(holding_days + 1))
    if previous_close is not None:
        _add_curve_leg(
            aggregates,
            exit_date,
            exit_open / previous_close - 1,
            base_mask,
        )
    return _curve_from_aggregates(aggregates)


def _sparse_open_exit_curve(
    frame: pd.DataFrame,
    signal_mask: pd.Series,
    scan_start: str,
    holding_days: int,
    *,
    open_column: str = "open",
    close_column: str = "close",
) -> dict[str, object]:
    """Build an open-to-open curve by iterating only selected sparse trades."""
    totals: dict[str, list[float | int]] = {}
    eligible = signal_mask & frame["trade_date"].ge(scan_start)
    for _, group in frame.groupby("ts_code", sort=False):
        group_signal = eligible.loc[group.index].to_numpy(dtype=bool)
        positions = np.flatnonzero(group_signal)
        if not len(positions):
            continue
        dates = group["trade_date"].astype(str).to_numpy()
        opens = pd.to_numeric(group[open_column], errors="coerce").to_numpy(float)
        closes = pd.to_numeric(group[close_column], errors="coerce").to_numpy(float)
        for signal_position in positions:
            entry = signal_position + 1
            exit_position = signal_position + holding_days + 1
            if exit_position >= len(group):
                continue
            legs: list[tuple[str, float]] = []
            first_return = closes[entry] / opens[entry] - 1 - ROUND_TRIP_COST
            legs.append((dates[entry], first_return))
            for position in range(entry + 1, signal_position + holding_days + 1):
                legs.append((dates[position], closes[position] / closes[position - 1] - 1))
            legs.append(
                (
                    dates[exit_position],
                    opens[exit_position] / closes[signal_position + holding_days] - 1,
                )
            )
            for date, value in legs:
                if not np.isfinite(value):
                    continue
                aggregate = totals.setdefault(date, [0.0, 0])
                aggregate[0] = float(aggregate[0]) + float(value)
                aggregate[1] = int(aggregate[1]) + 1
    if not totals:
        return {"points": [], "max_drawdown_pct": None, "latest_nav": None}
    aggregate = pd.DataFrame.from_dict(
        totals,
        orient="index",
        columns=["return_sum", "position_count"],
    ).sort_index()
    return _curve_from_aggregates([aggregate])


def _signal_mask_from_pairs(frame: pd.DataFrame, pairs: pd.DataFrame) -> pd.Series:
    if pairs.empty:
        return pd.Series(False, index=frame.index, dtype=bool)
    frame_pairs = pd.MultiIndex.from_frame(frame[["ts_code", "trade_date"]])
    selected_pairs = pd.MultiIndex.from_frame(
        pairs[["ts_code", "trade_date"]].drop_duplicates()
    )
    return pd.Series(frame_pairs.isin(selected_pairs), index=frame.index, dtype=bool)


def _stopped_curve(
    frame: pd.DataFrame,
    signal_mask: pd.Series,
    scan_start: str,
) -> dict[str, object]:
    """Daily curve for the existing B1/B2 stop and forced-exit rules."""
    grouped = frame.groupby("ts_code", sort=False)
    base_mask = signal_mask & frame["trade_date"].between(scan_start, frame["trade_date"].max())
    aggregates: list[pd.DataFrame] = []

    open_t1 = grouped["open"].shift(-1)
    close_t1 = grouped["close"].shift(-1)
    close_t2 = grouped["close"].shift(-2)
    close_t3 = grouped["close"].shift(-3)
    date_t1 = grouped["trade_date"].shift(-1)
    date_t2 = grouped["trade_date"].shift(-2)
    date_t3 = grouped["trade_date"].shift(-3)
    date_t4 = grouped["trade_date"].shift(-4)

    stop_t2 = frame["stop_t2"].fillna(False)
    stop_t3 = frame["stop_t3"].fillna(False)
    _add_curve_leg(
        aggregates,
        date_t1,
        close_t1 / open_t1 - 1 - ROUND_TRIP_COST,
        base_mask,
    )
    day2_exit = frame["open_t2"].where(stop_t2, close_t2)
    _add_curve_leg(aggregates, date_t2, day2_exit / close_t1 - 1, base_mask)

    active_day3 = base_mask & ~stop_t2
    day3_exit = frame["open_t3"].where(stop_t3, close_t3)
    _add_curve_leg(aggregates, date_t3, day3_exit / close_t2 - 1, active_day3)

    active_day4 = base_mask & ~stop_t2 & ~stop_t3
    _add_curve_leg(
        aggregates,
        date_t4,
        frame["open_t4"] / close_t3 - 1,
        active_day4,
    )
    return _curve_from_aggregates(aggregates)


def _event_metrics(
    signals: pd.DataFrame,
    baseline: pd.DataFrame,
    return_column: str,
    curve: dict[str, object],
    scan_start: str,
    scan_end: str,
) -> dict[str, object]:
    returns = signals[return_column].dropna().astype(float)
    baseline_returns = baseline[return_column].dropna().astype(float)
    actual_start = str(signals["trade_date"].min()) if not signals.empty else scan_start
    actual_end = str(signals["trade_date"].max()) if not signals.empty else scan_end
    if returns.empty:
        return {
            "period_start": actual_start,
            "period_end": actual_end,
            "signal_count": 0,
            "signal_dates": 0,
            "mean_return_pct": None,
            "net_mean_return_pct": None,
            "median_return_pct": None,
            "win_rate_pct": None,
            "baseline_return_pct": None,
            "excess_return_pct": None,
            "max_drawdown_pct": curve.get("max_drawdown_pct"),
            "latest_nav": curve.get("latest_nav"),
        }

    mean_return = float(returns.mean())
    baseline_mean = float(baseline_returns.mean()) if not baseline_returns.empty else math.nan
    return {
        "period_start": actual_start,
        "period_end": actual_end,
        "signal_count": int(len(returns)),
        "signal_dates": int(signals["trade_date"].nunique()),
        "mean_return_pct": round(mean_return * 100, 2),
        "net_mean_return_pct": round((mean_return - ROUND_TRIP_COST) * 100, 2),
        "median_return_pct": round(float(returns.median()) * 100, 2),
        "win_rate_pct": round(float((returns > 0).mean()) * 100, 1),
        "baseline_return_pct": None if math.isnan(baseline_mean) else round(baseline_mean * 100, 2),
        "excess_return_pct": None if math.isnan(baseline_mean) else round((mean_return - baseline_mean) * 100, 2),
        "max_drawdown_pct": curve.get("max_drawdown_pct"),
        "latest_nav": curve.get("latest_nav"),
    }


def _cash_curve(trade_dates: list[str]) -> dict[str, object]:
    points = [
        {"date": str(date), "nav": 1.0, "drawdown_pct": 0.0, "daily_return_pct": 0.0}
        for date in trade_dates
    ]
    return {
        "points": points,
        "max_drawdown_pct": 0.0 if points else None,
        "latest_nav": 1.0 if points else None,
    }


def _walk_forward_selection(
    frame: pd.DataFrame,
    signal_mask: pd.Series,
    return_column: str,
    exit_index: pd.Series,
    scan_start: str,
    gate: dict[str, float | int | bool],
    *,
    training_days: int = WALK_FORWARD_TRAIN_DAYS,
    test_days: int = WALK_FORWARD_TEST_DAYS,
) -> tuple[pd.Series, dict[str, object]]:
    """Select strictly out-of-sample signals with a rolling training gate.

    A training trade is eligible only when its exit index is strictly before
    the next test window.  This embargo prevents a trade opened during the
    training window from contributing an outcome that was not yet known when
    the test window began.
    """
    selected = pd.Series(False, index=frame.index, dtype=bool)
    analysis = frame[frame["trade_date"] >= scan_start]
    analysis_indices = sorted(int(value) for value in analysis["trade_index"].unique())
    all_dates = (
        frame[["trade_index", "trade_date"]]
        .drop_duplicates("trade_index")
        .set_index("trade_index")["trade_date"]
        .astype(str)
        .to_dict()
    )
    if len(analysis_indices) <= training_days:
        return selected, {
            "training_days": training_days,
            "test_days": test_days,
            "windows": [],
            "test_dates": [],
            "latest_approved": False,
        }

    windows: list[dict[str, object]] = []
    test_date_values: list[str] = []
    min_signal_count = int(gate.get("min_signal_count", 0))
    min_net_mean = float(gate.get("min_net_mean", 0))
    min_excess = float(gate.get("min_excess", 0))
    min_win_rate = float(gate.get("min_win_rate", 0))
    for test_offset in range(training_days, len(analysis_indices), test_days):
        test_slice = analysis_indices[test_offset : test_offset + test_days]
        if not test_slice:
            continue
        training_slice = analysis_indices[test_offset - training_days : test_offset]
        train_start_index = training_slice[0]
        test_start_index = test_slice[0]
        test_end_index = test_slice[-1]

        training_mask = (
            signal_mask
            & frame["trade_index"].between(train_start_index, training_slice[-1])
            & frame[return_column].notna()
            & exit_index.notna()
            & exit_index.lt(test_start_index)
        )
        training_returns = frame.loc[training_mask, return_column].astype(float)
        training_signal_dates = frame.loc[training_mask, "trade_index"].unique()
        baseline_mask = (
            frame["trade_index"].isin(training_signal_dates)
            & frame[return_column].notna()
            & exit_index.notna()
            & exit_index.lt(test_start_index)
        )
        baseline_returns = frame.loc[baseline_mask, return_column].astype(float)

        signal_count = int(len(training_returns))
        gross_mean = float(training_returns.mean()) if signal_count else math.nan
        net_mean = gross_mean - ROUND_TRIP_COST if signal_count else math.nan
        baseline_mean = float(baseline_returns.mean()) if len(baseline_returns) else math.nan
        excess = gross_mean - baseline_mean if signal_count and not math.isnan(baseline_mean) else math.nan
        win_rate = float((training_returns > 0).mean()) if signal_count else math.nan
        approved = (
            signal_count >= min_signal_count
            and not math.isnan(net_mean)
            and net_mean >= min_net_mean
            and not math.isnan(excess)
            and excess >= min_excess
            and not math.isnan(win_rate)
            and win_rate >= min_win_rate
        )

        test_mask = signal_mask & frame["trade_index"].between(test_start_index, test_end_index)
        if approved:
            selected |= test_mask
        test_date_values.extend(all_dates[index] for index in test_slice if index in all_dates)
        windows.append(
            {
                "training_start": all_dates.get(train_start_index),
                "training_end": all_dates.get(training_slice[-1]),
                "test_start": all_dates.get(test_start_index),
                "test_end": all_dates.get(test_end_index),
                "training_signal_count": signal_count,
                "training_net_mean_return_pct": None if math.isnan(net_mean) else round(net_mean * 100, 2),
                "training_excess_return_pct": None if math.isnan(excess) else round(excess * 100, 2),
                "training_win_rate_pct": None if math.isnan(win_rate) else round(win_rate * 100, 1),
                "approved": bool(approved),
                "test_signal_count": int(test_mask.sum()),
            }
        )

    return selected, {
        "training_days": training_days,
        "test_days": test_days,
        "windows": windows,
        "test_dates": test_date_values,
        "latest_approved": bool(windows and windows[-1]["approved"]),
    }


def _walk_forward_payload(
    selection: dict[str, object],
    selected_mask: pd.Series,
    frame: pd.DataFrame,
    return_column: str,
    curve: dict[str, object],
    gate: dict[str, float | int | bool],
    curve_method: str,
) -> dict[str, object]:
    windows = list(selection.get("windows", []))
    completed = selected_mask & frame[return_column].notna()
    completed_returns = frame.loc[completed, return_column].astype(float)
    enabled_windows = sum(bool(window.get("approved")) for window in windows)
    latest_window = windows[-1] if windows else None
    return {
        "training_days": int(selection.get("training_days", WALK_FORWARD_TRAIN_DAYS)),
        "test_days": int(selection.get("test_days", WALK_FORWARD_TEST_DAYS)),
        "embargo_rule": "训练交易必须在测试窗口开始前完成退出",
        "gate": {
            "min_signal_count": int(gate.get("min_signal_count", 0)),
            "min_net_mean_return_pct": round(float(gate.get("min_net_mean", 0)) * 100, 2),
            "min_excess_return_pct": round(float(gate.get("min_excess", 0)) * 100, 2),
            "min_win_rate_pct": round(float(gate.get("min_win_rate", 0)) * 100, 1),
        },
        "metrics": {
            "period_start": windows[0]["test_start"] if windows else None,
            "period_end": windows[-1]["test_end"] if windows else None,
            "total_windows": len(windows),
            "enabled_windows": enabled_windows,
            "oos_signal_count": int(selected_mask.sum()),
            "completed_oos_signal_count": int(completed.sum()),
            "oos_mean_return_pct": None if completed_returns.empty else round(float(completed_returns.mean() - ROUND_TRIP_COST) * 100, 2),
            "max_drawdown_pct": curve.get("max_drawdown_pct"),
            "latest_nav": curve.get("latest_nav"),
            "total_return_pct": None if curve.get("latest_nav") is None else round((float(curve["latest_nav"]) - 1) * 100, 2),
            "latest_approved": bool(selection.get("latest_approved", False)),
        },
        "latest_window": latest_window,
        "windows": windows,
        "curve": curve.get("points", []),
        "curve_method": curve_method,
    }


def _load_sector_scores(conn: sqlite3.Connection, as_of_date: str) -> dict[str, dict[str, float | int]]:
    if "sector_ranking_history" not in _table_names(conn):
        return {}
    rows = conn.execute(
        """SELECT industry, score, rank
           FROM sector_ranking_history
           WHERE trade_date = ?
           ORDER BY rank""",
        (as_of_date,),
    ).fetchall()
    return {
        str(row[0]): {"score": float(row[1] or 0), "rank": int(row[2] or 999)}
        for row in rows
    }


def _stock_lookup(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT ts_code, name, industry FROM stock_basic",
        conn,
    )


def _safe_stock_name(value: object) -> bool:
    name = str(value or "").upper()
    return "ST" not in name and "退" not in name


def _case_reasons(
    strategy_id: str,
    row: pd.Series,
    value_details: dict[tuple[str, str], object] | None = None,
) -> list[str]:
    """Describe only values that were available on the signal date."""
    if strategy_id == "r1_reversal":
        return [
            f"三月形成期收益 {float(row['r1_formation_return']) * 100:.1f}%，进入月末错杀组",
            f"市场20日中位收益 {float(row['r1_market_median_20']) * 100:.1f}%，市场门控开启",
            f"20日均成交额 {float(row['r1_amount_20']) / 100_000:.1f} 亿元",
        ]
    if strategy_id == "breakout_55":
        return [
            f"收盘突破前55日高点 {float(row['breakout_strength_pct']):.1f}%",
            f"成交量为20日均量 {float(row['breakout_volume_ratio']):.2f} 倍",
            f"市场20日中位收益 {float(row['r1_market_median_20']) * 100:.1f}%",
        ]
    if strategy_id == "trend_alignment":
        return [
            "MA20 > MA60 > MA120，且 MA120 较20日前上行",
            f"120日收益 {float(row['trend_return_120']) * 100:.1f}%",
            f"20日均成交额 {float(row['r1_amount_20']) / 100_000:.1f} 亿元，市场门控开启",
        ]
    if strategy_id == "value_quality":
        details = (value_details or {}).get((str(row["ts_code"]), str(row["trade_date"])))
        if details is None:
            return ["点时财报质量、现金流与合理估值筛选通过"]
        return [
            f"近3年 ROE 中位数 {float(details.roe_3y_median):.1f}%、最低 {float(details.roe_3y_min):.1f}%",
            f"营收/净利增速中位数 {float(details.revenue_yoy_3y_median):.1f}%/{float(details.net_profit_yoy_3y_median):.1f}%",
            f"PE 代理 {float(details.pe_proxy):.1f}、PB 代理 {float(details.pb_proxy):.1f}，经营现金流连续3年为正",
        ]
    if strategy_id == "ma20_ma60":
        return [
            f"前一日 MA20 {float(row['ma20_prev']):.2f} ≤ MA60 {float(row['ma60_prev']):.2f}",
            f"信号日 MA20 {float(row['ma20']):.2f} > MA60 {float(row['ma60']):.2f}",
            "信号收盘确认，次日开盘进入回测",
        ]
    if strategy_id == "b2_reversion":
        gap_pct = (
            (float(row["bull_bear"]) - float(row["trend_short"]))
            / float(row["bull_bear"])
            * 100
        )
        return [
            f"短趋势线低于多空线 {gap_pct:.1f}%",
            "满足 B2 趋势下方反转原始信号",
            "次日开盘进入，按买入日低点止损或最迟第4日开盘退出",
        ]
    volume_ratio = float(row["vol"]) / float(row["vol_ma5"])
    return [
        f"J 值 {float(row['j']):.1f} < 15，处于超卖区",
        f"成交量为5日均量 {volume_ratio:.2f} 倍，属于缩量",
        "收盘在 MA60 和多空线上方，短趋势高于多空线",
    ]


def _historical_cases(
    frame: pd.DataFrame,
    signal_mask: pd.Series,
    oos_mask: pd.Series,
    return_column: str,
    exit_index: pd.Series,
    scan_start: str,
    stock_lookup: pd.DataFrame,
    date_by_index: dict[int, str],
    strategy_id: str,
    *,
    value_details: dict[tuple[str, str], object] | None = None,
) -> dict[str, object]:
    """Return recent completed wins and losses without cherry-picking magnitude."""
    completed = (
        signal_mask
        & frame["trade_date"].ge(scan_start)
        & frame[return_column].notna()
        & frame["entry_index"].notna()
        & exit_index.notna()
    )
    completed_returns = frame.loc[completed, return_column].astype(float)
    net_returns = completed_returns - ROUND_TRIP_COST
    win_count = int(net_returns.gt(0).sum())
    loss_count = int(net_returns.le(0).sum())
    lookup = stock_lookup.drop_duplicates("ts_code").set_index("ts_code")

    def rows_for(outcome: str) -> list[dict[str, object]]:
        outcome_mask = net_returns.gt(0) if outcome == "win" else net_returns.le(0)
        indices = net_returns.index[outcome_mask]
        if indices.empty:
            return []
        recent = frame.loc[indices, ["trade_date", "ts_code"]].copy()
        recent = recent.sort_values(
            ["trade_date", "ts_code"],
            ascending=[False, True],
        ).head(HISTORICAL_CASES_PER_OUTCOME)
        cases = []
        for index in recent.index:
            row = frame.loc[index]
            ts_code = str(row["ts_code"])
            stock = lookup.loc[ts_code] if ts_code in lookup.index else None
            name = str(stock["name"] or ts_code) if stock is not None else ts_code
            industry = str(stock["industry"] or "未分类") if stock is not None else "未分类"
            exit_reason = None
            if strategy_id in {"b1_pullback", "b2_reversion"}:
                if bool(row.get("stop_t2", False)):
                    exit_reason = "第2日开盘触发止损"
                elif bool(row.get("stop_t3", False)):
                    exit_reason = "第3日开盘触发止损"
                else:
                    exit_reason = "第4日开盘到期退出"
            elif strategy_id == "value_quality":
                exit_reason = "持有63个交易日后开盘退出"
            elif strategy_id == "ma20_ma60":
                exit_reason = "持有至第20个交易日收盘"
            else:
                exit_reason = "持有20个交易日后开盘退出"
            gross_return = float(row[return_column])
            cases.append(
                {
                    "outcome": outcome,
                    "outcome_label": "盈利" if outcome == "win" else "亏损",
                    "ts_code": ts_code,
                    "name": name,
                    "industry": industry,
                    "signal_date": str(row["trade_date"]),
                    "entry_date": date_by_index.get(int(row["entry_index"])),
                    "exit_date": date_by_index.get(int(exit_index.loc[index])),
                    "gross_return_pct": round(gross_return * 100, 2),
                    "net_return_pct": round((gross_return - ROUND_TRIP_COST) * 100, 2),
                    "evidence_scope": "rolling_oos" if bool(oos_mask.loc[index]) else "full_sample",
                    "evidence_label": "滚动样本外" if bool(oos_mask.loc[index]) else "全样本参考",
                    "exit_reason": exit_reason,
                    "reasons": _case_reasons(strategy_id, row, value_details),
                }
            )
        return cases

    return {
        "definition": "最近已完成退出的4笔盈利与4笔亏损；收益已扣除0.20%往返成本。",
        "completed_count": int(completed.sum()),
        "win_count": win_count,
        "loss_count": loss_count,
        "wins": rows_for("win"),
        "losses": rows_for("loss"),
    }


def _credibility_payload(
    frame: pd.DataFrame,
    signal_mask: pd.Series,
    oos_mask: pd.Series,
    return_column: str,
    scan_start: str,
    as_of_date: str,
    walk_forward: dict[str, object],
) -> dict[str, object]:
    completed = (
        signal_mask
        & frame["trade_date"].between(scan_start, as_of_date)
        & frame[return_column].notna()
    )
    oos_completed = oos_mask & frame[return_column].notna()
    rows = frame.loc[completed, ["ts_code", "trade_date"]]
    metrics = walk_forward.get("metrics", {})
    enabled_windows = int(metrics.get("enabled_windows") or 0)
    total_windows = int(metrics.get("total_windows") or 0)
    oos_count = int(oos_completed.sum())
    return {
        "evidence_level": "rolling_oos" if oos_count else "full_sample_only",
        "evidence_label": "存在滚动样本外交易" if oos_count else "仅全样本参考",
        "price_history_start": scan_start,
        "price_history_end": as_of_date,
        "history_years": round(
            (datetime.strptime(as_of_date, "%Y%m%d") - datetime.strptime(scan_start, "%Y%m%d")).days
            / 365.25,
            1,
        ),
        "completed_trade_count": int(completed.sum()),
        "unique_stock_count": int(rows["ts_code"].nunique()) if not rows.empty else 0,
        "signal_date_count": int(rows["trade_date"].nunique()) if not rows.empty else 0,
        "oos_completed_trade_count": oos_count,
        "enabled_windows": enabled_windows,
        "total_windows": total_windows,
        "sample_warning": "股票×日期信号可能连续重复，不应把全部信号视为相互独立样本。",
    }


def _golden_recommendations(
    current: pd.DataFrame,
    stock_lookup: pd.DataFrame,
    sector_scores: dict[str, dict[str, float | int]],
) -> list[dict[str, object]]:
    if current.empty:
        return []
    rows = current.merge(stock_lookup, on="ts_code", how="left")
    rows["amount"] = pd.to_numeric(rows["amount"], errors="coerce")
    rows["pct_chg"] = pd.to_numeric(rows["pct_chg"], errors="coerce")
    rows["extension_pct"] = (rows["close"] / rows["ma60"] - 1) * 100
    rows["liquidity_billion"] = rows["amount"] / 100_000
    rows = rows[
        rows["name"].map(_safe_stock_name)
        & rows["amount"].ge(50_000)
        & rows["pct_chg"].between(-5, 8)
        & rows["extension_pct"].between(0, 12)
    ].copy()
    if rows.empty:
        return []

    rows["sector_score"] = rows["industry"].map(
        lambda value: float(sector_scores.get(str(value), {}).get("score", 0))
    )
    rows["sector_rank"] = rows["industry"].map(
        lambda value: int(sector_scores.get(str(value), {}).get("rank", 999))
    )
    rows["recommendation_score"] = (
        rows["sector_score"] * 50
        + rows["sector_rank"].le(10).astype(float) * 18
        + rows["liquidity_billion"].clip(upper=12) * 1.5
        - (rows["extension_pct"] - 3).abs() * 1.2
        - (rows["pct_chg"] - 5).clip(lower=0) * 2
    )
    rows = rows.sort_values(
        ["recommendation_score", "amount", "ts_code"],
        ascending=[False, False, True],
    ).head(MAX_RECOMMENDATIONS)

    recommendations = []
    for rank, (_, row) in enumerate(rows.iterrows(), start=1):
        reasons = ["MA20 今日上穿 MA60"]
        if int(row["sector_rank"]) <= 10:
            reasons.append(f"行业主线排名第 {int(row['sector_rank'])}")
        reasons.append(f"成交额 {float(row['liquidity_billion']):.1f} 亿")
        reasons.append(f"收盘高于 MA60 {float(row['extension_pct']):.1f}%")
        recommendations.append(
            {
                "rank": rank,
                "ts_code": str(row["ts_code"]),
                "name": str(row.get("name") or row["ts_code"]),
                "industry": str(row.get("industry") or "未分类"),
                "close": _round(row["close"]),
                "pct_chg": _round(row["pct_chg"]),
                "amount_billion": _round(row["liquidity_billion"], 1),
                "ma20": _round(row["ma20"]),
                "ma60": _round(row["ma60"]),
                "sector_rank": None if int(row["sector_rank"]) == 999 else int(row["sector_rank"]),
                "score": _round(row["recommendation_score"], 1),
                "action": "次日候选买入",
                "trigger": "高开不超过 3%",
                "reasons": reasons,
            }
        )
    return recommendations


def _b2_observations(
    current: pd.DataFrame,
    stock_lookup: pd.DataFrame,
    sector_scores: dict[str, dict[str, float | int]],
) -> list[dict[str, object]]:
    if current.empty:
        return []
    rows = current.merge(stock_lookup, on="ts_code", how="left")
    rows["gap_pct"] = (rows["bull_bear"] - rows["trend_short"]) / rows["bull_bear"] * 100
    rows["liquidity_billion"] = pd.to_numeric(rows["amount"], errors="coerce") / 100_000
    rows = rows[
        rows["name"].map(_safe_stock_name)
        & rows["gap_pct"].between(3, 12)
        & rows["liquidity_billion"].ge(1)
        & pd.to_numeric(rows["pct_chg"], errors="coerce").between(0, 5)
    ].copy()
    if rows.empty:
        return []
    rows["sector_rank"] = rows["industry"].map(
        lambda value: int(sector_scores.get(str(value), {}).get("rank", 999))
    )
    rows["observation_score"] = (
        18 - (rows["gap_pct"] - 6).abs()
        + rows["liquidity_billion"].clip(upper=10)
        + rows["sector_rank"].le(10).astype(float) * 5
    )
    rows = rows.sort_values(
        ["observation_score", "liquidity_billion", "ts_code"],
        ascending=[False, False, True],
    ).head(MAX_RECOMMENDATIONS)

    observations = []
    for rank, (_, row) in enumerate(rows.iterrows(), start=1):
        reasons = [f"短趋势低于多空线 {float(row['gap_pct']):.1f}%", "当日已出现正收益"]
        if int(row["sector_rank"]) <= 10:
            reasons.append(f"行业主线排名第 {int(row['sector_rank'])}")
        reasons.append(f"成交额 {float(row['liquidity_billion']):.1f} 亿")
        observations.append(
            {
                "rank": rank,
                "ts_code": str(row["ts_code"]),
                "name": str(row.get("name") or row["ts_code"]),
                "industry": str(row.get("industry") or "未分类"),
                "close": _round(row["close"]),
                "pct_chg": _round(row["pct_chg"]),
                "amount_billion": _round(row["liquidity_billion"], 1),
                "gap_pct": _round(row["gap_pct"], 1),
                "sector_rank": None if int(row["sector_rank"]) == 999 else int(row["sector_rank"]),
                "score": _round(row["observation_score"], 1),
                "action": "仅观察",
                "trigger": "不下单",
                "reasons": reasons,
            }
        )
    return observations


def _b1_recommendations(
    current: pd.DataFrame,
    stock_lookup: pd.DataFrame,
    sector_scores: dict[str, dict[str, float | int]],
) -> list[dict[str, object]]:
    """Rank today's B1 signals without changing the B1 signal definition."""
    if current.empty:
        return []
    rows = current.merge(stock_lookup, on="ts_code", how="left")
    rows["volume_ratio"] = (
        pd.to_numeric(rows["vol"], errors="coerce")
        / pd.to_numeric(rows["vol_ma5"], errors="coerce")
    )
    rows["liquidity_billion"] = pd.to_numeric(rows["amount"], errors="coerce") / 100_000
    rows["j"] = pd.to_numeric(rows["j"], errors="coerce")
    rows = rows[
        rows["name"].map(_safe_stock_name)
        & rows["volume_ratio"].between(0, 1, inclusive="neither")
        & rows["liquidity_billion"].ge(1)
        & rows["j"].lt(15)
    ].copy()
    if rows.empty:
        return []

    rows["sector_rank"] = rows["industry"].map(
        lambda value: int(sector_scores.get(str(value), {}).get("rank", 999))
    )
    rows["recommendation_score"] = (
        (15 - rows["j"]).clip(lower=0)
        + (1 - rows["volume_ratio"]).clip(lower=0) * 10
        + rows["liquidity_billion"].clip(upper=10) * 0.5
        + rows["sector_rank"].le(10).astype(float) * 5
    )
    rows = rows.sort_values(
        ["recommendation_score", "liquidity_billion", "ts_code"],
        ascending=[False, False, True],
    ).head(MAX_RECOMMENDATIONS)

    recommendations = []
    for rank, (_, row) in enumerate(rows.iterrows(), start=1):
        reasons = [
            f"J 值 {float(row['j']):.1f}，处于超卖区",
            f"成交量为 5 日均量 {float(row['volume_ratio']):.2f} 倍",
            "收盘仍在 MA60 与多空线上方",
        ]
        if int(row["sector_rank"]) <= 10:
            reasons.append(f"行业主线排名第 {int(row['sector_rank'])}")
        recommendations.append(
            {
                "rank": rank,
                "ts_code": str(row["ts_code"]),
                "name": str(row.get("name") or row["ts_code"]),
                "industry": str(row.get("industry") or "未分类"),
                "close": _round(row["close"]),
                "pct_chg": _round(row.get("pct_chg")),
                "amount_billion": _round(row["liquidity_billion"], 1),
                "j": _round(row["j"], 1),
                "volume_ratio": _round(row["volume_ratio"], 2),
                "sector_rank": None if int(row["sector_rank"]) == 999 else int(row["sector_rank"]),
                "score": _round(row["recommendation_score"], 1),
                "action": "次日候选买入",
                "trigger": "按 B1 次日开盘规则执行",
                "reasons": reasons,
            }
        )
    return recommendations


def _r1_observations(
    current: pd.DataFrame,
    stock_lookup: pd.DataFrame,
    context: dict[str, object],
) -> list[dict[str, object]]:
    if current.empty:
        return []
    rows = current.merge(stock_lookup, on="ts_code", how="left")
    rows = rows[rows["name"].map(_safe_stock_name)].head(MAX_RECOMMENDATIONS)
    observations = []
    for rank, (_, row) in enumerate(rows.iterrows(), start=1):
        formation_pct = float(row["r1_formation_return"]) * 100
        amount_billion = float(row["r1_amount_20"]) / 100_000
        observations.append(
            {
                "rank": rank,
                "ts_code": str(row["ts_code"]),
                "name": str(row.get("name") or row["ts_code"]),
                "industry": str(row.get("industry") or "未分类"),
                "close": _round(row["close"]),
                "pct_chg": _round(row.get("pct_chg")),
                "amount_billion": round(amount_billion, 1),
                "formation_return_pct": round(formation_pct, 1),
                "score": round(amount_billion, 1),
                "action": "仅观察",
                "trigger": "等待月度市场门控",
                "reasons": [
                    f"三月形成期收益 {formation_pct:.1f}%",
                    "最近一周不计入形成期",
                    f"20日均成交额 {amount_billion:.1f} 亿",
                    f"市场20日中位数 {context.get('market_median_20_pct') or 0:.2f}%",
                ],
            }
        )
    return observations


def _technical_recommendations(
    current: pd.DataFrame,
    stock_lookup: pd.DataFrame,
    *,
    kind: str,
) -> list[dict[str, object]]:
    if current.empty:
        return []
    rows = current.merge(stock_lookup, on="ts_code", how="left")
    rows = rows[rows["name"].map(_safe_stock_name)].copy()
    if kind == "breakout":
        rows = rows.sort_values(
            ["breakout_strength_pct", "r1_amount_20", "ts_code"],
            ascending=[False, False, True],
        )
    else:
        rows = rows.sort_values(
            ["trend_score", "r1_amount_20", "ts_code"],
            ascending=[False, False, True],
        )
    recommendations = []
    for rank, (_, row) in enumerate(rows.head(MAX_RECOMMENDATIONS).iterrows(), start=1):
        amount_billion = float(row["r1_amount_20"]) / 100_000
        if kind == "breakout":
            strength = float(row["breakout_strength_pct"])
            volume_ratio = float(row["breakout_volume_ratio"])
            reasons = [
                f"收盘突破前55日最高价 {strength:.1f}%",
                f"成交量为20日均量 {volume_ratio:.1f} 倍",
                f"20日均成交额 {amount_billion:.1f} 亿",
            ]
            score = strength * 10 + volume_ratio
        else:
            return_120 = float(row["trend_return_120"]) * 100
            reasons = [
                "MA20 > MA60 > MA120",
                "MA120 连续20日斜率向上",
                f"120日收益 {return_120:.1f}%",
                f"20日均成交额 {amount_billion:.1f} 亿",
            ]
            score = float(row["trend_score"])
        recommendations.append(
            {
                "rank": rank,
                "ts_code": str(row["ts_code"]),
                "name": str(row.get("name") or row["ts_code"]),
                "industry": str(row.get("industry") or "未分类"),
                "close": _round(row["close"]),
                "pct_chg": _round(row.get("pct_chg")),
                "amount_billion": round(amount_billion, 1),
                "score": round(score, 2),
                "action": "次日候选买入",
                "trigger": "次日不开盘追高",
                "reasons": reasons,
            }
        )
    return recommendations


def _value_recommendations(
    latest: pd.DataFrame,
    stock_lookup: pd.DataFrame,
) -> list[dict[str, object]]:
    if latest.empty:
        return []
    rows = latest.drop(columns=["name", "industry"], errors="ignore").merge(
        stock_lookup,
        on="ts_code",
        how="left",
    )
    rows = rows[rows["name"].map(_safe_stock_name)].sort_values(
        ["value_quality_score", "r1_amount_20", "ts_code"],
        ascending=[False, False, True],
    )
    recommendations = []
    for rank, (_, row) in enumerate(rows.head(MAX_RECOMMENDATIONS).iterrows(), start=1):
        amount_billion = float(row["r1_amount_20"]) / 100_000
        recommendations.append(
            {
                "rank": rank,
                "ts_code": str(row["ts_code"]),
                "name": str(row.get("name") or row["ts_code"]),
                "industry": str(row.get("industry") or "未分类"),
                "close": _round(row["close"]),
                "pct_chg": None,
                "amount_billion": round(amount_billion, 1),
                "score": _round(row["value_quality_score"], 1),
                "action": "深度研究",
                "trigger": "先验证护城河与管理层",
                "reasons": [
                    f"近3年ROE中位数 {float(row['roe_3y_median']):.1f}% / 最低 {float(row['roe_3y_min']):.1f}%",
                    f"近3年毛利率中位数 {float(row['gross_margin_3y_median']):.1f}%",
                    f"近3年营收/净利增速中位数 {float(row['revenue_yoy_3y_median']):.1f}% / {float(row['net_profit_yoy_3y_median']):.1f}%",
                    f"PE代理 {float(row['pe_proxy']):.1f} / PB代理 {float(row['pb_proxy']):.1f}",
                    "近3年经营现金流每股均为正",
                ],
            }
        )
    return recommendations


def _cohort_period_metrics(
    frame: pd.DataFrame,
    signal_mask: pd.Series,
    return_column: str,
    start: str,
    end: str,
) -> dict[str, object]:
    rows = frame[
        signal_mask
        & frame["trade_date"].between(start, end)
        & frame[return_column].notna()
    ][["trade_date", return_column]]
    if rows.empty:
        return {
            "period_start": start,
            "period_end": end if end >= start else None,
            "cohort_count": 0,
            "signal_count": 0,
            "net_mean_return_pct": None,
            "win_rate_pct": None,
            "latest_nav": None,
            "max_drawdown_pct": None,
        }
    cohort = rows.groupby("trade_date")[return_column].mean() - ROUND_TRIP_COST
    aggregate = pd.DataFrame(
        {"return_sum": cohort, "position_count": 1},
        index=cohort.index,
    )
    curve = _curve_from_aggregates([aggregate])
    returns = rows[return_column].astype(float)
    return {
        "period_start": str(rows["trade_date"].min()),
        "period_end": str(rows["trade_date"].max()),
        "cohort_count": int(rows["trade_date"].nunique()),
        "signal_count": int(len(rows)),
        "net_mean_return_pct": round(float(returns.mean() - ROUND_TRIP_COST) * 100, 2),
        "win_rate_pct": round(float((returns > 0).mean()) * 100, 1),
        "latest_nav": curve["latest_nav"],
        "max_drawdown_pct": curve["max_drawdown_pct"],
    }


def build_strategy_dashboard(
    db_path: Path | str = DEFAULT_DB_PATH,
    as_of_date: str | None = None,
    *,
    data_dir: Path | None = None,
) -> dict[str, object]:
    """Compute strategy metrics, drawdown curves and the current stock list."""
    db_path = Path(db_path)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    empty_payload: dict[str, object] = {
        "generated_at": generated_at,
        "as_of_date": as_of_date,
        "cost_assumption_pct": ROUND_TRIP_COST * 100,
        "strategies": [],
    }
    if not db_path.exists():
        return empty_payload

    with sqlite3.connect(db_path) as conn:
        tables = _table_names(conn)
        required = {"daily", "stock_basic", "kdj", "zhixing"}
        if not required.issubset(tables):
            return empty_payload
        if as_of_date is None:
            row = conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()
            as_of_date = str(row[0]) if row and row[0] else None
        if not as_of_date:
            return empty_payload

        scan_start = _shift_date(as_of_date, -BACKTEST_CALENDAR_DAYS)
        load_start = _shift_date(scan_start, -WARMUP_CALENDAR_DAYS)
        daily = pd.read_sql_query(
            """SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
               FROM daily
               WHERE trade_date BETWEEN ? AND ?
               ORDER BY ts_code, trade_date""",
            conn,
            params=[load_start, as_of_date],
        )
        trade_dates = sorted(daily["trade_date"].astype(str).unique())
        trade_date_index = {date: index for index, date in enumerate(trade_dates)}
        date_by_index = {index: date for date, index in trade_date_index.items()}
        daily["trade_index"] = daily["trade_date"].map(trade_date_index).astype("int16")
        daily = r1_reversal.add_features(daily, copy=False)
        daily = technical_expansion.add_features(daily, copy=False)
        breakout_signal = technical_expansion.cap_daily_signals(
            daily,
            "breakout_signal",
            "breakout_strength_pct",
        )
        trend_signal = technical_expansion.cap_daily_signals(
            daily,
            "trend_signal",
            "trend_score",
        )
        stock_lookup = _stock_lookup(conn)
        sector_scores = _load_sector_scores(conn, as_of_date)

        grouped = daily.groupby("ts_code", sort=False)
        daily["ma20"] = grouped["close"].rolling(20, min_periods=20).mean().droplevel(0)
        daily["ma60"] = grouped["close"].rolling(60, min_periods=60).mean().droplevel(0)
        daily["vol_ma5"] = grouped["vol"].rolling(5, min_periods=5).mean().droplevel(0)
        daily["ma20_prev"] = grouped["ma20"].shift(1)
        daily["ma60_prev"] = grouped["ma60"].shift(1)
        daily["golden_cross"] = (
            (daily["ma20"] > daily["ma60"])
            & (daily["ma20_prev"] <= daily["ma60_prev"])
        )
        daily["entry_index"] = grouped["trade_index"].shift(-1)
        daily["open_t1"] = grouped["open"].shift(-1)
        daily["close_t20"] = grouped["close"].shift(-20)
        daily["exit_index_20"] = grouped["trade_index"].shift(-20)
        daily["ret_20d"] = daily["close_t20"] / daily["open_t1"] - 1
        daily["r1_open_t21"] = grouped["r1_adjusted_open_index"].shift(
            -(r1_reversal.HOLDING_DAYS + 1)
        )
        daily["r1_exit_index"] = grouped["trade_index"].shift(-(r1_reversal.HOLDING_DAYS + 1))
        daily["r1_open_t1"] = grouped["r1_adjusted_open_index"].shift(-1)
        daily["r1_actual_ret"] = daily["r1_open_t21"] / daily["r1_open_t1"] - 1
        daily["value_open_t64"] = grouped["r1_adjusted_open_index"].shift(
            -(value_quality.HOLDING_DAYS + 1)
        )
        daily["value_exit_index"] = grouped["trade_index"].shift(
            -(value_quality.HOLDING_DAYS + 1)
        )
        daily["value_actual_ret"] = daily["value_open_t64"] / daily["r1_open_t1"] - 1

        r1_signal, r1_latest_observations, r1_context = r1_reversal.select_signals(
            daily,
            as_of_date,
        )
        r1_recommendations = _r1_observations(
            r1_latest_observations,
            stock_lookup,
            r1_context,
        )
        r1_valid = (
            r1_signal
            & daily["trade_date"].between(scan_start, as_of_date)
            & daily["r1_actual_ret"].notna()
        )
        r1_signals = daily.loc[r1_valid, ["trade_date", "r1_actual_ret"]].copy()
        r1_dates = r1_signals["trade_date"].unique()
        r1_baseline = daily[
            daily["trade_date"].isin(r1_dates) & daily["r1_actual_ret"].notna()
        ][["trade_date", "r1_actual_ret"]]
        r1_curve = _open_exit_curve(
            daily,
            r1_signal,
            scan_start,
            holding_days=r1_reversal.HOLDING_DAYS,
            open_column="r1_adjusted_open_index",
            close_column="r1_adjusted_close_index",
        )
        r1_metrics = _event_metrics(
            r1_signals,
            r1_baseline,
            "r1_actual_ret",
            r1_curve,
            scan_start,
            as_of_date,
        )
        r1_wf_mask, r1_wf_selection = _walk_forward_selection(
            daily,
            r1_signal,
            "r1_actual_ret",
            daily["r1_exit_index"],
            scan_start,
            WALK_FORWARD_GATES["r1_reversal"],
        )
        r1_wf_curve = _open_exit_curve(
            daily,
            r1_wf_mask,
            scan_start,
            holding_days=r1_reversal.HOLDING_DAYS,
            open_column="r1_adjusted_open_index",
            close_column="r1_adjusted_close_index",
        )
        if not r1_wf_curve["points"]:
            r1_wf_curve = _cash_curve(list(r1_wf_selection["test_dates"]))
        r1_walk_forward = _walk_forward_payload(
            r1_wf_selection,
            r1_wf_mask,
            daily,
            "r1_actual_ret",
            r1_wf_curve,
            WALK_FORWARD_GATES["r1_reversal"],
            "252 个交易日训练、21 个交易日样本外测试；月末选股，次日开盘买入，第 21 个交易日开盘退出。",
        )
        r1_research_split = {
            "development": _cohort_period_metrics(
                daily,
                r1_signal,
                "r1_actual_ret",
                "20240901",
                "20260831",
            ),
            "frozen_holdout": _cohort_period_metrics(
                daily,
                r1_signal,
                "r1_actual_ret",
                "20260820",
                as_of_date,
            ),
            "holdout_opened_once": False,
            "methodology_revision": "R1.1 于 2026-08-20 改用除权口径收益；旧留出作废，新冻结留出从 2026-08-20 开始。",
        }

        breakout_current = daily[
            breakout_signal & daily["trade_date"].eq(as_of_date)
        ].copy()
        breakout_recommendations = _technical_recommendations(
            breakout_current,
            stock_lookup,
            kind="breakout",
        )
        breakout_valid = (
            breakout_signal
            & daily["trade_date"].between(scan_start, as_of_date)
            & daily["r1_actual_ret"].notna()
        )
        breakout_signals = daily.loc[
            breakout_valid, ["trade_date", "r1_actual_ret"]
        ].copy()
        breakout_dates = breakout_signals["trade_date"].unique()
        breakout_baseline = daily[
            daily["trade_date"].isin(breakout_dates) & daily["r1_actual_ret"].notna()
        ][["trade_date", "r1_actual_ret"]]
        breakout_curve = _sparse_open_exit_curve(
            daily,
            breakout_signal,
            scan_start,
            technical_expansion.HOLDING_DAYS,
            open_column="r1_adjusted_open_index",
            close_column="r1_adjusted_close_index",
        )
        breakout_metrics = _event_metrics(
            breakout_signals,
            breakout_baseline,
            "r1_actual_ret",
            breakout_curve,
            scan_start,
            as_of_date,
        )
        breakout_wf_mask, breakout_wf_selection = _walk_forward_selection(
            daily,
            breakout_signal,
            "r1_actual_ret",
            daily["r1_exit_index"],
            scan_start,
            WALK_FORWARD_GATES["breakout_55"],
        )
        breakout_wf_curve = _sparse_open_exit_curve(
            daily,
            breakout_wf_mask,
            scan_start,
            technical_expansion.HOLDING_DAYS,
            open_column="r1_adjusted_open_index",
            close_column="r1_adjusted_close_index",
        )
        if not breakout_wf_curve["points"]:
            breakout_wf_curve = _cash_curve(list(breakout_wf_selection["test_dates"]))
        breakout_walk_forward = _walk_forward_payload(
            breakout_wf_selection,
            breakout_wf_mask,
            daily,
            "r1_actual_ret",
            breakout_wf_curve,
            WALK_FORWARD_GATES["breakout_55"],
            "252日训练、21日样本外测试；55日放量突破后次日开盘买入，第21个交易日开盘退出。",
        )

        trend_current = daily[trend_signal & daily["trade_date"].eq(as_of_date)].copy()
        trend_recommendations = _technical_recommendations(
            trend_current,
            stock_lookup,
            kind="trend",
        )
        trend_valid = (
            trend_signal
            & daily["trade_date"].between(scan_start, as_of_date)
            & daily["r1_actual_ret"].notna()
        )
        trend_signals = daily.loc[trend_valid, ["trade_date", "r1_actual_ret"]].copy()
        trend_dates = trend_signals["trade_date"].unique()
        trend_baseline = daily[
            daily["trade_date"].isin(trend_dates) & daily["r1_actual_ret"].notna()
        ][["trade_date", "r1_actual_ret"]]
        trend_curve = _sparse_open_exit_curve(
            daily,
            trend_signal,
            scan_start,
            technical_expansion.HOLDING_DAYS,
            open_column="r1_adjusted_open_index",
            close_column="r1_adjusted_close_index",
        )
        trend_metrics = _event_metrics(
            trend_signals,
            trend_baseline,
            "r1_actual_ret",
            trend_curve,
            scan_start,
            as_of_date,
        )
        trend_wf_mask, trend_wf_selection = _walk_forward_selection(
            daily,
            trend_signal,
            "r1_actual_ret",
            daily["r1_exit_index"],
            scan_start,
            WALK_FORWARD_GATES["trend_alignment"],
        )
        trend_wf_curve = _sparse_open_exit_curve(
            daily,
            trend_wf_mask,
            scan_start,
            technical_expansion.HOLDING_DAYS,
            open_column="r1_adjusted_open_index",
            close_column="r1_adjusted_close_index",
        )
        if not trend_wf_curve["points"]:
            trend_wf_curve = _cash_curve(list(trend_wf_selection["test_dates"]))
        trend_walk_forward = _walk_forward_payload(
            trend_wf_selection,
            trend_wf_mask,
            daily,
            "r1_actual_ret",
            trend_wf_curve,
            WALK_FORWARD_GATES["trend_alignment"],
            "252日训练、21日样本外测试；多周期趋势首次对齐后次日开盘买入，第21个交易日开盘退出。",
        )

        if "fundamental_annual" in tables:
            fundamentals = pd.read_sql_query(
                """SELECT ts_code, report_date, announcement_date, name, industry,
                          revenue_yoy, net_profit_yoy, eps, book_value_per_share,
                          roe, ocf_per_share, gross_margin, debt_to_assets
                   FROM fundamental_annual
                   WHERE announcement_date <= ?
                   ORDER BY announcement_date, ts_code""",
                conn,
                params=[as_of_date],
            )
        else:
            fundamentals = pd.DataFrame()
        quarter_month = daily["trade_date"].astype(str).str[4:6].isin(
            ["01", "04", "07", "10"]
        )
        complete_month = daily["trade_date"].astype(str).str[:6].lt(as_of_date[:6])
        quarter_rows = daily[quarter_month & complete_month]
        quarter_dates = set(
            quarter_rows.groupby(quarter_rows["trade_date"].str[:6])["trade_date"].max()
        )
        value_prices = daily[daily["trade_date"].isin(quarter_dates)][
            ["ts_code", "trade_date", "close", "r1_amount_20"]
        ].copy()
        value_selected, value_latest, value_context = value_quality.score_snapshots(
            fundamentals,
            value_prices,
            as_of_date,
        )
        value_case_details = {
            (str(row.ts_code), str(row.trade_date)): row
            for row in value_selected.itertuples(index=False)
        }
        value_signal = _signal_mask_from_pairs(daily, value_selected)
        value_recommendations = _value_recommendations(value_latest, stock_lookup)
        value_valid = (
            value_signal
            & daily["trade_date"].between(scan_start, as_of_date)
            & daily["value_actual_ret"].notna()
        )
        value_signals = daily.loc[
            value_valid, ["trade_date", "value_actual_ret"]
        ].copy()
        value_dates = value_signals["trade_date"].unique()
        value_baseline = daily[
            daily["trade_date"].isin(value_dates) & daily["value_actual_ret"].notna()
        ][["trade_date", "value_actual_ret"]]
        value_curve = _sparse_open_exit_curve(
            daily,
            value_signal,
            scan_start,
            value_quality.HOLDING_DAYS,
            open_column="r1_adjusted_open_index",
            close_column="r1_adjusted_close_index",
        )
        value_metrics = _event_metrics(
            value_signals,
            value_baseline,
            "value_actual_ret",
            value_curve,
            scan_start,
            as_of_date,
        )
        value_wf_mask, value_wf_selection = _walk_forward_selection(
            daily,
            value_signal,
            "value_actual_ret",
            daily["value_exit_index"],
            scan_start,
            WALK_FORWARD_GATES["value_quality"],
        )
        value_wf_curve = _sparse_open_exit_curve(
            daily,
            value_wf_mask,
            scan_start,
            value_quality.HOLDING_DAYS,
            open_column="r1_adjusted_open_index",
            close_column="r1_adjusted_close_index",
        )
        if not value_wf_curve["points"]:
            value_wf_curve = _cash_curve(list(value_wf_selection["test_dates"]))
        value_walk_forward = _walk_forward_payload(
            value_wf_selection,
            value_wf_mask,
            daily,
            "value_actual_ret",
            value_wf_curve,
            WALK_FORWARD_GATES["value_quality"],
            "季度末点时财报与估值筛选，次日开盘建立研究组合，63个交易日后开盘复核退出。",
        )

        golden_current = daily[
            daily["golden_cross"] & daily["trade_date"].eq(as_of_date)
        ].copy()
        golden_recommendations = _golden_recommendations(
            golden_current,
            stock_lookup,
            sector_scores,
        )
        golden_valid = (
            daily["golden_cross"]
            & daily["trade_date"].between(scan_start, as_of_date)
            & daily["ret_20d"].notna()
        )
        golden_signals = daily.loc[golden_valid, ["trade_date", "ret_20d"]].copy()
        golden_dates = golden_signals["trade_date"].unique()
        golden_baseline = daily[
            daily["trade_date"].isin(golden_dates) & daily["ret_20d"].notna()
        ][["trade_date", "ret_20d"]]
        golden_curve = _fixed_holding_curve(
            daily,
            daily["golden_cross"],
            scan_start,
            holding_days=20,
        )
        golden_metrics = _event_metrics(
            golden_signals,
            golden_baseline,
            "ret_20d",
            golden_curve,
            scan_start,
            as_of_date,
        )
        golden_wf_mask, golden_wf_selection = _walk_forward_selection(
            daily,
            daily["golden_cross"],
            "ret_20d",
            daily["exit_index_20"],
            scan_start,
            WALK_FORWARD_GATES["ma20_ma60"],
        )
        golden_wf_curve = _fixed_holding_curve(
            daily,
            golden_wf_mask,
            scan_start,
            holding_days=20,
        )
        if not golden_wf_curve["points"]:
            golden_wf_curve = _cash_curve(list(golden_wf_selection["test_dates"]))
        golden_walk_forward = _walk_forward_payload(
            golden_wf_selection,
            golden_wf_mask,
            daily,
            "ret_20d",
            golden_wf_curve,
            WALK_FORWARD_GATES["ma20_ma60"],
            "252 个交易日训练、21 个交易日样本外测试；训练交易须在测试前完成退出，门控通过后才持仓。",
        )

        r1_historical_cases = _historical_cases(
            daily, r1_signal, r1_wf_mask, "r1_actual_ret", daily["r1_exit_index"],
            scan_start, stock_lookup, date_by_index, "r1_reversal",
        )
        r1_credibility = _credibility_payload(
            daily, r1_signal, r1_wf_mask, "r1_actual_ret", scan_start,
            as_of_date, r1_walk_forward,
        )
        breakout_historical_cases = _historical_cases(
            daily, breakout_signal, breakout_wf_mask, "r1_actual_ret", daily["r1_exit_index"],
            scan_start, stock_lookup, date_by_index, "breakout_55",
        )
        breakout_credibility = _credibility_payload(
            daily, breakout_signal, breakout_wf_mask, "r1_actual_ret", scan_start,
            as_of_date, breakout_walk_forward,
        )
        trend_historical_cases = _historical_cases(
            daily, trend_signal, trend_wf_mask, "r1_actual_ret", daily["r1_exit_index"],
            scan_start, stock_lookup, date_by_index, "trend_alignment",
        )
        trend_credibility = _credibility_payload(
            daily, trend_signal, trend_wf_mask, "r1_actual_ret", scan_start,
            as_of_date, trend_walk_forward,
        )
        value_historical_cases = _historical_cases(
            daily, value_signal, value_wf_mask, "value_actual_ret", daily["value_exit_index"],
            scan_start, stock_lookup, date_by_index, "value_quality",
            value_details=value_case_details,
        )
        value_credibility = _credibility_payload(
            daily, value_signal, value_wf_mask, "value_actual_ret", scan_start,
            as_of_date, value_walk_forward,
        )
        golden_historical_cases = _historical_cases(
            daily, daily["golden_cross"], golden_wf_mask, "ret_20d", daily["exit_index_20"],
            scan_start, stock_lookup, date_by_index, "ma20_ma60",
        )
        golden_credibility = _credibility_payload(
            daily, daily["golden_cross"], golden_wf_mask, "ret_20d", scan_start,
            as_of_date, golden_walk_forward,
        )

        # Merge persisted indicators only after the larger 20-day curve has
        # been built, keeping peak memory bounded during the daily export.
        zhixing = pd.read_sql_query(
            """SELECT ts_code, trade_date, trend_short, bull_bear
               FROM zhixing
               WHERE trade_date BETWEEN ? AND ?""",
            conn,
            params=[load_start, as_of_date],
        )
        kdj = pd.read_sql_query(
            """SELECT ts_code, trade_date, j
               FROM kdj
               WHERE trade_date BETWEEN ? AND ?""",
            conn,
            params=[load_start, as_of_date],
        )

    daily.drop(
        columns=[
            "ma20_prev", "ma60_prev", "close_t20",
            "r1_open_t21", "r1_open_t1", "r1_exit_index", "r1_actual_ret",
            "value_open_t64", "value_exit_index", "value_actual_ret",
            "r1_adjusted_close_index", "r1_adjusted_open_index",
            "r1_formation_return", "r1_market_return_20",
            "r1_amount_20", "r1_market_median_20",
            "tech_adjusted_high", "breakout_previous_high",
            "breakout_volume_ratio", "breakout_signal", "breakout_strength_pct",
            "trend_ma20", "trend_ma60", "trend_ma120", "trend_return_120",
            "trend_volatility_20", "trend_ma120_prev20", "trend_signal",
            "trend_score",
        ],
        inplace=True,
    )
    daily = daily.merge(zhixing, on=["ts_code", "trade_date"], how="inner")
    del zhixing
    daily = daily.merge(kdj, on=["ts_code", "trade_date"], how="inner")
    del kdj
    gc.collect()

    grouped = daily.groupby("ts_code", sort=False)
    daily["low_t1"] = grouped["low"].shift(-1)
    daily["open_t2"] = grouped["open"].shift(-2)
    daily["open_t3"] = grouped["open"].shift(-3)
    daily["open_t4"] = grouped["open"].shift(-4)
    date_index_t2 = grouped["trade_index"].shift(-2)
    date_index_t3 = grouped["trade_index"].shift(-3)
    date_index_t4 = grouped["trade_index"].shift(-4)
    daily["stop_t2"] = daily["open_t2"] < daily["low_t1"]
    daily["stop_t3"] = (~daily["stop_t2"]) & (daily["open_t3"] < daily["low_t1"])
    daily["exit_price"] = np.where(
        daily["stop_t2"],
        daily["open_t2"],
        np.where(daily["stop_t3"], daily["open_t3"], daily["open_t4"]),
    )
    daily["actual_ret"] = daily["exit_price"] / daily["open_t1"] - 1
    daily["stopped_exit_index"] = np.where(
        daily["stop_t2"],
        date_index_t2,
        np.where(daily["stop_t3"], date_index_t3, date_index_t4),
    )

    b2_signal = (
        daily["trend_short"].notna()
        & daily["bull_bear"].gt(0)
        & (daily["trend_short"] < daily["bull_bear"])
    )
    b2_current = daily[b2_signal & daily["trade_date"].eq(as_of_date)].copy()
    b2_observations = _b2_observations(b2_current, stock_lookup, sector_scores)
    b2_valid = (
        b2_signal
        & daily["trade_date"].between(scan_start, as_of_date)
        & daily["actual_ret"].notna()
    )
    b2_signals = daily.loc[b2_valid, ["trade_date", "actual_ret"]].copy()
    b2_dates = b2_signals["trade_date"].unique()
    b2_baseline = daily[
        daily["trade_date"].isin(b2_dates) & daily["actual_ret"].notna()
    ][["trade_date", "actual_ret"]]
    b2_curve = _stopped_curve(daily, b2_signal, scan_start)
    b2_metrics = _event_metrics(
        b2_signals,
        b2_baseline,
        "actual_ret",
        b2_curve,
        scan_start,
        as_of_date,
    )
    b2_wf_mask, b2_wf_selection = _walk_forward_selection(
        daily,
        b2_signal,
        "actual_ret",
        daily["stopped_exit_index"],
        scan_start,
        WALK_FORWARD_GATES["b2_reversion"],
    )
    b2_wf_curve = _stopped_curve(daily, b2_wf_mask, scan_start)
    if not b2_wf_curve["points"]:
        b2_wf_curve = _cash_curve(list(b2_wf_selection["test_dates"]))
    b2_walk_forward = _walk_forward_payload(
        b2_wf_selection,
        b2_wf_mask,
        daily,
        "actual_ret",
        b2_wf_curve,
        WALK_FORWARD_GATES["b2_reversion"],
        "252 个交易日训练、21 个交易日样本外测试；训练交易须在测试前完成退出，门控通过后才持仓。",
    )
    b2_historical_cases = _historical_cases(
        daily, b2_signal, b2_wf_mask, "actual_ret", daily["stopped_exit_index"],
        scan_start, stock_lookup, date_by_index, "b2_reversion",
    )
    b2_credibility = _credibility_payload(
        daily, b2_signal, b2_wf_mask, "actual_ret", scan_start,
        as_of_date, b2_walk_forward,
    )

    b1_signal = (
        (daily["vol"] / daily["vol_ma5"] < 1)
        & (daily["j"] < 15)
        & (daily["close"] > daily["ma60"])
        & (daily["trend_short"] > daily["bull_bear"])
        & (daily["close"] > daily["bull_bear"])
    )
    b1_current = daily[b1_signal & daily["trade_date"].eq(as_of_date)].copy()
    b1_recommendations = _b1_recommendations(
        b1_current,
        stock_lookup,
        sector_scores,
    )
    b1_valid = (
        b1_signal
        & daily["trade_date"].between(scan_start, as_of_date)
        & daily["actual_ret"].notna()
    )
    b1_signals = daily.loc[b1_valid, ["trade_date", "actual_ret"]].copy()
    b1_dates = b1_signals["trade_date"].unique()
    b1_baseline = daily[
        daily["trade_date"].isin(b1_dates) & daily["actual_ret"].notna()
    ][["trade_date", "actual_ret"]]
    b1_curve = _stopped_curve(daily, b1_signal, scan_start)
    b1_metrics = _event_metrics(
        b1_signals,
        b1_baseline,
        "actual_ret",
        b1_curve,
        scan_start,
        as_of_date,
    )
    b1_wf_mask, b1_wf_selection = _walk_forward_selection(
        daily,
        b1_signal,
        "actual_ret",
        daily["stopped_exit_index"],
        scan_start,
        WALK_FORWARD_GATES["b1_pullback"],
    )
    b1_wf_curve = _stopped_curve(daily, b1_wf_mask, scan_start)
    if not b1_wf_curve["points"]:
        b1_wf_curve = _cash_curve(list(b1_wf_selection["test_dates"]))
    b1_walk_forward = _walk_forward_payload(
        b1_wf_selection,
        b1_wf_mask,
        daily,
        "actual_ret",
        b1_wf_curve,
        WALK_FORWARD_GATES["b1_pullback"],
        "252 个交易日训练、21 个交易日样本外测试；训练交易须在测试前完成退出，门控通过后才持仓。",
    )
    b1_historical_cases = _historical_cases(
        daily, b1_signal, b1_wf_mask, "actual_ret", daily["stopped_exit_index"],
        scan_start, stock_lookup, date_by_index, "b1_pullback",
    )
    b1_credibility = _credibility_payload(
        daily, b1_signal, b1_wf_mask, "actual_ret", scan_start,
        as_of_date, b1_walk_forward,
    )
    b1_current_count = int(len(b1_current))

    golden_latest_approved = bool(
        golden_walk_forward["metrics"].get("latest_approved", False)
    )
    if not golden_latest_approved:
        for recommendation in golden_recommendations:
            recommendation["action"] = "仅观察"
            recommendation["trigger"] = "滚动门控未通过"

    b1_latest_approved = bool(
        b1_walk_forward["metrics"].get("latest_approved", False)
    )
    if not b1_latest_approved:
        for recommendation in b1_recommendations:
            recommendation["action"] = "仅观察"
            recommendation["trigger"] = "滚动门控未通过"

    r1_development = r1_research_split["development"]
    r1_holdout = r1_research_split["frozen_holdout"]
    r1_latest_approved = bool(r1_walk_forward["metrics"].get("latest_approved", False))
    r1_holdout_passed = bool(
        int(r1_holdout.get("cohort_count") or 0) >= 3
        and float(r1_holdout.get("latest_nav") or 0) > 1
        and float(r1_holdout.get("max_drawdown_pct") or -100) >= -15
    )
    r1_market_open = bool(r1_context.get("market_regime_open", False))
    r1_can_trade = r1_latest_approved and r1_holdout_passed and r1_market_open
    if r1_can_trade:
        r1_status_label = "允许执行"
        r1_confidence = "中等"
        for recommendation in r1_recommendations:
            recommendation["action"] = "月度候选买入"
            recommendation["trigger"] = "下个交易日不开盘追高"
    elif int(r1_holdout.get("cohort_count") or 0) < 3:
        r1_status_label = "冻结留出不足"
        r1_confidence = "研究阶段"
        for recommendation in r1_recommendations:
            recommendation["trigger"] = "等待更多冻结样本"
    elif not r1_holdout_passed:
        r1_status_label = "冻结留出未通过"
        r1_confidence = "偏低"
        for recommendation in r1_recommendations:
            recommendation["trigger"] = "冻结留出未通过"
    elif not r1_latest_approved:
        r1_status_label = "滚动未通过"
        r1_confidence = "偏低"
        for recommendation in r1_recommendations:
            recommendation["trigger"] = "滚动门控未通过"
    else:
        r1_status_label = "市场门控关闭"
        r1_confidence = "中等"
    if int(r1_holdout.get("cohort_count") or 0):
        r1_evidence = (
            f"R1.1 研究期 {r1_development.get('cohort_count') or 0} 个组合，"
            f"净值 {r1_development.get('latest_nav') or '--'}、回撤 {r1_development.get('max_drawdown_pct')}%；"
            f"冻结留出已有 {r1_holdout.get('cohort_count')} 个完整组合，"
            f"净单笔 {r1_holdout.get('net_mean_return_pct')}%。"
        )
    else:
        r1_evidence = (
            f"R1.1 研究期 {r1_development.get('cohort_count') or 0} 个组合，"
            f"净值 {r1_development.get('latest_nav') or '--'}、回撤 {r1_development.get('max_drawdown_pct')}%；"
            "除权口径修订后，新的冻结留出从 2026年8月20日开始，目前尚无完整组合。"
        )

    breakout_latest_approved = bool(
        breakout_walk_forward["metrics"].get("latest_approved", False)
    )
    if not breakout_latest_approved:
        for recommendation in breakout_recommendations:
            recommendation["action"] = "仅观察"
            recommendation["trigger"] = "滚动门控未通过"
    trend_latest_approved = bool(
        trend_walk_forward["metrics"].get("latest_approved", False)
    )
    if not trend_latest_approved:
        for recommendation in trend_recommendations:
            recommendation["action"] = "仅观察"
            recommendation["trigger"] = "滚动门控未通过"
    value_latest_approved = bool(
        value_walk_forward["metrics"].get("latest_approved", False)
    )

    strategies = [
        {
            "id": "r1_reversal",
            "version": "R1.1",
            "name": "R1 三月错杀修复",
            "short_name": "R1 错杀修复",
            "status": "active" if r1_can_trade else "watch",
            "status_label": r1_status_label,
            "confidence": r1_confidence,
            "thesis": "每月寻找过去三个月跌幅居前、但跳过最近一周的高流动性股票；仅在市场20日中位数为正时做均值回归。",
            "evidence": r1_evidence,
            "signal_rule": "完整月末：形成期 t-65 至 t-5 收益位于流动性股票后10%，市场20日收益中位数 > 0，取成交额最高20只。",
            "exit_rule": "月末收盘生成信号，下一交易日开盘买入，持有20个交易日后于第21日开盘退出。",
            "position_rule": "冻结留出至少3个组合且净值>1、回撤不低于-15%，同时滚动门控与市场门控通过后，才允许每股1%、总仓20%。",
            "recommendation_label": "最近月末观察池" if not r1_can_trade else "月度买入候选",
            "recommendation_note": (
                f"最近完整信号日 {r1_context.get('latest_signal_date') or '--'}；"
                f"市场20日中位数 {r1_context.get('market_median_20_pct')}%。"
                + ("所有候选仅观察，不下单。" if not r1_can_trade else "门控通过，可按月度规则执行。")
            ),
            "current_signal_label": "最近月末观察",
            "current_signal_count": int(len(r1_latest_observations)),
            "metrics": r1_metrics,
            "curve": r1_curve["points"],
            "curve_method": "完整月末等权持仓，次日开盘买入、第21个交易日开盘退出；含0.20%往返成本。",
            "walk_forward": r1_walk_forward,
            "credibility": r1_credibility,
            "historical_cases": r1_historical_cases,
            "research_split": r1_research_split,
            "known_limitations": [
                "历史库没有点时 ST 名称快照，回测未排除历史 ST；实时观察池会剔除当前 ST 与退市风险股票。",
                "0.20% 往返成本未模拟涨跌停无法成交、停牌和大额订单冲击，实盘表现可能更差。",
            ],
            "source": {
                "title": "Short-term Reversal in Chinese A-Shares",
                "url": "https://ssrn.com/abstract=6872158",
                "note": "策略借鉴三个月反转并跳过最近一周的点时研究设计，但流动性、市场门控和持仓规模为本项目规则。",
            },
            "recommendations": r1_recommendations,
        },
        {
            "id": "breakout_55",
            "name": "B3 55日放量突破",
            "short_name": "B3 突破",
            "status": "active" if breakout_latest_approved else "watch",
            "status_label": "滚动通过" if breakout_latest_approved else "滚动未通过",
            "confidence": "中等" if breakout_latest_approved else "偏低",
            "thesis": "只参与价格创55日新高且成交量同步放大的流动性股票，并用市场广度过滤弱市假突破。",
            "evidence": "参数在查看新增策略结果前冻结：55日通道、1.5倍成交量、20日持有；是否执行完全由滚动样本外门控决定。",
            "signal_rule": "收盘突破此前55个交易日最高价，成交量≥20日均量1.5倍、20日均成交额≥1亿元、市场20日收益中位数>0；每日最多20只。",
            "exit_rule": "信号后下一交易日开盘买入，第21个交易日开盘退出；不在信号当日追涨。",
            "position_rule": "仅滚动门控通过时执行；单股1%、总仓20%，同一行业不超过5%，跳空高开超过5%放弃。",
            "recommendation_label": "今日突破候选" if breakout_latest_approved else "今日突破观察",
            "recommendation_note": "滚动门控通过后，候选才可在次日按规则执行。" if breakout_latest_approved else "最近滚动训练窗口未通过，全部仅观察。",
            "current_signal_count": int(len(breakout_current)),
            "metrics": breakout_metrics,
            "curve": breakout_curve["points"],
            "curve_method": "除权价格55日放量突破，次日开盘等权买入、第21日开盘退出；含0.20%往返成本。",
            "walk_forward": breakout_walk_forward,
            "credibility": breakout_credibility,
            "historical_cases": breakout_historical_cases,
            "known_limitations": [
                "未模拟涨停封板无法买入与突破日之后的开盘滑点。",
                "固定20日退出用于统一审计，不等于最优的移动止损规则。",
            ],
            "recommendations": breakout_recommendations,
        },
        {
            "id": "trend_alignment",
            "name": "T1 多周期趋势对齐",
            "short_name": "T1 趋势",
            "status": "active" if trend_latest_approved else "watch",
            "status_label": "滚动通过" if trend_latest_approved else "滚动未通过",
            "confidence": "中等" if trend_latest_approved else "偏低",
            "thesis": "等待短中长期均线同向、长期均线斜率转正，只参与趋势首次对齐而不是追逐每一天的强势股。",
            "evidence": "采用20/60/120日多周期结构与120日自身动量，和趋势跟随研究的“用自身历史收益判断方向”一致；A股参数仍需本地样本外结果验证。",
            "signal_rule": "MA20>MA60>MA120、MA120高于20日前、120日收益>0、20日均成交额≥1亿元、市场门控开启；仅取首次对齐。",
            "exit_rule": "下一交易日开盘买入，第21个交易日开盘退出；趋势失效的更长持有版本另行冻结后验证。",
            "position_rule": "仅滚动门控通过时执行；按波动率从低到高优先，单股1%、总仓20%，单行业不超过5%。",
            "recommendation_label": "今日趋势候选" if trend_latest_approved else "今日趋势观察",
            "recommendation_note": "只执行今天首次完成趋势对齐的股票。" if trend_latest_approved else "最近滚动训练窗口未通过，全部仅观察。",
            "current_signal_count": int(len(trend_current)),
            "metrics": trend_metrics,
            "curve": trend_curve["points"],
            "curve_method": "除权价格多周期趋势首次对齐，次日开盘等权买入、第21日开盘退出；含0.20%往返成本。",
            "walk_forward": trend_walk_forward,
            "credibility": trend_credibility,
            "historical_cases": trend_historical_cases,
            "known_limitations": [
                "趋势论文证据主要来自跨资产期货，不能直接外推为A股个股收益。",
                "固定20日审计窗口可能提前截断长趋势，页面结果必须按本项目数据解释。",
            ],
            "source": {
                "title": "Time Series Momentum",
                "url": "https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf",
                "note": "仅借鉴自身历史收益与趋势持续性的研究框架。",
            },
            "recommendations": trend_recommendations,
        },
        {
            "id": "value_quality",
            "name": "V1 好公司合理价（巴芒段风格）",
            "short_name": "V1 价值",
            "status": "watch",
            "status_label": "人工尽调必需" if value_latest_approved else "数据验证中",
            "confidence": "研究阶段",
            "thesis": "把股票当作企业所有权：先筛持续盈利、现金流为正、负债可控的公司，再用点时PE/PB代理约束买入价格。",
            "evidence": f"最新季度观察日 {value_context.get('latest_signal_date') or '--'}，财务合格 {value_context.get('eligible_count') or 0} 家；量化只能做第一层筛选，不能替代护城河、管理层与能力圈判断。",
            "signal_rule": "季度末仅使用公告日不晚于信号日的年报：近3年ROE中位数≥15%且最低≥10%、毛利率中位数≥20%、营收与净利增速中位数非负、3年经营现金流/股均>0、最高负债率≤60%；PE代理5–30、PB代理≤6。",
            "exit_rule": "63个交易日只作为组合审计与再评估周期；企业价值逻辑未破坏时不机械止盈，基本面恶化或价格显著透支时退出。",
            "position_rule": "始终需要人工确认商业模式、护城河、管理层诚信和机会成本；研究池单股上限5%，确认前不下单。",
            "recommendation_label": "季度价值研究池",
            "recommendation_note": f"最近观察日 {value_context.get('latest_signal_date') or '--'}，使用截至当日已公告的 {value_context.get('report_date') or '--'} 年报；这些不是自动买入指令。",
            "current_signal_label": "季度研究入选",
            "current_signal_count": int(len(value_latest)),
            "metrics": value_metrics,
            "curve": value_curve["points"],
            "curve_method": "季度末点时财报筛选后建立63交易日等权审计组合；含0.20%往返成本。",
            "walk_forward": value_walk_forward,
            "credibility": value_credibility,
            "historical_cases": value_historical_cases,
            "known_limitations": [
                "PE/PB为年报EPS、每股净资产与当时股价计算的保守代理，不是完整现金流折现估值。",
                "公告源保留最新公告日并保守延后使用，可避免明显未来函数，但历史更正版本与当时原始版本仍可能不同。",
                "品牌、护城河、管理层诚信、资本配置与能力圈无法仅靠结构化数据量化。",
            ],
            "source": {
                "title": "Berkshire Hathaway 2023 Annual Report",
                "url": "https://www.berkshirehathaway.com/2023ar/2023ar.pdf",
                "note": "借鉴长期所有权、优质企业与资本配置框架；本策略不是任何投资人的原始公式。",
            },
            "recommendations": value_recommendations,
        },
        {
            "id": "ma20_ma60",
            "name": "MA20/60 金叉趋势",
            "short_name": "金叉趋势",
            "status": "active" if golden_latest_approved else "watch",
            "status_label": "滚动通过" if golden_latest_approved else "滚动未通过",
            "confidence": "中等" if golden_latest_approved else "偏低",
            "thesis": "用中期均线刚刚上穿长期均线捕捉趋势启动，并用主线行业、成交额与追高幅度做二次排序。",
            "evidence": "是否允许执行由最近 252 个交易日的已完成交易决定，并只在随后 21 个交易日样本外生效；主线排序层仍未单独完成长期验证。",
            "signal_rule": "收盘后确认 MA20 由下向上穿越 MA60；次日开盘执行。",
            "exit_rule": "持有至第 20 个交易日收盘；回测未加入盘中止损。",
            "position_rule": "滚动门控通过时：组合等权，单股不超过账户权益 1.5%，同一行业不超过 8%，总仓位不超过 30%；未通过时保持空仓。",
            "recommendation_label": "今日条件买入候选" if golden_latest_approved else "今日观察池",
            "recommendation_note": "滚动门控已通过；仅在次日开盘未高开超过 3% 时分批执行。" if golden_latest_approved else "最近滚动训练窗口未通过，候选仅观察，不下单。",
            "current_signal_count": int(len(golden_current)),
            "metrics": golden_metrics,
            "curve": golden_curve["points"],
            "curve_method": "每日等权所有有效金叉持仓，次日开盘买入、持有 20 个交易日；含 0.20% 往返成本。",
            "walk_forward": golden_walk_forward,
            "credibility": golden_credibility,
            "historical_cases": golden_historical_cases,
            "recommendations": golden_recommendations,
        },
        {
            "id": "b2_reversion",
            "name": "B2 趋势下方反转",
            "short_name": "B2 反转",
            "status": "watch",
            "status_label": "观察验证",
            "confidence": "偏低",
            "thesis": "短趋势线低于多空线时寻找均值回归，但原始信号覆盖面过大，容易混入持续下跌的股票。",
            "evidence": "相对基准略有正超额，但扣除成本后的单笔优势很薄、胜率仍低于 50%，暂不进入自动买入。",
            "signal_rule": "trend_short < bull_bear；观察池额外要求流动性、温和偏离和当日转强。",
            "exit_rule": "次日开盘买入，以买入日最低价为后续止损参考，最迟第 4 日开盘退出。",
            "position_rule": "研究阶段不建议实盘；若做纸面验证，每股权重不超过 1%。",
            "recommendation_label": "今日观察池",
            "recommendation_note": "这些股票用于继续验证反转条件，不属于可执行买入建议。",
            "current_signal_count": int(len(b2_current)),
            "metrics": b2_metrics,
            "curve": b2_curve["points"],
            "curve_method": "每日等权所有 B2 有效持仓，沿用项目的次日开盘买入与 3 日内退出规则；含 0.20% 往返成本。",
            "walk_forward": b2_walk_forward,
            "credibility": b2_credibility,
            "historical_cases": b2_historical_cases,
            "recommendations": b2_observations,
        },
        {
            "id": "b1_pullback",
            "name": "B1 缩量超卖回踩",
            "short_name": "B1 回踩",
            "status": "active" if b1_latest_approved else "watch",
            "status_label": "滚动通过" if b1_latest_approved else "滚动未通过",
            "confidence": "中等" if b1_latest_approved else "偏低",
            "thesis": "缩量、KDJ 超卖且仍在长期趋势上方的五条件回踩筛选。",
            "evidence": "状态完全由滚动门控自动判定；当前长期样本扣除成本后表现偏弱，因此未通过时只观察，但未来窗口达标后可自动恢复。",
            "signal_rule": "vol < MA5、J < 15、close > MA60、短趋势 > 多空线、close > 多空线。",
            "exit_rule": "次日开盘买入，以买入日最低价为后续止损参考，最迟第 4 日开盘退出。",
            "position_rule": "滚动门控通过时：组合等权，单股不超过账户权益 1%，总仓位不超过 20%；未通过时保持空仓。",
            "recommendation_label": "今日条件买入候选" if b1_latest_approved else "今日观察池",
            "recommendation_note": "滚动门控已通过；按 B1 次日开盘与止损规则执行。" if b1_latest_approved else "最近滚动训练窗口未通过，候选仅观察，不下单。",
            "current_signal_count": b1_current_count,
            "metrics": b1_metrics,
            "curve": b1_curve["points"],
            "curve_method": "每日等权所有 B1 有效持仓，沿用项目的次日开盘买入与 3 日内退出规则；含 0.20% 往返成本。",
            "walk_forward": b1_walk_forward,
            "credibility": b1_credibility,
            "historical_cases": b1_historical_cases,
            "recommendations": b1_recommendations,
        },
    ]

    strategies.append(zb1.build_strategy(db_path, as_of_date, data_dir))

    active_recommendations = sum(
        len(strategy["recommendations"])
        for strategy in strategies
        if strategy["status"] == "active"
    )
    return {
        "generated_at": generated_at,
        "as_of_date": as_of_date,
        "backtest_start": scan_start,
        "cost_assumption_pct": ROUND_TRIP_COST * 100,
        "summary": {
            "active_strategy_count": sum(s["status"] == "active" for s in strategies),
            "watch_strategy_count": sum(s["status"] == "watch" for s in strategies),
            "retired_strategy_count": sum(s["status"] == "retired" for s in strategies),
            "active_recommendation_count": active_recommendations,
        },
        "risk_notice": "研究策略按252日训练、21日样本外测试的滚动门控验证；ZB1按用户自定义规则独立模拟，不受该门控限制，也不代表已通过验证。页面不连接实盘下单，历史结果不保证未来盈利。",
        "strategies": strategies,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the strategy dashboard payload.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--date", help="Dashboard trade date in YYYYMMDD form")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_strategy_dashboard(args.db_path, args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"strategy dashboard: {len(payload['strategies'])} strategies, "
        f"as of {payload.get('as_of_date') or '--'} -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
