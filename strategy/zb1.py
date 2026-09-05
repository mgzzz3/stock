"""ZB1: replay saved B1 predictions in a three-position, cash-backed portfolio.

Only archived next_day_<date>.csv rankings are used (never regenerated scores).
Signals execute on the next market session, not a suspended stock's next bar.
Positions have no expiry and remain open at the end of the replay.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pandas as pd

MAX_POSITIONS = 3
ACTIVATE_RETURN = 0.15
TAKE_PROFIT_RETURN = 0.10
STOP_RETURN = -0.05
SIDE_COST = 0.001


def load_rankings(data_dir: Path, as_of_date: str) -> dict[str, list[dict]]:
    """Rank only the largest industries in the entire same-day B1 pool.

    Count unique stocks before filtering predictions or excluding holdings.
    Tied largest industries share the candidate pool; missing industries do
    not form an industry. Never fill vacancies from a smaller industry.
    """
    rankings = {}
    for path in sorted((data_dir / "predictions").glob("next_day_*.csv")):
        date = path.stem.removeprefix("next_day_")
        if len(date) != 8 or not date.isdigit() or date > as_of_date:
            continue
        pool_path = data_dir / "signals" / f"b1_{date}.csv"
        if not pool_path.exists():
            continue
        pool = pd.read_csv(pool_path, dtype=str)
        predictions = pd.read_csv(path, dtype={"ts_code": str, "trade_date": str})
        if "ts_code" not in pool or not {"ts_code", "prob_up", "trade_date"}.issubset(predictions):
            raise ValueError(f"ZB1 股票池或预测文件缺少必需列：{date}")
        pool["ts_code"] = pool["ts_code"].str.strip().str.upper()
        pool = pool[pool["ts_code"].notna() & pool["ts_code"].ne("")].drop_duplicates("ts_code")
        industries = pool.get("industry", pd.Series("", index=pool.index)).fillna("").str.strip()
        pool["industry"] = industries
        pool = pool[~industries.isin(["", "未分类", "(unknown)"])]
        counts = pool["industry"].value_counts()
        largest = set(counts[counts.eq(counts.max())].index)
        selected_pool = pool[pool["industry"].isin(largest)].set_index("ts_code")
        codes = set(selected_pool.index)
        predictions["ts_code"] = predictions["ts_code"].str.strip().str.upper()
        # The Web exporter also assigns rank from saved row order.
        predictions["prediction_rank"] = range(1, len(predictions) + 1)
        predictions["prob_up"] = pd.to_numeric(predictions["prob_up"], errors="coerce")
        mask = (
            predictions["ts_code"].isin(codes)
            & predictions["trade_date"].eq(date)
            & predictions["prob_up"].between(0, 1)
        )
        if "prediction_pool" in predictions:
            mask &= predictions["prediction_pool"].eq("b1")
        # Use the industry snapshot in the B1 CSV, not prediction metadata or
        # today's stock_basic table, so historical membership is point-in-time.
        predictions["industry"] = predictions["ts_code"].map(selected_pool["industry"])
        predictions["b1_industry_count"] = predictions["industry"].map(counts)
        rankings[date] = predictions.loc[mask].drop_duplicates("ts_code").fillna("").to_dict("records")
    return rankings


def _bars_by_date(bars: pd.DataFrame) -> dict[str, dict[str, dict]]:
    """Use trailing pct_chg price indices to avoid false exits on ex-right days."""
    result: dict[str, dict[str, dict]] = {}
    for code, group in bars.sort_values(["ts_code", "trade_date"]).groupby("ts_code", sort=False):
        previous_close = None
        adjusted_close = 1.0
        for bar in group.to_dict("records"):
            prices = [bar.get(key) for key in ("open", "high", "low", "close")]
            if not all(pd.notna(p) and math.isfinite(float(p)) and float(p) > 0 for p in prices):
                continue
            if "vol" in bar and (pd.isna(bar["vol"]) or float(bar["vol"]) <= 0):
                continue
            close = float(bar["close"])
            if previous_close is not None:
                change = bar.get("pct_chg")
                ratio = 1 + float(change) / 100 if pd.notna(change) else close / previous_close
                if not math.isfinite(ratio) or ratio <= 0:
                    continue
                adjusted_close *= ratio
            previous_close = close
            factor = adjusted_close / close
            bar["factor"] = factor
            for key in ("open", "high", "low", "close"):
                bar[f"adj_{key}"] = float(bar[key]) * factor
            result.setdefault(str(bar["trade_date"]), {})[str(code)] = bar
    return result


def _above(price: float, target: float) -> bool:
    return price > target and not math.isclose(price, target, rel_tol=1e-10)


def _at_or_below(price: float, target: float) -> bool:
    return price < target or math.isclose(price, target, rel_tol=1e-10)


def exit_fill(position: dict, bar: dict, *, can_sell: bool) -> tuple[float, str] | None:
    """Gap fills use open. On ambiguous OHLC bars, the adverse exit wins.

    Before activation, a stop-loss touch takes precedence over the day's high.
    Otherwise assume high precedes low for a same-bar activation/retracement.
    Buy-day highs may activate protection, but T+1 forbids buy-day exits.
    """
    entry = position["entry_adjusted"]
    stop = entry * (1 + STOP_RETURN)
    profit = entry * (1 + TAKE_PROFIT_RETURN)
    activation = entry * (1 + ACTIVATE_RETURN)
    opening, low, high = (bar[f"adj_{key}"] for key in ("open", "low", "high"))
    if can_sell:
        if _at_or_below(opening, stop):
            return opening, "-5%止损（开盘跳空按开盘价）"
        if position["profit_armed"] and _at_or_below(opening, profit):
            return opening, "超过15%后回撤至10%（开盘按开盘价）"
        if position["profit_armed"] or _above(opening, activation):
            position["profit_armed"] = True
            if _at_or_below(low, profit):
                return profit, "超过15%后回撤至10%"
        elif _at_or_below(low, stop):
            return stop, "-5%止损"
    if _above(high, activation):
        position["profit_armed"] = True
    if can_sell and position["profit_armed"] and _at_or_below(low, profit):
        return profit, "超过15%后回撤至10%（日线先高后低假设）"
    return None


def simulate(bars: pd.DataFrame, rankings: dict[str, list[dict]], trade_dates: list[str]) -> dict:
    """Replay without rebalancing; split free cash across vacant slots at entry."""
    by_date = _bars_by_date(bars)
    positions: dict[str, dict] = {}
    cash, previous_nav, peak = 1.0, 1.0, 1.0
    pending: list[dict] = []
    trades, curve = [], []
    for date in sorted(set(trade_dates)):
        today = by_date.get(date, {})
        # These orders were fixed at the previous close. No current-day ranks.
        budget = cash / (MAX_POSITIONS - len(positions)) if len(positions) < MAX_POSITIONS else 0
        for candidate in pending:
            code = candidate["ts_code"]
            bar = today.get(code)
            if code in positions or bar is None or len(positions) >= MAX_POSITIONS or budget <= 0:
                continue
            entry = bar["adj_open"]
            positions[code] = {
                "ts_code": code, "name": candidate.get("name") or code,
                "industry": candidate.get("industry") or "未分类",
                "signal_date": candidate["trade_date"], "entry_date": date,
                "entry_price": float(bar["open"]), "entry_adjusted": entry,
                "prediction_rank": candidate["prediction_rank"],
                "b1_industry_count": candidate.get("b1_industry_count"),
                "units": budget / (1 + SIDE_COST) / entry, "invested": budget,
                "last_adjusted": entry, "last_price": float(bar["open"]),
                "last_factor": bar["factor"], "price_date": date,
                "profit_armed": False,
            }
            cash -= budget
        for code, position in list(positions.items()):
            bar = today.get(code)
            if bar is None:
                continue  # Keep suspended holdings and their last valuation.
            fill = exit_fill(position, bar, can_sell=date > position["entry_date"])
            if fill:
                price, reason = fill
                proceeds = position["units"] * price * (1 - SIDE_COST)
                cash += proceeds
                net = proceeds / position["invested"] - 1
                trades.append({
                    **{key: position[key] for key in ("ts_code", "name", "industry", "signal_date", "entry_date", "entry_price", "prediction_rank")},
                    "exit_date": date, "exit_price": round(price / bar["factor"], 4),
                    "gross_return_pct": round((price / position["entry_adjusted"] - 1) * 100, 4),
                    "net_return_pct": round(net * 100, 4), "exit_reason": reason,
                    "outcome": "win" if net > 0 else "loss",
                    "evidence_scope": "simulation", "evidence_label": "规则模拟",
                    "reasons": [f"B1最多行业：{position['industry']}（{position['b1_industry_count']}只）",
                                f"B1预测排名第{position['prediction_rank']}；次日开盘买入"],
                })
                del positions[code]
            else:
                position.update(last_adjusted=bar["adj_close"], last_price=float(bar["close"]),
                                last_factor=bar["factor"], price_date=date)
        nav = cash + sum(p["units"] * p["last_adjusted"] for p in positions.values())
        peak = max(peak, nav)
        curve.append({"date": date, "nav": round(nav, 6),
                      "drawdown_pct": round((nav / peak - 1) * 100, 4),
                      "daily_return_pct": round((nav / previous_nav - 1) * 100, 4),
                      "position_count": len(positions), "cash": round(cash, 8)})
        previous_nav = nav
        pending = [row for row in rankings.get(date, []) if row["ts_code"] not in positions][:MAX_POSITIONS - len(positions)]
    holdings = []
    for p in positions.values():
        holdings.append({**p, "holding_return_pct": round((p["last_adjusted"] / p["entry_adjusted"] - 1) * 100, 4),
                         "stop_price": round(p["entry_adjusted"] * 0.95 / p["last_factor"], 4),
                         "profit_exit_price": round(p["entry_adjusted"] * 1.10 / p["last_factor"], 4) if p["profit_armed"] else None})
    return {"holdings": holdings, "pending_buys": pending, "trades": trades, "curve": curve, "cash": cash}


def build_strategy(db_path: Path, as_of_date: str, data_dir: Path | None = None) -> dict:
    rankings = load_rankings(data_dir or db_path.parent, as_of_date)
    start = min(rankings, default=as_of_date)
    codes = sorted({row["ts_code"] for rows in rankings.values() for row in rows})
    with sqlite3.connect(db_path) as conn:
        dates = [str(row[0]) for row in conn.execute(
            "SELECT DISTINCT trade_date FROM daily WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date", (start, as_of_date))]
        # Bound parameters in chunks for SQLite builds with a 999-variable limit.
        frames = []
        for offset in range(0, len(codes), 500):
            chunk = codes[offset:offset + 500]
            frames.append(pd.read_sql_query(
                f"SELECT ts_code, trade_date, open, high, low, close, vol, pct_chg FROM daily WHERE ts_code IN ({','.join('?' for _ in chunk)}) AND trade_date BETWEEN ? AND ?",
                conn, params=[*chunk, start, as_of_date]))
    bars = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ts_code", "trade_date"])
    result = simulate(bars, rankings, dates)
    trades, curve = result["trades"], result["curve"]
    returns = pd.Series([t["net_return_pct"] for t in trades], dtype=float)
    wins = [t for t in reversed(trades) if t["outcome"] == "win"]
    losses = [t for t in reversed(trades) if t["outcome"] == "loss"]
    holdings = result["holdings"]
    recommendations = []
    for p in holdings:
        recommendations.append({
            "ts_code": p["ts_code"], "name": p["name"], "industry": p["industry"],
            "close": p["last_price"], "action": "继续持有", "trigger": "仅止盈回撤/止损退出",
            "reasons": [f"买入时B1最多行业：{p['industry']}（{p['b1_industry_count']}只）",
                        f"{p['entry_date']}开盘买入 {p['entry_price']:.2f}",
                        f"持有收益 {p['holding_return_pct']:+.2f}%",
                        "已激活10%回撤止盈" if p["profit_armed"] else "尚未超过15%",
                        f"估值行情日 {p['price_date']}"]})
    for candidate in result["pending_buys"]:
        recommendations.append({
            **{key: candidate.get(key) for key in ("ts_code", "name", "industry", "close")},
            "action": "待补仓", "trigger": "下一交易日开盘",
            "reasons": [f"B1最多行业：{candidate['industry']}（{candidate['b1_industry_count']}只）",
                        f"B1预测排名第{candidate['prediction_rank']}", f"信号日 {candidate['trade_date']}", "下一交易日开盘买入；无有效开盘价则放弃当日委托"]})
    for rank, row in enumerate(recommendations, 1):
        row["rank"] = rank
    latest_nav = curve[-1]["nav"] if curve else None
    metrics = {"period_start": start, "period_end": as_of_date, "signal_count": len(trades),
               "net_mean_return_pct": round(float(returns.mean()), 2) if trades else None,
               "win_rate_pct": round(len(wins) / len(trades) * 100, 2) if trades else None,
               "latest_nav": latest_nav,
               "total_return_pct": round((latest_nav - 1) * 100, 2) if latest_nav is not None else None,
               "max_drawdown_pct": min((p["drawdown_pct"] for p in curve), default=None)}
    return {
        "id": "zb1", "name": "ZB1", "short_name": "ZB1", "execution_mode": "portfolio_simulation",
        "status": "watch", "status_label": "自定义规则模拟", "confidence": "待验证",
        "thesis": "先选每日B1池中股票数量最多的行业，再按预测排名取前三，最多持有三只；只按15%→10%回撤止盈或-5%止损退出。",
        "evidence": f"从首份可用预测 {start} 连续模拟，已完成 {len(trades)} 笔交易；不回填历史预测、不强制清仓。",
        "signal_rule": "每日收盘后，按完整B1池的去重股票数选数量最多的行业（并列第一合并）；仅在这些行业内按已保存预测排名、跳过已持仓，选取空缺数量（最多3只），下一交易日开盘买入。不足时留现金，不跨到其他行业；行业缺失或无预测不买。",
        "exit_rule": "相对买入价的除权持有收益严格超过15%后，回落至10%或以下卖出；跌至-5%或以下止损。其余时间持续持有，无到期卖出；买入当日不卖。",
        "position_rule": "最多3只，不重复买入、不因排名或最多行业变化换仓。初始资金分3份；补仓时剩余现金按空位均分，不卖出其他持仓调仓。卖出后仍先按当日完整B1池统计最多行业，再按预测排名安排次日补仓。",
        "recommendation_label": "当前持仓与次日补仓", "current_signal_label": "最多行业预测候选",
        "recommendation_note": f"模拟持仓 {len(holdings)}/3，只在空位补仓；次日待买 {len(result['pending_buys'])} 只。此处不连接实盘账户。",
        "current_signal_count": len(rankings.get(as_of_date, [])), "metrics": metrics, "curve": curve,
        "curve_method": "现金+最多3只持仓逐日盯市，不每日再平衡；买卖各0.10%模拟成本，未平仓收益计入净值但不计入已完成交易胜率。",
        "credibility": {"evidence_label": "存档预测规则模拟", "completed_trade_count": len(trades),
                        "unique_stock_count": len({t['ts_code'] for t in trades}), "signal_date_count": len(rankings),
                        "sample_warning": "仅使用现存历史预测文件，不代表从策略发布日起的前瞻验证；存档缺日不交易，不使用今日模型重算过去。"},
        "known_limitations": [
            "日线无法还原盘中顺序：未激活时若同日触及-5%及超过15%，先按止损；否则同日激活回撤按先高后低估算。",
            "开盘跳空越过退出线按实际开盘价，不能保证成交收益恰为10%或-5%；停牌或无有效行情时保留持仓。",
            "除权用历史pct_chg链式价格指数近似；未模拟涨跌停排队、滑点、整手限制和实际税费差异。"],
        "historical_cases": {"definition": "最近4笔盈利和4笔亏损的已完成ZB1交易；未平仓不计入。", "completed_count": len(trades),
                             "win_count": len(wins), "loss_count": len(losses), "wins": wins[:4], "losses": losses[:4]},
        "recommendations": recommendations, "portfolio": result,
    }
