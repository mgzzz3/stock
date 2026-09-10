"""Fixed-rule market-sentiment research with executable, cash-aware replay.

No parameter search. Run: python -m strategy.emotion --output reports/emotion.json
Daily breadth is a price/volume proxy, not news or investor-survey sentiment.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HOLDING_DAYS = 5
PORTFOLIO_SIZE = 10
SIDE_COST = 0.001
TRAIN_DAYS = 252
TEST_DAYS = 21
MIN_TRAIN_COHORTS = 8
RULE_VERSION = "emotion-v1"
SPECS = (
    ("emotion_repair", "E1 冰点修复", "冰点后等待市场回暖，选择已经止跌的流动性股票。",
     "昨日上涨占比≤25%；今日≥45%且提升≥20个百分点；个股涨幅0%～5%、近5日收益<0。"),
    ("emotion_thrust", "E2 广度转强", "市场参与面从低迷转向普涨，参与具有中期相对强度的股票。",
     "昨日5日平均上涨占比≤45%；今日上涨占比≥65%、涨幅中位数>0.5%；个股涨幅0%～5%、20日收益高于市场中位数。"),
    ("emotion_resilience", "E3 分歧承接", "市场中期趋势向上但当日分歧，观察仍有正向承接的股票。",
     "市场20日收益中位数>0；当日上涨占比25%～45%、涨幅中位数<0；个股涨幅0%～3%、20日收益高于市场中位数且收盘高于MA20。"),
    ("emotion_cooling", "E4 降温回踩", "普涨过热后等待情绪降温，在中期趋势仍向上时观察缩量回踩。",
     "此前5日上涨占比最大值≥80%；今日上涨占比40%～60%、较昨日下降≥10个百分点；市场20日收益中位数>0；个股跌幅0%～3%、收盘高于MA20、量比<1。"),
)


@dataclass
class Market:
    dates: list[str]
    codes: list[str]
    values: dict[str, np.ndarray]
    features: dict[str, np.ndarray]
    sentiment: pd.DataFrame
    lookup: dict[str, dict]
    data_audit: dict = field(default_factory=dict)


def prepare_market(frame: pd.DataFrame, stocks: pd.DataFrame, *, min_market: int = 500) -> Market:
    """Past/current data only; missing bars never become executable prices."""
    frame = frame.sort_values(["trade_date", "ts_code"])
    dates = sorted(frame.trade_date.unique().tolist())
    codes = sorted(frame.ts_code.unique().tolist())
    pivots = {column: frame.pivot(index="trade_date", columns="ts_code", values=column)
              .reindex(index=dates, columns=codes).astype(float)
              for column in ("open", "close", "pre_close", "pct_chg", "vol", "amount")}
    return prepare_pivots(pivots, stocks, min_market=min_market)


def prepare_pivots(pivots: dict[str, pd.DataFrame], stocks: pd.DataFrame, *, min_market: int = 500) -> Market:
    """Feature kernel shared by small fixtures and the bounded-memory loader."""
    dates = pivots['close'].index.astype(str).tolist()
    codes = pivots['close'].columns.astype(str).tolist()
    close, pct = pivots["close"], pivots["pct_chg"]
    valid = (close.gt(0) & pivots["open"].gt(0) & pivots["pre_close"].gt(0)
             & pivots["vol"].gt(0) & pct.notna() & pct.gt(-100))
    # pct_chg removes ex-right discontinuities. Missing sessions carry marks,
    # while raw open and volume are still required for an execution.
    adj = (1 + pct.where(valid).div(100).fillna(0)).cumprod()
    adjusted_open = (adj * pivots["open"] / close).where(valid)
    ret5, ret20 = adj / adj.shift(5) - 1, adj / adj.shift(20) - 1
    ma20 = adj.rolling(20, min_periods=20).mean()
    amount20 = pivots["amount"].where(valid).rolling(20, min_periods=20).mean()
    volume_ratio = pivots["vol"] / pivots["vol"].shift(1).rolling(20, min_periods=20).mean()
    seasoned = valid.cumsum().ge(60)
    breadth_pool = valid & seasoned
    count = breadth_pool.sum(axis=1)
    coverage = count.ge(min_market) & count.ge(count.shift(1).rolling(20, min_periods=1).median() * .9)
    breadth = pct.gt(0).where(breadth_pool).mean(axis=1).where(coverage)
    sentiment = pd.DataFrame({"breadth": breadth, "median_pct": pct.where(breadth_pool).median(axis=1).where(coverage),
                              "market_ret20": ret20.where(breadth_pool).median(axis=1).where(coverage),
                              "stock_count": count, "coverage_ok": coverage})
    sentiment["breadth_prev"] = breadth.shift(1)
    sentiment["breadth_mean5_prev"] = breadth.shift(1).rolling(5, min_periods=5).mean()
    sentiment["breadth_max5_prev"] = breadth.shift(1).rolling(5, min_periods=5).max()
    # No current stock name/industry is used for historical selection.
    eligible = valid & seasoned & close.ge(2) & amount20.ge(100_000)
    gap = pivots["open"] / pivots["pre_close"] - 1
    # Conservative 4.8% sell lock proxy also covers historical main-board ST.
    sellable = valid & gap.gt(-.048)
    next_sell = np.full(valid.shape, -1, dtype=np.int32)
    next_index = np.full(len(codes), -1, dtype=np.int32)
    for t in range(len(dates) - 1, -1, -1):
        next_index = np.where(sellable.iloc[t].to_numpy(), t, next_index)
        next_sell[t] = next_index
    values = {key: value.to_numpy() for key, value in pivots.items()}
    values.update(adj_close=adj.to_numpy(), adj_open=adjusted_open.to_numpy(),
                  entry_ok=(valid & gap.ge(-.03) & gap.le(.03)).to_numpy(), next_sell=next_sell)
    features = {"eligible": eligible.to_numpy(), "ret5": ret5.to_numpy(), "ret20": ret20.to_numpy(),
                "above_ma20": adj.gt(ma20).to_numpy(), "volume_ratio": volume_ratio.to_numpy(),
                "amount20": amount20.to_numpy()}
    lookup = stocks.drop_duplicates("ts_code").set_index("ts_code").fillna("").to_dict("index")
    return Market(dates, codes, values, features, sentiment, lookup)


def select_candidates(market: Market, strategy_id: str) -> list[np.ndarray]:
    f, v, s = market.features, market.values, market.sentiment
    b, prev, middle = s.breadth, s.breadth_prev, s.market_ret20
    pct = v["pct_chg"]
    if strategy_id == "emotion_repair":
        regime = prev.le(.25) & b.ge(.45) & (b - prev).ge(.20)
        stock = (pct >= 0) & (pct <= 5) & (f["ret5"] < 0)
        score = -f["ret5"]
    elif strategy_id == "emotion_thrust":
        regime = s.breadth_mean5_prev.le(.45) & b.ge(.65) & s.median_pct.gt(.5)
        stock = (pct >= 0) & (pct <= 5) & (f["ret20"] > middle.to_numpy()[:, None])
        score = f["ret20"]
    elif strategy_id == "emotion_resilience":
        regime = middle.gt(0) & b.between(.25, .45) & s.median_pct.lt(0)
        stock = (pct >= 0) & (pct <= 3) & (f["ret20"] > middle.to_numpy()[:, None]) & f["above_ma20"]
        score = f["ret20"]
    elif strategy_id == "emotion_cooling":
        regime = s.breadth_max5_prev.ge(.8) & b.between(.4, .6) & (prev - b).ge(.1) & middle.gt(0)
        stock = (pct >= -3) & (pct <= 0) & f["above_ma20"] & (f["volume_ratio"] < 1)
        score = -f["volume_ratio"]
    else:
        raise ValueError(strategy_id)
    mask = stock & f["eligible"] & regime.to_numpy()[:, None] & np.isfinite(score)
    result = []
    for t in range(len(market.dates)):
        indices = np.flatnonzero(mask[t])
        order = np.lexsort((indices, -f["amount20"][t, indices], -score[t, indices]))
        result.append(indices[order][:PORTFOLIO_SIZE])
    return result


def replay_cohort(m: Market, signal: int, candidates: np.ndarray, *, slots: int = PORTFOLIO_SIZE,
                  cost: float = SIDE_COST) -> dict:
    """Fixed initial slots; skipped buys stay cash, locked sells are deferred."""
    n = len(m.dates)
    entry, planned_exit = signal + 1, signal + HOLDING_DAYS + 1
    if entry >= n:
        return {"signal": signal, "entry": entry, "end": n, "complete": False,
                "path": np.array([]), "trades": [], "skipped": 0}
    picked = candidates[m.values["entry_ok"][entry, candidates]]
    exits = m.values["next_sell"][planned_exit, picked] if planned_exit < n else np.full(len(picked), -1)
    end = int(exits.max()) if len(exits) and (exits >= 0).all() else (n if len(picked) else entry)
    last = min(end, n - 1)
    axis = np.arange(entry, last + 1)
    path = np.ones(len(axis), dtype=float)
    trades = []
    if len(picked):
        entry_prices = m.values["adj_open"][entry, picked]
        marks = m.values["adj_close"][entry:last + 1, picked] / entry_prices / (1 + cost)
        for column, (stock, exit_t) in enumerate(zip(picked, exits)):
            net = None
            if exit_t >= 0:
                gross = m.values["adj_open"][exit_t, stock] / entry_prices[column] - 1
                net = (1 + gross) / (1 + cost) * (1 - cost) - 1
                marks[axis >= exit_t, column] = 1 + net
            trades.append({"stock": int(stock), "signal": signal, "entry": entry, "exit": int(exit_t),
                           "net": float(net) if net is not None else None,
                           "gross": float(gross) if net is not None else None,
                           "delayed": bool(planned_exit < n and (exit_t < 0 or exit_t > planned_exit))})
        path += (marks - 1).sum(axis=1) / slots
    return {"signal": signal, "entry": entry, "end": end, "complete": end < n,
            "path": path, "trades": trades, "skipped": int(len(candidates) - len(picked))}


def simulate(m: Market, candidates: list[np.ndarray], allowed: np.ndarray | None = None,
             *, cost: float = SIDE_COST) -> tuple[list[dict], list[dict]]:
    """One non-overlapping cohort at a time; no re-entry before actual exit."""
    n = len(m.dates)
    allowed = np.ones(n, bool) if allowed is None else allowed
    nav = np.ones(n)
    capital, available = 1.0, 0
    cohorts = []
    for t, picks in enumerate(candidates):
        if t < available or not allowed[t] or not len(picks) or t + 1 >= n:
            continue
        cohort = replay_cohort(m, t, picks, cost=cost)
        end = min(cohort["end"], n - 1)
        nav[cohort["entry"]:end + 1] = capital * cohort["path"]
        capital = float(nav[end])
        nav[end + 1:] = capital
        available = cohort["end"]
        cohorts.append(cohort)
    peak = np.maximum.accumulate(np.maximum(nav, 1))
    returns = nav / np.r_[1.0, nav[:-1]] - 1
    curve = [{"date": date, "nav": round(float(nav[t]), 6),
              "drawdown_pct": round(float(nav[t] / peak[t] - 1) * 100, 3),
              "daily_return_pct": round(float(returns[t]) * 100, 3)} for t, date in enumerate(m.dates)]
    return cohorts, curve


def attach_baselines(m: Market, cohorts: list[dict], cache: dict, *, cost: float = SIDE_COST) -> None:
    for cohort in cohorts:
        t = cohort["signal"]
        key = (t, cost)
        if key not in cache:
            pool = np.flatnonzero(m.features["eligible"][t])
            replay = replay_cohort(m, t, pool, slots=max(len(pool), 1), cost=cost)
            # Baseline trade dictionaries can otherwise consume gigabytes over
            # a decade. Only its completion boundary and terminal value are used.
            cache[key] = {"end": replay["end"], "return": float(replay["path"][-1] - 1) if replay["complete"] else None}
        base = cache[key]
        cohort["baseline_end"] = base["end"]
        cohort["baseline_return"] = base["return"]


def walk_forward(m: Market, cohorts: list[dict]) -> tuple[np.ndarray, list[dict]]:
    allowed = np.zeros(len(m.dates), bool)
    windows = []
    for start in range(TRAIN_DAYS, len(m.dates), TEST_DAYS):
        end = min(start + TEST_DAYS, len(m.dates))
        training = [c for c in cohorts if start - TRAIN_DAYS <= c["signal"] < start
                    and c["trades"] and c["complete"] and c["end"] < start and c["baseline_end"] < start]
        nets = np.array([c["path"][-1] - 1 for c in training])
        excess = np.array([c["path"][-1] - 1 - c["baseline_return"] for c in training])
        count = sum(len(c["trades"]) for c in training)
        approved = bool(len(training) >= MIN_TRAIN_COHORTS and count >= 40
                        and nets.mean() > 0 and excess.mean() > 0 and (nets > 0).mean() >= .5)
        allowed[start:end] = approved
        windows.append({"training_start": m.dates[start - TRAIN_DAYS], "training_end": m.dates[start - 1],
                        "test_start": m.dates[start], "test_end": m.dates[end - 1],
                        "training_signal_count": count, "training_cohort_count": len(training),
                        "training_net_mean_return_pct": pct_mean(nets),
                        "training_excess_return_pct": pct_mean(excess),
                        "training_win_rate_pct": pct_mean(nets > 0) if len(nets) else None,
                        "approved": approved})
    return allowed, windows


def pct_mean(values) -> float | None:
    return round(float(np.mean(values)) * 100, 3) if len(values) else None


def validation_status(paired_cohorts: int, supported: bool) -> tuple[str, str]:
    """Separate a disproved rule from one that merely lacks observations."""
    if supported:
        return "watch", "历史初验通过"
    if paired_cohorts >= 20:
        return "retired", "长期样本未通过"
    return "watch", "样本外证据不足"


def evidence(cohorts: list[dict], curve: list[dict]) -> dict:
    completed = [c for c in cohorts if c["complete"] and c["trades"]]
    trades = [t for c in cohorts for t in c["trades"] if t["net"] is not None]
    paired = [c for c in completed if c.get("baseline_return") is not None]
    nets = np.array([c["path"][-1] - 1 for c in completed])
    excess = np.array([c["path"][-1] - 1 - c["baseline_return"] for c in paired])
    # Non-overlapping date cohorts, not correlated stock rows; Bonferroni for
    # the four declared hypotheses. An interval is descriptive, not a guarantee.
    interval = None
    if len(excess) >= 8:
        rng = np.random.default_rng(20260907)
        # Resample consecutive blocks of 3 cohorts to retain short dependence.
        starts = rng.integers(0, len(excess), size=(4000, (len(excess) + 2) // 3))
        indices = ((starts[:, :, None] + np.arange(3)) % len(excess)).reshape(4000, -1)[:, :len(excess)]
        interval = [round(float(x) * 100, 3) for x in np.quantile(excess[indices].mean(axis=1), [.00625, .99375])]
    return {"signal_count": len(trades), "signal_dates": len(completed), "cohort_count": len(completed),
            "paired_cohort_count": len(paired), "unique_stock_count": len({t["stock"] for t in trades}),
            "mean_return_pct": pct_mean([t["gross"] for t in trades]),
            "net_mean_return_pct": pct_mean([t["net"] for t in trades]),
            "win_rate_pct": pct_mean([t["net"] > 0 for t in trades]),
            "cohort_net_mean_pct": pct_mean(nets), "excess_return_pct": pct_mean(excess),
            "baseline_return_pct": pct_mean([c["baseline_return"] for c in paired]),
            "excess_ci_familywise95_pct": interval,
            "max_drawdown_pct": min((p["drawdown_pct"] for p in curve), default=None),
            "latest_nav": curve[-1]["nav"] if curve else None,
            "total_return_pct": round((curve[-1]["nav"] - 1) * 100, 3) if curve else None,
            "skipped_buys": sum(c["skipped"] for c in cohorts),
            "delayed_exits": sum(t["delayed"] for c in cohorts for t in c["trades"]),
            "pending_trades": sum(t["net"] is None for c in cohorts for t in c["trades"])}


def reasons(m: Market, t: int, stock: int) -> list[str]:
    s = m.sentiment.iloc[t]
    return [f"市场上涨占比 {s.breadth * 100:.1f}%，前日 {s.breadth_prev * 100:.1f}%",
            f"市场20日收益中位数 {s.market_ret20 * 100:.1f}%",
            f"个股20日收益 {m.features['ret20'][t, stock] * 100:.1f}%，20日均成交额 {m.features['amount20'][t, stock] / 100_000:.1f}亿元"]


def stock_row(m: Market, stock: int, t: int) -> dict:
    code = m.codes[stock]
    lookup = m.lookup.get(code, {})
    return {"ts_code": code, "name": lookup.get("name") or code, "industry": lookup.get("industry") or "未分类",
            "close": round(float(m.values["close"][t, stock]), 2),
            "pct_chg": round(float(m.values["pct_chg"][t, stock]), 2),
            "amount_billion": round(float(m.values["amount"][t, stock]) / 100_000, 2),
            "reasons": reasons(m, t, stock)}


def historical_cases(m: Market, full: list[dict], oos: list[dict]) -> dict:
    trades = [t for c in full for t in c["trades"] if t["net"] is not None]
    oos_keys = {(t["signal"], t["stock"]) for c in oos for t in c["trades"]}
    def cases(win):
        selected = sorted([t for t in trades if (t["net"] > 0) == win],
                          key=lambda t: (-t["signal"], t["stock"]))[:4]
        result = []
        for t in selected:
            row = stock_row(m, t["stock"], t["signal"])
            is_oos = (t["signal"], t["stock"]) in oos_keys
            row.update(outcome="win" if win else "loss", outcome_label="盈利" if win else "亏损",
                       signal_date=m.dates[t["signal"]], entry_date=m.dates[t["entry"]], exit_date=m.dates[t["exit"]],
                       gross_return_pct=round(t["gross"] * 100, 3), net_return_pct=round(t["net"] * 100, 3),
                       evidence_scope="rolling_oos" if is_oos else "full_sample",
                       evidence_label="滚动样本外" if is_oos else "全样本参考",
                       exit_reason="卖出受限后延迟退出" if t["delayed"] else "持有5个完整交易日后开盘退出")
            result.append(row)
        return result
    wins = sum(t["net"] > 0 for t in trades)
    return {"definition": "最近完成的4笔盈利与4笔亏损；按买卖各0.10%成本计算，含延迟退出。",
            "completed_count": len(trades), "win_count": wins, "loss_count": len(trades) - wins,
            "wins": cases(True), "losses": cases(False)}


def build_from_market(m: Market) -> list[dict]:
    result, baseline_cache = [], {}
    for strategy_id, name, thesis, rule in SPECS:
        candidates = select_candidates(m, strategy_id)
        full, curve = simulate(m, candidates)
        attach_baselines(m, full, baseline_cache)
        allowed, windows = walk_forward(m, full)
        oos, oos_curve_all = simulate(m, candidates, allowed)
        oos_curve = oos_curve_all[TRAIN_DAYS:]
        attach_baselines(m, oos, baseline_cache)
        metrics, oos_metrics = evidence(full, curve), evidence(oos, oos_curve)
        stress, stress_curve = simulate(m, candidates, allowed, cost=.0025)
        attach_baselines(m, stress, baseline_cache, cost=.0025)
        stress_metrics = evidence(stress, stress_curve[TRAIN_DAYS:])
        ci = oos_metrics["excess_ci_familywise95_pct"]
        supported = bool(oos_metrics["paired_cohort_count"] >= 20 and ci and ci[0] > 0
                         and (oos_metrics["total_return_pct"] or 0) > 0
                         and (stress_metrics["total_return_pct"] or 0) > 0)
        status, label = validation_status(
            oos_metrics["paired_cohort_count"], supported
        )
        raw_allowed = np.arange(len(m.dates)) >= TRAIN_DAYS
        raw_oos, raw_curve = simulate(m, candidates, raw_allowed)
        attach_baselines(m, raw_oos, baseline_cache)
        raw_metrics = evidence(raw_oos, raw_curve[TRAIN_DAYS:])
        year_metrics = []
        for year in sorted({date[:4] for date in m.dates[TRAIN_DAYS:]}):
            subset = [c for c in oos if m.dates[c["signal"]][:4] == year]
            stats = evidence(subset, [])
            year_metrics.append({"year": year, "cohort_count": stats["cohort_count"],
                                 "cohort_net_mean_pct": stats["cohort_net_mean_pct"], "excess_return_pct": stats["excess_return_pct"]})
        latest = len(m.dates) - 1
        holding = bool(oos and oos[-1]["end"] > latest)
        recommendations = []
        for rank, stock in enumerate(candidates[-1], 1):
            row = stock_row(m, int(stock), latest)
            row.update(rank=rank, action="仅观察", trigger="等待前瞻纸面验证；历史回放不直接下单")
            recommendations.append(row)
        metrics.update(period_start=m.dates[0], period_end=m.dates[-1])
        wf_metrics = {**oos_metrics, "period_start": m.dates[TRAIN_DAYS] if len(m.dates) > TRAIN_DAYS else None,
                      "period_end": m.dates[-1], "total_windows": len(windows),
                      "enabled_windows": sum(w["approved"] for w in windows),
                      "completed_oos_signal_count": oos_metrics["signal_count"],
                      "oos_signal_count": sum(len(c["trades"]) for c in oos),
                      "oos_mean_return_pct": oos_metrics["net_mean_return_pct"],
                      "latest_approved": bool(supported and allowed[-1])}
        ci_text = f"{ci[0]:.2f}%～{ci[1]:.2f}%" if ci else "样本不足"
        evidence_text = (f"滚动样本外完成 {oos_metrics['cohort_count']} 个不重叠组合、{oos_metrics['signal_count']} 笔交易；"
                         f"组合平均超额 {oos_metrics['excess_return_pct']}%，四策略多重检验校正区间 {ci_text}。"
                         f"未门控样本外 {raw_metrics['cohort_count']} 个组合，组合平均净收益 {raw_metrics['cohort_net_mean_pct']}%。"
                         f"高成本情景（往返约0.50%）滚动总收益 {stress_metrics['total_return_pct']}%。")
        method = "收盘信号、次日开盘建仓；10个固定资金槽、每槽10%，不足或跳过保留现金；持有5个完整交易日后开盘退出，受限顺延；按持股与现金逐日计价，买卖各0.10%成本。"
        result.append({"id": strategy_id, "name": name, "short_name": name, "category": "emotion",
                       "status": status, "status_label": label, "confidence": "历史研究",
                       "thesis": thesis, "evidence": evidence_text,
                       "signal_rule": rule + "统一要求有60根有效日线、股价≥2元、20日均成交额≥1亿元；每日最多10只：E1按5日跌幅、E2/E3按20日收益、E4按缩量程度优先；同分按成交额降序、代码升序。",
                       "exit_rule": "次日开盘价相对当日行情pre_close（除权参考价）在±3%内且有成交才买入；第6个后续交易日开盘卖出。缺行情/停牌或开盘跌幅≥4.8%则延迟，未退出继续计价。",
                       "position_rule": "研究模拟总资金100%、每股初始10%，空位留现金；前一组合全部退出后才接新信号，不重叠加仓。当前仅观察。",
                       "recommendation_label": "今日情绪观察",
                       "recommendation_note": ("模拟组合仍有未退出持仓；今日信号不加仓。" if holding else "") + "仅展示今日收盘规则候选；门控和成交条件不代表实盘批准。",
                       "current_signal_count": len(candidates[-1]), "recommendations": recommendations,
                       "metrics": metrics, "curve": curve, "curve_method": method,
                       "walk_forward": {"training_days": TRAIN_DAYS, "test_days": TEST_DAYS,
                           "embargo_rule": "策略及同日基准均须在测试窗开始前完成；训练至少8个组合、40笔成交，组合净收益/超额>0、组合胜率≥50%。",
                           "gate": {"min_signal_count": 40, "min_cohort_count": MIN_TRAIN_COHORTS,
                                    "min_net_mean_return_pct": 0, "min_excess_return_pct": 0, "min_win_rate_pct": 50},
                           "windows": windows, "latest_window": windows[-1] if windows else None,
                           "metrics": wf_metrics, "curve": oos_curve, "curve_method": "252日滚动训练，随后21日仅按此前结果开关；" + method},
                       "credibility": {"evidence_level": "rolling_oos" if oos_metrics["signal_count"] else "full_sample_only",
                           "evidence_label": label, "history_years": round((pd.Timestamp(m.dates[-1]) - pd.Timestamp(m.dates[0])).days / 365.25, 1),
                           "price_history_start": m.dates[0], "price_history_end": m.dates[-1],
                           "completed_trade_count": metrics["signal_count"], "unique_stock_count": metrics["unique_stock_count"],
                           "signal_date_count": metrics["cohort_count"], "oos_completed_trade_count": oos_metrics["signal_count"],
                           "enabled_windows": wf_metrics["enabled_windows"], "total_windows": len(windows),
                           "sample_warning": "以不重叠组合日期为统计单位；3组合区块自助法保留短期相关性，并校正4次比较；历史伪样本外仍不等于新增数据前瞻验证。"},
                       "validation": {"rule_version": RULE_VERSION, "historically_supported": supported,
                           "raw_oos": raw_metrics, "stress_cost_pct": .5, "stress_oos": stress_metrics,
                           "oos_by_signal_year": year_metrics,
                           "acceptance_rule": "至少20个与基准均完成的滚动样本外配对组合；校正后超额区间下界>0、净值收益>0、高成本收益>0。未满足时不标记可靠。",
                           "benchmark": "同信号日、相同历史流动性股票池等权持有；相同开盘过滤/延迟卖出/成本，跳过的买入留现金；按组合日期配对超额。"},
                       "historical_cases": historical_cases(m, full, oos),
                       "known_limitations": ["情绪仅由行情广度和成交量代理，未使用新闻、龙虎榜或历史封单数据。",
                           "数据库约两年历史，股票基础表仅现存上市公司；历史行情含部分已退股票，但退市最终收益及历史风险警示未完整校验，存在覆盖偏差。",
                           "日线不能验证开盘排队成交；4.8%跌幅延迟卖出为保守代理，未逐笔还原涨跌停、停牌和冲击成本。",
                           "复权收益由pct_chg链式构建；缺行情按末次价格计价，无法反映缺失期间真实损失。",
                           "参数在本次回放前固定；这仍是历史伪样本外审计，需要后续新数据验证。"]})
    return result


def load_market(db_path: Path | str, as_of_date: str | None = None, *,
                archive_dir: Path | None = None) -> Market | None:
    """Fill dense numeric matrices in chunks; never concatenate a decade of strings."""
    db_path = Path(db_path).resolve()
    archive_dir = archive_dir or db_path.parent / 'history_daily'
    manifest_path = archive_dir / 'manifest.json'
    archive = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        as_of_date = as_of_date or conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
        if not as_of_date:
            return None
        db_dates = [row[0] for row in conn.execute('SELECT DISTINCT trade_date FROM daily WHERE trade_date<=? ORDER BY trade_date', [as_of_date])]
        files = {date: item for date, item in archive.get('files', {}).items() if date <= as_of_date}
        dates = sorted(set(db_dates) | set(files))
        if not dates:
            return None
        codes = sorted({row[0] for row in conn.execute('SELECT DISTINCT ts_code FROM daily WHERE trade_date<=?', [as_of_date])} | set(archive.get('codes', [])))
        date_index, code_index = pd.Index(dates), pd.Index(codes)
        columns = ('open', 'close', 'pre_close', 'pct_chg', 'vol', 'amount')
        arrays = {column: np.full((len(dates), len(codes)), np.nan) for column in columns}
        loaded_rows = 0
        def insert(chunk, date=None):
            nonlocal loaded_rows
            rows = date_index.get_indexer(chunk['trade_date']) if date is None else date_index.get_loc(date)
            stocks = code_index.get_indexer(chunk['ts_code'])
            if (stocks < 0).any():
                raise ValueError('Archive contains codes absent from its inventory')
            for column in columns:
                arrays[column][rows, stocks] = pd.to_numeric(chunk[column], errors='coerce').to_numpy()
            loaded_rows += len(chunk)
        query = 'SELECT ts_code,trade_date,' + ','.join(columns) + ' FROM daily WHERE trade_date<=?'
        for chunk in pd.read_sql_query(query, conn, params=[as_of_date], chunksize=100_000):
            chunk = chunk[~chunk.trade_date.isin(files)]
            insert(chunk)
        stocks = pd.read_sql_query('SELECT ts_code,name,industry,list_status,list_date,delist_date FROM stock_basic', conn)
    for date, item in sorted(files.items()):
        path = archive_dir / item['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'Archive checksum mismatch: {date}; rerun ingest.history_archive')
        chunk = pd.read_csv(path, usecols=['ts_code', *columns], dtype={'ts_code': str})
        if len(chunk) != item['row_count'] or chunk.ts_code.duplicated().any():
            raise ValueError(f'Archive row count or uniqueness mismatch: {date}')
        insert(chunk, date)
    pivots = {column: pd.DataFrame(values, index=date_index, columns=code_index, copy=False) for column, values in arrays.items()}
    market = prepare_pivots(pivots, stocks)
    expected = [date for date in archive.get('expected_sessions', []) if dates[0] <= date <= as_of_date]
    market.data_audit = {'period_start': dates[0], 'period_end': dates[-1], 'trading_days': len(dates),
                         'row_count': loaded_rows, 'stock_count': len(codes),
                         'archive_sessions': len(files), 'sqlite_sessions': len(set(db_dates) - set(files)),
                         'calendar_missing_sessions': sorted(set(expected) - set(dates)),
                         'calendar_source': archive.get('calendar_source'),
                         'metadata_status_counts': stocks.list_status.value_counts().to_dict(),
                         'archive_hashes_verified': True,
                         'source': 'Tushare daily (SQLite + compressed historical archive)'}
    return market


def build_strategies(db_path: Path | str, as_of_date: str | None = None) -> list[dict]:
    market = load_market(db_path, as_of_date)
    if market is None:
        return []
    strategies = build_from_market(market)
    for strategy in strategies:
        strategy['validation']['data_audit'] = market.data_audit
        strategy['known_limitations'][1] = (
            f"历史覆盖 {market.dates[0]}—{market.dates[-1]}；历史股票状态和退市终值仍不完整，存在覆盖与估值偏差。")
    return strategies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=ROOT / "data/stock.db")
    parser.add_argument("--date")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/emotion_validation.json")
    args = parser.parse_args()
    strategies = build_strategies(args.db_path, args.date)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "rule_version": RULE_VERSION,
               "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "strategies": strategies}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    for strategy in strategies:
        print(strategy["name"], strategy["status_label"], json.dumps(strategy["walk_forward"]["metrics"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
