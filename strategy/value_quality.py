"""Conservative quantitative proxy for Buffett/Munger/Duan-style investing.

The model can screen accounting quality and valuation, but it cannot measure
management integrity, durable competitive advantage, or whether the business
is inside the investor's circle of competence.  Those remain manual gates.
"""

from __future__ import annotations

import pandas as pd


MIN_ROE = 15.0
MIN_GROSS_MARGIN = 20.0
MAX_DEBT_TO_ASSETS = 60.0
MIN_PE = 5.0
MAX_PE = 30.0
MAX_PB = 6.0
MIN_AMOUNT_20 = 100_000.0
PORTFOLIO_SIZE = 20
HOLDING_DAYS = 63


def score_snapshots(
    fundamentals: pd.DataFrame,
    prices: pd.DataFrame,
    as_of_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Point-in-time join and score quarterly valuation snapshots."""
    if fundamentals.empty or prices.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "latest_signal_date": None,
            "eligible_count": 0,
            "data_ready": False,
        }
    current_month = as_of_date[:6]
    left = prices[prices["trade_date"].astype(str).str[:6] < current_month].copy()
    right = fundamentals[
        fundamentals["announcement_date"].astype(str).le(as_of_date)
    ].copy()
    if left.empty or right.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "latest_signal_date": None,
            "eligible_count": 0,
            "data_ready": False,
        }
    left["trade_date"] = left["trade_date"].astype(str)
    right["announcement_date"] = right["announcement_date"].astype(str)
    right["report_date"] = right["report_date"].astype(str)
    snapshots = []
    for trade_date, price_rows in left.groupby("trade_date", sort=True):
        available = right[
            right["announcement_date"].le(str(trade_date))
            & right["report_date"].lt(str(trade_date))
        ].sort_values(["ts_code", "report_date", "announcement_date"])
        if available.empty:
            continue
        recent = available.groupby("ts_code", sort=False).tail(3)
        history = recent.groupby("ts_code", sort=False).agg(
            report_count=("report_date", "count"),
            roe_3y_median=("roe", "median"),
            roe_3y_min=("roe", "min"),
            gross_margin_3y_median=("gross_margin", "median"),
            revenue_yoy_3y_median=("revenue_yoy", "median"),
            net_profit_yoy_3y_median=("net_profit_yoy", "median"),
            ocf_positive_years=("ocf_per_share", lambda values: int((values > 0).sum())),
            debt_to_assets_3y_max=("debt_to_assets", "max"),
        ).reset_index()
        latest_fundamental = available.groupby("ts_code", sort=False).tail(1)
        snapshot = price_rows.merge(latest_fundamental, on="ts_code", how="inner")
        snapshot = snapshot.merge(history, on="ts_code", how="left")
        snapshots.append(snapshot)
    if not snapshots:
        return pd.DataFrame(), pd.DataFrame(), {
            "latest_signal_date": None,
            "eligible_count": 0,
            "data_ready": False,
        }
    joined = pd.concat(snapshots, ignore_index=True)
    numeric_columns = [
        "close", "r1_amount_20", "eps", "book_value_per_share", "revenue_yoy",
        "net_profit_yoy", "roe", "ocf_per_share", "gross_margin",
        "debt_to_assets",
        "report_count", "roe_3y_median", "roe_3y_min",
        "gross_margin_3y_median", "revenue_yoy_3y_median",
        "net_profit_yoy_3y_median", "ocf_positive_years",
        "debt_to_assets_3y_max",
    ]
    for column in numeric_columns:
        joined[column] = pd.to_numeric(joined[column], errors="coerce")
    joined["pe_proxy"] = joined["close"] / joined["eps"]
    joined["pb_proxy"] = joined["close"] / joined["book_value_per_share"]
    safe_name = ~joined["name"].fillna("").str.upper().str.contains("ST|退", regex=True)
    eligible = joined[
        safe_name
        & joined["report_count"].ge(3)
        & joined["pe_proxy"].between(MIN_PE, MAX_PE)
        & joined["pb_proxy"].between(0, MAX_PB)
        & joined["r1_amount_20"].ge(MIN_AMOUNT_20)
        & joined["roe_3y_median"].ge(MIN_ROE)
        & joined["roe_3y_min"].ge(10)
        & joined["gross_margin_3y_median"].ge(MIN_GROSS_MARGIN)
        & joined["debt_to_assets_3y_max"].le(MAX_DEBT_TO_ASSETS)
        & joined["revenue_yoy_3y_median"].ge(0)
        & joined["net_profit_yoy_3y_median"].ge(0)
        & joined["ocf_positive_years"].ge(3)
    ].copy()
    if eligible.empty:
        latest = str(left["trade_date"].max()) if not left.empty else None
        return pd.DataFrame(), pd.DataFrame(), {
            "latest_signal_date": latest,
            "eligible_count": 0,
            "data_ready": True,
        }
    eligible["earnings_yield"] = 1 / eligible["pe_proxy"]
    score_parts = {
        "roe_rank": ("roe_3y_median", True),
        "margin_rank": ("gross_margin_3y_median", True),
        "growth_rank": ("net_profit_yoy_3y_median", True),
        "cash_rank": ("ocf_per_share", True),
        "debt_rank": ("debt_to_assets_3y_max", False),
        "earnings_yield_rank": ("earnings_yield", True),
        "pb_rank": ("pb_proxy", False),
    }
    for output, (source, higher_is_better) in score_parts.items():
        eligible[output] = eligible.groupby("trade_date")[source].rank(
            pct=True,
            ascending=higher_is_better,
        )
    eligible["quality_score"] = eligible[
        ["roe_rank", "margin_rank", "growth_rank", "cash_rank", "debt_rank"]
    ].mean(axis=1)
    eligible["value_score"] = eligible[
        ["earnings_yield_rank", "pb_rank"]
    ].mean(axis=1)
    eligible["value_quality_score"] = (
        eligible["quality_score"] * 0.65 + eligible["value_score"] * 0.35
    ) * 100
    selected = (
        eligible.sort_values(
            ["trade_date", "value_quality_score", "r1_amount_20", "ts_code"],
            ascending=[True, False, False, True],
        )
        .groupby("trade_date", sort=False)
        .head(PORTFOLIO_SIZE)
        .copy()
    )
    latest_signal_date = str(selected["trade_date"].max())
    latest = selected[selected["trade_date"] == latest_signal_date].copy()
    return selected, latest, {
        "latest_signal_date": latest_signal_date,
        "eligible_count": int((eligible["trade_date"] == latest_signal_date).sum()),
        "data_ready": True,
        "report_date": str(latest["report_date"].max()) if not latest.empty else None,
    }
