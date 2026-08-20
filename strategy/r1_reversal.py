"""R1 三月错杀修复：月度、流动性约束的 A 股反转策略。

策略逻辑在查看冻结留出区间前确定：

1. 每个完整自然月的最后一个交易日计算信号；
2. 形成期为 t-65 到 t-5，跳过最近一周，避免把极短期噪声当趋势；
3. 在价格不低于 2 元、20 日平均成交额不低于 1 亿元的股票中，选择
   形成期收益最低的 10%；
4. 仅当全市场 20 日收益中位数大于 0 时交易；
5. 从候选中取 20 日平均成交额最高的 20 只，次日开盘等权买入，
   第 21 个交易日开盘退出（持有 20 个交易日）。

该模块只生成信号。回撤、滚动训练门控和网页输出位于
``strategy.dashboard``，以便所有策略共享同一执行和成本口径。
"""

from __future__ import annotations

import sys

import pandas as pd

from strategy import loader


FORMATION_LOOKBACK = 65
SKIP_RECENT_DAYS = 5
MARKET_LOOKBACK = 20
LIQUIDITY_LOOKBACK = 20
MIN_AMOUNT_20 = 100_000  # Tushare amount 单位为千元，即约 1 亿元
MIN_CLOSE = 2.0
LOSER_QUANTILE = 0.10
PORTFOLIO_SIZE = 20
HOLDING_DAYS = 20


def add_features(frame: pd.DataFrame, *, copy: bool = True) -> pd.DataFrame:
    """Add trailing-only R1 features to a ts_code/trade_date-sorted frame."""
    data = frame.copy() if copy else frame
    daily_return = (
        pd.to_numeric(data["pct_chg"], errors="coerce")
        .div(100)
        .clip(lower=-0.95)
        .fillna(0)
    )
    # Tushare's daily pct_chg is based on the ex-right adjusted previous close.
    # Chaining it produces a point-in-time price index without false crashes on
    # cash-dividend or split dates.  Its level is arbitrary; its returns are not.
    data["r1_adjusted_close_index"] = (1 + daily_return).groupby(
        data["ts_code"], sort=False
    ).cumprod()
    data["r1_adjusted_open_index"] = (
        data["r1_adjusted_close_index"]
        * pd.to_numeric(data["open"], errors="coerce")
        / pd.to_numeric(data["close"], errors="coerce")
    )
    grouped = data.groupby("ts_code", sort=False)
    data["r1_formation_return"] = (
        grouped["r1_adjusted_close_index"].shift(SKIP_RECENT_DAYS)
        / grouped["r1_adjusted_close_index"].shift(FORMATION_LOOKBACK)
        - 1
    )
    data["r1_market_return_20"] = (
        data["r1_adjusted_close_index"]
        / grouped["r1_adjusted_close_index"].shift(MARKET_LOOKBACK)
        - 1
    )
    data["r1_amount_20"] = (
        grouped["amount"]
        .rolling(LIQUIDITY_LOOKBACK, min_periods=LIQUIDITY_LOOKBACK)
        .mean()
        .droplevel(0)
    )
    data["r1_market_median_20"] = data.groupby("trade_date")[
        "r1_market_return_20"
    ].transform("median")
    return data


def select_signals(
    frame: pd.DataFrame,
    as_of_date: str,
) -> tuple[pd.Series, pd.DataFrame, dict[str, object]]:
    """Return historical R1 signal mask and latest completed-month observations.

    The current, incomplete calendar month is never treated as a month end.
    Observation rows ignore the market-regime gate so the UI can explain which
    stocks would qualify if the gate were open; the returned signal mask always
    enforces the gate.
    """
    month = frame["trade_date"].astype(str).str[:6]
    complete = frame[month < as_of_date[:6]]
    if complete.empty:
        return pd.Series(False, index=frame.index), frame.iloc[0:0].copy(), {
            "latest_signal_date": None,
            "market_regime_open": False,
        }

    complete_month = complete["trade_date"].astype(str).str[:6]
    month_end_dates = set(complete.groupby(complete_month)["trade_date"].max())
    month_end_mask = frame["trade_date"].isin(month_end_dates)
    eligible = (
        month_end_mask
        & frame["close"].ge(MIN_CLOSE)
        & frame["r1_amount_20"].ge(MIN_AMOUNT_20)
        & frame["r1_formation_return"].notna()
    )

    candidate_rows = frame.loc[eligible].copy()
    candidate_rows["r1_formation_rank_pct"] = candidate_rows.groupby("trade_date")[
        "r1_formation_return"
    ].rank(pct=True)
    loser_rows = candidate_rows[
        candidate_rows["r1_formation_rank_pct"] <= LOSER_QUANTILE
    ].copy()
    regime_rows = loser_rows[loser_rows["r1_market_median_20"] > 0].copy()
    selected_rows = (
        regime_rows.sort_values(
            ["trade_date", "r1_amount_20", "ts_code"],
            ascending=[True, False, True],
        )
        .groupby("trade_date", sort=False)
        .head(PORTFOLIO_SIZE)
    )
    signal_mask = pd.Series(frame.index.isin(selected_rows.index), index=frame.index)

    latest_signal_date = str(max(month_end_dates))
    latest_observations = (
        loser_rows[loser_rows["trade_date"] == latest_signal_date]
        .sort_values(["r1_amount_20", "ts_code"], ascending=[False, True])
        .head(PORTFOLIO_SIZE)
        .copy()
    )
    latest_market_value = latest_observations["r1_market_median_20"].dropna()
    market_regime_open = bool(
        not latest_market_value.empty and float(latest_market_value.iloc[0]) > 0
    )
    return signal_mask, latest_observations, {
        "latest_signal_date": latest_signal_date,
        "market_regime_open": market_regime_open,
        "market_median_20_pct": (
            round(float(latest_market_value.iloc[0]) * 100, 2)
            if not latest_market_value.empty
            else None
        ),
        "selected_signal_count": int(signal_mask.sum()),
    }


def screen(on_date: str | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    """Build the latest R1 observation list from the local database."""
    on_date = on_date or loader.latest_trade_date()
    if not on_date:
        raise RuntimeError("daily table is empty")
    data = loader.load_all(
        start="20240101",
        end=on_date,
        columns=("open", "close", "amount", "pct_chg"),
    )
    featured = add_features(data)
    _, observations, context = select_signals(featured, on_date)
    observations = observations.merge(loader.stock_names(), on="ts_code", how="left")
    return observations, context


def _report(rows: pd.DataFrame, context: dict[str, object]) -> None:
    print("R1 三月错杀修复")
    print(f"信号日: {context.get('latest_signal_date') or '--'}")
    print(f"市场门控: {'开启' if context.get('market_regime_open') else '关闭'}")
    print(f"市场20日中位数: {context.get('market_median_20_pct')}%")
    if rows.empty:
        print("没有候选")
        return
    columns = [
        "ts_code", "name", "industry", "close",
        "r1_formation_return", "r1_amount_20",
    ]
    print(rows[columns].to_string(index=False))


if __name__ == "__main__":
    requested_date = sys.argv[1] if len(sys.argv) > 1 else None
    result, signal_context = screen(requested_date)
    _report(result, signal_context)
