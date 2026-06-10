"""可解释的 A 股次日涨跌预测、复盘与无未来数据滚动回测。

预测目标是信号日 t 收盘后，在下一交易日开盘买入并持有到收盘的收益：
``close[t+1] / open[t+1] - 1``。这样预测结果具备可执行含义，也不会把无法成交的
隔夜跳空误认为策略收益。

模型仅使用日线 OHLCV 派生特征，采用带 L2 正则的逻辑回归。每次预测都重新训练，
训练样本只包含信号日之前、且在当时已经能知道结果的记录。输出中的“原因”是模型
特征贡献（相关性解释），不是确定的因果关系或收益承诺。

常用命令：
    uv run python -m strategy.next_day predict             # 预测数据库最新日之后一日
    uv run python -m strategy.next_day predict 20260601    # 用 06-01 收盘数据预测 06-02
    uv run python -m strategy.next_day review 20260601     # 复盘 06-01 → 06-02
    uv run python -m strategy.next_day backtest 20260101 20260601

预测候选严格来自信号日的 B1 股票池；默认使用约 3 个交易年的历史样本训练。
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from store.db import connect

FEATURES = (
    "ret_1d",
    "ret_3d",
    "ret_5d",
    "close_vs_ma5",
    "close_vs_ma20",
    "ma5_vs_ma20",
    "volume_ratio_5d",
    "amount_ratio_20d",
    "intraday_ret",
    "range_pct",
    "close_position",
    "volatility_10d",
    "market_ret_1d",
    "relative_strength_1d",
)

FEATURE_LABELS = {
    "ret_1d": "1日动量",
    "ret_3d": "3日动量",
    "ret_5d": "5日动量",
    "close_vs_ma5": "价格相对5日均线",
    "close_vs_ma20": "价格相对20日均线",
    "ma5_vs_ma20": "短中期均线趋势",
    "volume_ratio_5d": "量能相对5日均量",
    "amount_ratio_20d": "成交额相对20日均值",
    "intraday_ret": "当日开收到收",
    "range_pct": "当日振幅",
    "close_position": "收盘在日内区间位置",
    "volatility_10d": "10日波动率",
    "market_ret_1d": "市场当日强弱",
    "relative_strength_1d": "个股相对市场强度",
}

EPSILON = 1e-12
DEFAULT_TRAIN_DAYS = 756
B1_STRATEGY = "b1"


@dataclass
class Model:
    weights: np.ndarray
    means: np.ndarray
    scales: np.ndarray
    feature_names: tuple[str, ...]
    baseline_rate: float
    training_rows: int
    training_start: str
    training_end: str


def load_bars(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """从 SQLite 读取全市场日线和股票名称。"""
    sql = """
        SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close,
               d.pre_close, d.vol, d.amount, s.name, s.industry
        FROM daily d
        LEFT JOIN stock_basic s ON s.ts_code = d.ts_code
    """
    where: list[str] = []
    params: list[str] = []
    if start:
        where.append("d.trade_date >= ?")
        params.append(start)
    if end:
        where.append("d.trade_date <= ?")
        params.append(end)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.ts_code, d.trade_date"
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def load_b1_pool(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """读取已持久化的 B1 股票池成员，供预测和回测按日筛选候选。"""
    sql = "SELECT ts_code, trade_date FROM signals WHERE strategy = ?"
    params: list[str] = [B1_STRATEGY]
    if start:
        sql += " AND trade_date >= ?"
        params.append(start)
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)
    sql += " ORDER BY trade_date, ts_code"
    with connect() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def _pool_codes(b1_pool: pd.DataFrame, signal_date: str) -> set[str]:
    if b1_pool.empty:
        return set()
    rows = b1_pool[b1_pool["trade_date"].astype(str) == signal_date]
    return set(rows["ts_code"].dropna().astype(str))


def build_dataset(bars: pd.DataFrame) -> pd.DataFrame:
    """构造只依赖当前及历史行情的特征，并附加次日可交易收益标签。"""
    if bars.empty:
        return bars.copy()

    df = bars.copy().sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    numeric = ["open", "high", "low", "close", "pre_close", "vol", "amount"]
    for column in numeric:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    grouped = df.groupby("ts_code", sort=False, group_keys=False)
    previous_close = df["pre_close"].where(df["pre_close"] > 0, grouped["close"].shift(1))
    df["ret_1d"] = df["close"] / previous_close - 1
    df["ret_3d"] = grouped["close"].pct_change(3, fill_method=None)
    df["ret_5d"] = grouped["close"].pct_change(5, fill_method=None)

    ma5 = grouped["close"].rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)
    ma20 = grouped["close"].rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    vol5 = grouped["vol"].rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)
    amount20 = grouped["amount"].rolling(20, min_periods=20).mean().reset_index(level=0, drop=True)
    volatility10 = grouped["ret_1d"].rolling(10, min_periods=10).std().reset_index(level=0, drop=True)

    df["close_vs_ma5"] = df["close"] / ma5 - 1
    df["close_vs_ma20"] = df["close"] / ma20 - 1
    df["ma5_vs_ma20"] = ma5 / ma20 - 1
    df["volume_ratio_5d"] = df["vol"] / vol5 - 1
    df["amount_ratio_20d"] = df["amount"] / amount20 - 1
    df["intraday_ret"] = df["close"] / df["open"] - 1
    df["range_pct"] = (df["high"] - df["low"]) / previous_close
    spread = df["high"] - df["low"]
    df["close_position"] = ((df["close"] - df["low"]) / spread).where(spread > 0, 0.5)
    df["volatility_10d"] = volatility10
    df["market_ret_1d"] = df.groupby("trade_date")["ret_1d"].transform("median")
    df["relative_strength_1d"] = df["ret_1d"] - df["market_ret_1d"]

    next_open = grouped["open"].shift(-1)
    next_close = grouped["close"].shift(-1)
    df["next_ret"] = next_close / next_open - 1
    df["target"] = np.where(df["next_ret"].notna(), (df["next_ret"] > 0).astype(float), np.nan)
    df["next_trade_date"] = grouped["trade_date"].shift(-1)

    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    return df


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -35, 35)
    return 1 / (1 + np.exp(-values))


def fit_model(
    rows: pd.DataFrame,
    *,
    l2: float = 2.0,
    half_life: float = 120.0,
    iterations: int = 300,
    learning_rate: float = 0.08,
) -> Model:
    """拟合带时间衰减和 L2 正则的逻辑回归。"""
    clean = rows.dropna(subset=[*FEATURES, "target"]).copy()
    if clean.empty or clean["target"].nunique() < 2:
        raise ValueError("训练数据不足或只有单一涨跌类别")

    matrix = clean.loc[:, FEATURES].to_numpy(dtype=float)
    means = np.nanmedian(matrix, axis=0)
    scales = np.nanstd(matrix, axis=0)
    scales = np.where(scales < EPSILON, 1.0, scales)
    x = np.clip((matrix - means) / scales, -8, 8)
    x = np.column_stack([np.ones(len(x)), x])
    y = clean["target"].to_numpy(dtype=float)

    dates = pd.to_datetime(clean["trade_date"], format="%Y%m%d")
    ages = (dates.max() - dates).dt.days.to_numpy(dtype=float)
    sample_weights = np.power(0.5, ages / half_life)
    sample_weights /= sample_weights.mean()

    baseline = float(np.average(y, weights=sample_weights))
    weights = np.zeros(x.shape[1], dtype=float)
    weights[0] = math.log((baseline + 1e-6) / (1 - baseline + 1e-6))

    penalty = np.r_[0.0, np.ones(x.shape[1] - 1)]
    for step in range(iterations):
        predictions = _sigmoid(x @ weights)
        gradient = x.T @ (sample_weights * (predictions - y)) / len(y)
        gradient += l2 * penalty * weights / len(y)
        rate = learning_rate / math.sqrt(1 + step / 50)
        weights -= rate * gradient

    return Model(
        weights=weights,
        means=means,
        scales=scales,
        feature_names=FEATURES,
        baseline_rate=baseline,
        training_rows=len(clean),
        training_start=str(clean["trade_date"].min()),
        training_end=str(clean["trade_date"].max()),
    )


def _format_reason(feature: str, contribution: float) -> str:
    direction = "提高" if contribution > 0 else "降低"
    return f"{FEATURE_LABELS[feature]}{direction}上涨概率"


def score_rows(model: Model, rows: pd.DataFrame, reason_count: int = 3) -> pd.DataFrame:
    """评分并生成每只股票最重要的正向/负向统计解释。"""
    result = rows.dropna(subset=list(FEATURES)).copy()
    matrix = result.loc[:, FEATURES].to_numpy(dtype=float)
    standardized = np.clip((matrix - model.means) / model.scales, -8, 8)
    contributions = standardized * model.weights[1:]
    result["prob_up"] = _sigmoid(model.weights[0] + contributions.sum(axis=1))

    reasons: list[str] = []
    for values in contributions:
        order = np.argsort(np.abs(values))[::-1][:reason_count]
        reasons.append("；".join(_format_reason(FEATURES[index], values[index]) for index in order))
    result["reasons"] = reasons
    return result


def train_and_score(
    dataset: pd.DataFrame,
    signal_date: str,
    *,
    train_days: int = DEFAULT_TRAIN_DAYS,
    min_training_rows: int = 1000,
) -> tuple[Model, pd.DataFrame]:
    """以 signal_date 收盘时可获得的数据训练并评分。"""
    dates = sorted(dataset.loc[dataset["trade_date"] <= signal_date, "trade_date"].unique())
    if signal_date not in dates:
        raise ValueError(f"数据库中没有交易日 {signal_date}")
    start_index = max(0, len(dates) - train_days - 1)
    train_start = dates[start_index]

    # signal_date 当日收盘时，前一日样本的 next_ret 已经揭晓，因此允许进入训练。
    training = dataset[
        (dataset["trade_date"] >= train_start)
        & (dataset["trade_date"] < signal_date)
        & dataset["target"].notna()
    ]
    available = training.dropna(subset=[*FEATURES, "target"])
    if len(available) < min_training_rows:
        raise ValueError(f"有效训练样本仅 {len(available):,} 条，至少需要 {min_training_rows:,} 条")

    model = fit_model(training)
    candidates = dataset[dataset["trade_date"] == signal_date]
    scored = score_rows(model, candidates)
    return model, scored


def _tradable(rows: pd.DataFrame, min_amount: float) -> pd.DataFrame:
    result = rows[rows["amount"].fillna(0) >= min_amount].copy()
    if "name" in result:
        result = result[~result["name"].fillna("").str.upper().str.contains("ST")]
    return result


def prediction_table(
    dataset: pd.DataFrame,
    b1_pool: pd.DataFrame,
    signal_date: str,
    *,
    top: int = 0,
    train_days: int = DEFAULT_TRAIN_DAYS,
    min_training_rows: int = 1000,
    min_amount: float = 20_000.0,
) -> tuple[Model, pd.DataFrame]:
    codes = _pool_codes(b1_pool, signal_date)
    if not codes:
        raise ValueError(
            f"{signal_date} 没有已持久化的 B1 股票池；请先运行 "
            f"`uv run python -m strategy.b1 {signal_date}`"
        )
    model, scored = train_and_score(
        dataset, signal_date, train_days=train_days, min_training_rows=min_training_rows
    )
    scored = scored[scored["ts_code"].isin(codes)].copy()
    scored = _tradable(scored, min_amount)
    scored["prediction_pool"] = B1_STRATEGY
    columns = [
        "trade_date", "next_trade_date", "ts_code", "name", "industry", "close",
        "amount", "prediction_pool", "prob_up", "reasons", "next_ret", "target",
    ]
    ranked = scored.sort_values("prob_up", ascending=False)
    if top > 0:
        ranked = ranked.head(top)
    return model, ranked[columns]


def walk_forward_backtest(
    dataset: pd.DataFrame,
    b1_pool: pd.DataFrame,
    start: str,
    end: str,
    *,
    top: int = 0,
    train_days: int = DEFAULT_TRAIN_DAYS,
    min_training_rows: int = 1000,
    min_amount: float = 20_000.0,
) -> pd.DataFrame:
    """逐日重新训练；每一天只使用当时已知的数据。"""
    dates = sorted(dataset.loc[
        (dataset["trade_date"] >= start) & (dataset["trade_date"] <= end), "trade_date"
    ].unique())
    outputs = []
    for signal_date in dates:
        try:
            _, picks = prediction_table(
                dataset,
                b1_pool,
                signal_date,
                top=top,
                train_days=train_days,
                min_training_rows=min_training_rows,
                min_amount=min_amount,
            )
        except ValueError as exc:
            print(f"跳过 {signal_date}: {exc}")
            continue
        known = picks[picks["next_ret"].notna()].copy()
        known["rank"] = np.arange(1, len(known) + 1)
        outputs.append(known)
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame()


def _print_model(model: Model) -> None:
    print(
        f"训练区间 {model.training_start} → {model.training_end}，"
        f"样本 {model.training_rows:,}，历史上涨率 {model.baseline_rate:.1%}"
    )


def _print_predictions(rows: pd.DataFrame, review: bool = False) -> None:
    if rows.empty:
        print("没有满足条件的候选股票")
        return
    shown = rows.copy()
    shown["上涨概率"] = shown["prob_up"].map(lambda value: f"{value:.1%}")
    shown["名称"] = shown["name"].fillna("")
    shown["代码"] = shown["ts_code"]
    columns = ["代码", "名称", "上涨概率", "reasons"]
    if review:
        shown["实际收益"] = shown["next_ret"].map(lambda value: "--" if pd.isna(value) else f"{value:+.2%}")
        shown["结果"] = shown["target"].map({1.0: "涨", 0.0: "跌"}).fillna("未知")
        columns += ["实际收益", "结果"]
    print(shown[columns].to_string(index=False))


def _save(rows: pd.DataFrame, path: Path, model: Model | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        payload: dict[str, object] = {"rows": rows.where(pd.notna(rows), None).to_dict("records")}
        if model:
            payload["model"] = {
                "training_start": model.training_start,
                "training_end": model.training_end,
                "training_rows": model.training_rows,
                "baseline_rate": model.baseline_rate,
            }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        rows.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"已写入 {path}")


def _report_backtest(rows: pd.DataFrame, top: int) -> None:
    if rows.empty:
        print("回测区间没有可评估的预测")
        return
    daily = rows.groupby("trade_date").agg(
        picks=("ts_code", "size"),
        win_rate=("target", "mean"),
        mean_return=("next_ret", "mean"),
    )
    baseline = rows["target"].mean()
    scope = f"每日 Top {top}" if top > 0 else "每日全部 B1 入池股票"
    print(f"滚动回测：{daily.index.min()} → {daily.index.max()}，{scope}")
    print(f"预测日数 {len(daily)}，股票日样本 {len(rows):,}")
    print(f"平均命中率 {baseline:.1%}，平均次日开收到收收益 {rows['next_ret'].mean():+.3%}")
    print(f"盈利交易日占比 {(daily['mean_return'] > 0).mean():.1%}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("predict", "review", "backtest"), default="predict")
    parser.add_argument("dates", nargs="*", help="predict/review: 信号日；backtest: 开始日 结束日")
    parser.add_argument("--top", type=int, default=0, help="B1 池内最多输出 N 只；0 表示全部（默认）")
    parser.add_argument(
        "--train-days", type=int, default=DEFAULT_TRAIN_DAYS,
        help=f"滚动训练交易日数，默认 {DEFAULT_TRAIN_DAYS}（约 3 年）",
    )
    parser.add_argument("--min-training-rows", type=int, default=1000)
    parser.add_argument("--min-amount", type=float, default=20_000.0, help="最低成交额（Tushare 千元）")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with connect() as conn:
        row = conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()
    latest = str(row[0]) if row and row[0] else ""
    if not latest:
        raise SystemExit("daily 表为空，请先运行数据更新")

    if args.command in {"predict", "review"}:
        signal_date = args.dates[0] if args.dates else latest
        first_signal_date = signal_date
        last_signal_date = signal_date
    else:
        if len(args.dates) != 2:
            raise SystemExit("backtest 需要开始日和结束日，例如：backtest 20260101 20260601")
        first_signal_date, last_signal_date = args.dates

    warmup_days = 40
    history_days = math.ceil(args.train_days * 1.7) + warmup_days
    load_start = (
        datetime.strptime(first_signal_date, "%Y%m%d") - timedelta(days=history_days)
    ).strftime("%Y%m%d")
    load_end = min(
        latest,
        (datetime.strptime(last_signal_date, "%Y%m%d") + timedelta(days=10)).strftime("%Y%m%d"),
    )
    bars = load_bars(start=load_start, end=load_end)
    dataset = build_dataset(bars)
    b1_pool = load_b1_pool(start=first_signal_date, end=last_signal_date)

    if args.command in {"predict", "review"}:
        model, rows = prediction_table(
            dataset,
            b1_pool,
            signal_date,
            top=args.top,
            train_days=args.train_days,
            min_training_rows=args.min_training_rows,
            min_amount=args.min_amount,
        )
        _print_model(model)
        print(
            f"信号日 {signal_date}，B1 股票池 {len(_pool_codes(b1_pool, signal_date))} 只，"
            "预测目标：下一交易日开盘 → 收盘"
        )
        _print_predictions(rows, review=args.command == "review")
        if args.command == "review" and rows["next_ret"].notna().any():
            known = rows.dropna(subset=["next_ret"])
            print(f"Top {len(known)} 命中率 {known['target'].mean():.1%}，平均收益 {known['next_ret'].mean():+.3%}")
        output = args.output or Path("data/predictions") / f"next_day_{signal_date}.csv"
        _save(rows, output, model)
        return 0

    rows = walk_forward_backtest(
        dataset,
        b1_pool,
        args.dates[0],
        args.dates[1],
        top=args.top,
        train_days=args.train_days,
        min_training_rows=args.min_training_rows,
        min_amount=args.min_amount,
    )
    _report_backtest(rows, args.top)
    output = args.output or Path("data/predictions") / f"backtest_{args.dates[0]}_{args.dates[1]}.csv"
    _save(rows, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
