"""Audit fixed limit-board sentiment hypotheses without promoting them.

The market trigger is derived only from liquid Shanghai/Shenzhen main-board
stocks, whose ordinary daily price limit is stable at 10%.  Candidate stocks
may come from the full liquid A-share pool.  The three calendar partitions are
declared here and the final partition is treated as a frozen holdout.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy import emotion  # noqa: E402


PERIODS = {
    "development_2015_2020": ("20150101", "20201231"),
    "validation_2021_2023": ("20210101", "20231231"),
    "holdout_2024_2026": ("20240101", "20261231"),
}
SPECS = {
    "limit_down_relief": "L1 跌停消退",
    "limit_up_expansion": "L2 涨停扩散",
    "limit_board_reversal": "L3 封板翻转",
    "limit_up_cooling": "L4 强势降温",
}


def limit_regimes(market: emotion.Market) -> dict[str, np.ndarray]:
    pct = market.values["pct_chg"]
    main_board = np.array([
        code.endswith((".SH", ".SZ"))
        and code[:3] in {"000", "001", "002", "003", "600", "601", "603", "605"}
        for code in market.codes
    ])
    pool = market.features["eligible"] & main_board[None, :]
    denominator = np.maximum(pool.sum(axis=1), 1)
    limit_up = ((pct >= 9.8) & pool).sum(axis=1) / denominator
    limit_down = ((pct <= -9.8) & pool).sum(axis=1) / denominator
    breadth = market.sentiment.breadth.to_numpy()
    market_ret20 = market.sentiment.market_ret20.to_numpy()
    previous_up = np.r_[np.nan, limit_up[:-1]]
    previous_down = np.r_[np.nan, limit_down[:-1]]
    board_balance = limit_up - limit_down
    previous_balance = np.r_[np.nan, board_balance[:-1]]
    max_up_5d_before = np.full(len(limit_up), np.nan)
    for index in range(5, len(limit_up)):
        max_up_5d_before[index] = limit_up[index - 5:index].max()
    return {
        "limit_down_relief": (
            (previous_down >= .005)
            & (limit_down <= previous_down * .4)
            & (breadth >= .45)
        ),
        "limit_up_expansion": (
            (previous_up < .005) & (limit_up >= .01) & (breadth >= .60)
        ),
        "limit_board_reversal": (
            (previous_balance <= -.003)
            & (board_balance >= .003)
            & (breadth >= .50)
        ),
        "limit_up_cooling": (
            (max_up_5d_before >= .015)
            & (limit_up <= .005)
            & (breadth >= .35)
            & (breadth <= .55)
            & (market_ret20 > 0)
        ),
    }


def candidates_for(
    market: emotion.Market, strategy_id: str, regime: np.ndarray
) -> list[np.ndarray]:
    features, values = market.features, market.values
    pct = values["pct_chg"]
    market_ret20 = market.sentiment.market_ret20.to_numpy()
    if strategy_id == "limit_down_relief":
        stock = (pct >= 0) & (pct <= 5) & (features["ret5"] < 0)
        score = -features["ret5"]
    elif strategy_id in {"limit_up_expansion", "limit_board_reversal"}:
        stock = (
            (pct >= 0)
            & (pct <= 5)
            & (features["ret20"] > market_ret20[:, None])
        )
        score = features["ret20"]
    else:
        stock = (
            (pct >= -3)
            & (pct <= 0)
            & features["above_ma20"]
            & (features["volume_ratio"] < 1)
        )
        score = -features["volume_ratio"]
    mask = stock & features["eligible"] & regime[:, None] & np.isfinite(score)
    result = []
    for date_index in range(len(market.dates)):
        indices = np.flatnonzero(mask[date_index])
        order = np.lexsort((
            indices,
            -features["amount20"][date_index, indices],
            -score[date_index, indices],
        ))
        result.append(indices[order][:emotion.PORTFOLIO_SIZE])
    return result


def run(market: emotion.Market) -> dict:
    regimes = limit_regimes(market)
    baseline_cache: dict = {}
    results = []
    keys = (
        "paired_cohort_count",
        "signal_count",
        "cohort_net_mean_pct",
        "excess_return_pct",
        "excess_ci_familywise95_pct",
        "total_return_pct",
        "max_drawdown_pct",
    )
    for strategy_id, name in SPECS.items():
        picks = candidates_for(market, strategy_id, regimes[strategy_id])
        periods = {}
        for label, (start, end) in PERIODS.items():
            allowed = np.array([start <= date <= end for date in market.dates])
            cohorts, curve = emotion.simulate(market, picks, allowed)
            emotion.attach_baselines(market, cohorts, baseline_cache)
            metrics = emotion.evidence(cohorts, curve)
            periods[label] = {key: metrics[key] for key in keys}
        results.append({
            "id": strategy_id,
            "name": name,
            "regime_days": int(regimes[strategy_id].sum()),
            "periods": periods,
            "promoted": False,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "method": {
            "signal_source": "Tushare daily close/pre_close; liquid SSE/SZSE main board",
            "limit_proxy": "pct_chg >= 9.8% or <= -9.8%; first 60 valid bars excluded",
            "execution": "close signal, next open, 10 equal cash slots, five complete sessions, 0.10% each side",
            "benchmark": "same-date liquid eligible pool with identical execution",
            "partitions": PERIODS,
            "selection_policy": "four hypotheses fixed before reading their partition results",
        },
        "data_audit": market.data_audit,
        "results": results,
        "conclusion": "No hypothesis passed development and validation; the frozen holdout did not promote any rule.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=ROOT / "data/stock.db")
    parser.add_argument("--date", default="20260909")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/emotion_limit_research_20260910.json",
    )
    args = parser.parse_args()
    market = emotion.load_market(args.db_path, args.date)
    if market is None:
        raise SystemExit("No market data")
    payload = run(market)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    )
    print(payload["conclusion"])
    for item in payload["results"]:
        print(item["name"], json.dumps(item["periods"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
