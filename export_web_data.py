"""Export CSV signal files into static JSON for GitHub Pages.

Usage:
    uv run python export_web_data.py

The generated files live under web/data/ and can be served by GitHub Pages:
    web/data/manifest.json
    web/data/dates/<YYYYMMDD>.json
    web/data/search_index.json
    web/data/industry_trends.json
    web/data/strategies.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from statistics import median

import pandas as pd

from search_stock_csv import order_columns, read_csv, relative_path
from strategy.dashboard import build_strategy_dashboard


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_OUTPUT_DIR = ROOT / "web" / "data"
DEFAULT_DB_PATH = ROOT / "data" / "stock.db"
DATE_RE = re.compile(r"(?<!\d)(20\d{6})(?!\d)")
CODE_COLUMNS = (
    "ts_code",
    "code",
    "symbol",
    "stock_code",
    "seccode",
    "security_code",
    "ticker",
    "股票代码",
    "证券代码",
)
TS_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.IGNORECASE)
SYMBOL_RE = re.compile(r"^\d{6}$")
PRICE_TICK = Decimal("0.01")
MAIN_BOARD_ST_LIMIT_CHANGE_DATE = "20260706"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export web/static JSON data.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    parser.add_argument(
        "--db-path",
        default=Path(os.environ.get("STOCK_DB_PATH", DEFAULT_DB_PATH)),
        type=Path,
        help="SQLite database used to export static K-line detail data.",
    )
    parser.add_argument("--kline-limit", default=120, type=int)
    parser.add_argument(
        "--strategies-only",
        action="store_true",
        help="Refresh strategies.json and strategy-linked K-lines without rebuilding all web data.",
    )
    return parser.parse_args()


def csv_date(path: Path) -> str | None:
    match = DATE_RE.search(path.name)
    return match.group(1) if match else None


def csv_files(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []
    return sorted(data_dir.rglob("*.csv"))


def frame_payload(df: pd.DataFrame) -> dict[str, object]:
    if df.empty:
        return {"columns": [], "rows": []}

    safe_df = df.fillna("")
    return {
        "columns": list(safe_df.columns),
        "rows": safe_df.to_dict(orient="records"),
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


PREDICTION_COLUMNS = ("prediction_rank", "prob_up", "reasons", "next_trade_date")


def is_prediction_file(path: Path, df: pd.DataFrame) -> bool:
    """Return whether a CSV is a next-day prediction output."""
    return "prob_up" in df.columns and (
        path.name.startswith("next_day_") or "predictions" in path.parts
    )


def _code_column(df: pd.DataFrame) -> str | None:
    normalized_columns = {column.lower().replace("_", ""): column for column in df.columns}
    for candidate in CODE_COLUMNS:
        column = candidate if candidate in df.columns else normalized_columns.get(candidate.lower().replace("_", ""))
        if column:
            return column
    return None


def normalize_stock_code(value: object) -> str:
    """Return a canonical stock key so symbols and ts_codes join reliably."""
    if pd.isna(value):
        return ""
    code = str(value).strip().upper()
    if TS_CODE_RE.match(code):
        return code
    if SYMBOL_RE.match(code):
        return infer_ts_code(code) or code
    return code


def combine_files(paths: list[Path]) -> pd.DataFrame:
    """Combine daily signals and annotate them with next-day predictions.

    Prediction fields are merged onto matching signal rows. Prediction-only
    picks are retained as standalone rows so a refreshed signal CSV cannot hide
    predictions that were already generated for that trading date.
    """
    signal_frames: list[pd.DataFrame] = []
    prediction_frames: list[pd.DataFrame] = []
    for path in paths:
        df = read_csv(path)
        if is_prediction_file(path, df):
            prediction = df.copy()
            prediction["prediction_source_file"] = relative_path(path)
            prediction["prediction_rank"] = range(1, len(prediction) + 1)
            prediction_frames.append(prediction)
        else:
            df.insert(0, "source_file", relative_path(path))
            signal_frames.append(df)

    signals = (
        pd.concat(signal_frames, ignore_index=True, sort=False)
        if signal_frames
        else pd.DataFrame()
    )
    predictions = (
        pd.concat(prediction_frames, ignore_index=True, sort=False)
        if prediction_frames
        else pd.DataFrame()
    )
    if predictions.empty:
        return order_columns(signals)
    if signals.empty:
        predictions.insert(0, "source_file", predictions.pop("prediction_source_file"))
        return order_columns(predictions)

    signal_code = _code_column(signals)
    prediction_code = _code_column(predictions)
    if not signal_code or not prediction_code:
        predictions.insert(0, "source_file", predictions.pop("prediction_source_file"))
        return order_columns(pd.concat([signals, predictions], ignore_index=True, sort=False))

    join_key = "__stock_code_key"
    signals[join_key] = signals[signal_code].map(normalize_stock_code)
    predictions[join_key] = predictions[prediction_code].map(normalize_stock_code)
    predictions = predictions.drop_duplicates(join_key, keep="first").copy()
    annotation_columns = [
        join_key,
        "prediction_source_file",
        *[column for column in PREDICTION_COLUMNS if column in predictions.columns],
    ]
    annotated = signals.merge(
        predictions[annotation_columns],
        how="left",
        on=join_key,
        suffixes=("", "_prediction"),
    )

    matched_codes = set(signals[join_key])
    unmatched = predictions[~predictions[join_key].isin(matched_codes)].copy()
    if not unmatched.empty:
        unmatched["source_file"] = unmatched["prediction_source_file"]
        annotated = pd.concat([annotated, unmatched], ignore_index=True, sort=False)

    annotated = annotated.drop(columns=[join_key])
    if "prediction_rank" in annotated.columns:
        annotated = annotated.sort_values(
            ["prediction_rank"], ascending=True, na_position="last", kind="stable"
        )
    return order_columns(annotated.reset_index(drop=True))


def infer_ts_code(symbol: str) -> str | None:
    if not SYMBOL_RE.match(symbol):
        return None
    if symbol.startswith(("60", "68", "90")):
        return f"{symbol}.SH"
    if symbol.startswith(("00", "30", "20")):
        return f"{symbol}.SZ"
    if symbol.startswith(("43", "83", "87", "88", "92")):
        return f"{symbol}.BJ"
    return None


def collect_code_values(df: pd.DataFrame) -> set[str]:
    values: set[str] = set()
    if df.empty:
        return values

    normalized_columns = {column.lower().replace("_", ""): column for column in df.columns}
    for candidate in CODE_COLUMNS:
        column = candidate if candidate in df.columns else normalized_columns.get(candidate.lower().replace("_", ""))
        if not column:
            continue
        for value in df[column].dropna().astype(str):
            code = value.strip().upper()
            if code:
                values.add(code)
    return values


def resolve_export_codes(code_values: set[str], db_path: Path) -> set[str]:
    resolved = {code for code in code_values if TS_CODE_RE.match(code)}
    symbols = {code for code in code_values if SYMBOL_RE.match(code)}
    if not symbols:
        return resolved

    if db_path.exists():
        with sqlite3.connect(db_path) as conn:
            symbol_list = sorted(symbols)
            for start in range(0, len(symbol_list), 500):
                chunk = symbol_list[start : start + 500]
                rows = conn.execute(
                    f"SELECT symbol, ts_code FROM stock_basic WHERE symbol IN ({','.join('?' for _ in chunk)})",
                    chunk,
                ).fetchall()
                for symbol, ts_code in rows:
                    if ts_code:
                        resolved.add(str(ts_code).upper())
                        symbols.discard(str(symbol))

    for symbol in symbols:
        inferred = infer_ts_code(symbol)
        if inferred:
            resolved.add(inferred)
    return resolved


def resolve_code_map(code_values: set[str], db_path: Path) -> dict[str, str]:
    """Return a best-effort mapping from raw CSV code values to canonical ts_code."""
    mapping: dict[str, str] = {}
    symbols: set[str] = set()

    for raw in code_values:
        code = str(raw).strip().upper()
        if not code:
            continue
        if TS_CODE_RE.match(code):
            mapping[code] = code
        elif SYMBOL_RE.match(code):
            symbols.add(code)

    if symbols and db_path.exists():
        with sqlite3.connect(db_path) as conn:
            symbol_list = sorted(symbols)
            for start in range(0, len(symbol_list), 500):
                chunk = symbol_list[start : start + 500]
                rows = conn.execute(
                    f"SELECT symbol, ts_code FROM stock_basic WHERE symbol IN ({','.join('?' for _ in chunk)})",
                    chunk,
                ).fetchall()
                for symbol, ts_code in rows:
                    if ts_code:
                        mapping[str(symbol).strip().upper()] = str(ts_code).strip().upper()

    for symbol in symbols:
        if symbol not in mapping:
            inferred = infer_ts_code(symbol)
            if inferred:
                mapping[symbol] = inferred

    return mapping




def mainline_summary(level: str, main_line: str, score: float, consecutive: int, gap: float) -> str:
    if level == "strong":
        return f"✅ 主线确认！{main_line}连续{consecutive}天评分≥0.70，领先{round(gap,2)}，当前评分{round(score,3)}"
    if level == "emerging":
        return f"🟡 主线萌芽：{main_line}评分{round(score,3)}，领先{round(gap,2)}，连续{consecutive}天不足3天"
    if level == "candidate":
        return f"🔵 潜在主线：{main_line}评分{round(score,3)}，领先{round(gap,2)}，需观察持续性"
    return "⚪ 暂无明显主线，市场处于轮动状态"



def build_mainline_stock_rows(conn: sqlite3.Connection, date: str, industry: str) -> list[dict[str, object]]:
    """Return the full stock pool for a main-line industry on one trading date."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT d.ts_code, s.name, s.industry, d.close, d.pct_chg, d.amount
           FROM daily d
           JOIN stock_basic s ON s.ts_code = d.ts_code
           WHERE d.trade_date = ?
             AND s.industry = ?
             AND COALESCE(s.delist_date, '') = ''
           ORDER BY d.amount DESC, d.ts_code""",
        (date, industry),
    ).fetchall()
    return [
        {
            "trade_date": date,
            "ts_code": row["ts_code"],
            "name": row["name"],
            "industry": row["industry"],
            "close": round(float(row["close"]), 2) if row["close"] is not None else None,
            "pct_chg": round(float(row["pct_chg"]), 2) if row["pct_chg"] is not None else None,
            "amount": round(float(row["amount"]), 2) if row["amount"] is not None else None,
        }
        for row in rows
    ]

def build_mainline_payload(conn: sqlite3.Connection, date: str) -> dict[str, object] | None:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT trade_date, industry, score, rank,
                  return_5d, return_10d, return_20d,
                  turnover, breadth, new_high_ratio,
                  concentration, relative_strength
           FROM sector_ranking_history
           WHERE trade_date = ?
           ORDER BY rank
           LIMIT 10""",
        (date,),
    ).fetchall()
    if not rows:
        return None

    sectors = []
    for row in rows:
        sectors.append(
            {
                "rank": int(row["rank"]),
                "industry": row["industry"],
                "score": round(float(row["score"]), 4) if row["score"] is not None else None,
                "return_5d": round(float(row["return_5d"]), 2) if row["return_5d"] is not None else None,
                "turnover_billion": round(float(row["turnover"]), 1) if row["turnover"] is not None else None,
                "breadth_pct": round(float(row["breadth"]), 1) if row["breadth"] is not None else None,
                "new_high_pct": round(float(row["new_high_ratio"]), 1) if row["new_high_ratio"] is not None else None,
                "relative_strength": round(float(row["relative_strength"]), 2) if row["relative_strength"] is not None else None,
                "stocks": build_mainline_stock_rows(conn, date, row["industry"]),
            }
        )

    signal = None
    if sectors:
        top_score = sectors[0]["score"] or 0
        second_score = sectors[1]["score"] if len(sectors) > 1 and sectors[1]["score"] is not None else 0
        gap = round(top_score - second_score, 4)
        consecutive = 1
        prev_dates = conn.execute(
            """SELECT DISTINCT trade_date FROM sector_ranking_history
               WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 10""",
            (date,),
        ).fetchall()
        for prev_row in prev_dates:
            previous_top = conn.execute(
                "SELECT industry FROM sector_ranking_history WHERE trade_date = ? ORDER BY rank LIMIT 1",
                (prev_row["trade_date"],),
            ).fetchone()
            if previous_top and previous_top["industry"] == sectors[0]["industry"]:
                consecutive += 1
            else:
                break

        if top_score >= 0.70 and gap >= 0.10:
            level = "strong" if consecutive >= 3 else "emerging"
        elif top_score >= 0.70:
            level = "candidate"
        else:
            level = "none"
        signal = {
            "main_line": sectors[0]["industry"],
            "main_score": top_score,
            "gap": gap,
            "consecutive_days": consecutive,
            "confirmation_level": level,
            "strength": 2 if level == "strong" else 1 if level in ("emerging", "candidate") else 0,
            "summary": mainline_summary(level, sectors[0]["industry"], top_score, consecutive, gap),
        }

    return {
        "date": date,
        "main_line": sectors[0]["industry"] if sectors else None,
        "main_score": sectors[0]["score"] if sectors else None,
        "clarity": "clear" if signal and signal["confirmation_level"] in ("strong", "emerging") else "fuzzy" if signal else "rotating",
        "signal": signal,
        "sectors": sectors,
    }


def export_mainline_data(db_path: Path, output_dir: Path, dates: list[str]) -> dict[str, str]:
    if not db_path.exists() or not dates:
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sector_ranking_history'"
            ).fetchone()
            if not exists:
                return {}
            index = {}
            for date in dates:
                payload = build_mainline_payload(conn, date)
                if not payload:
                    continue
                path = output_dir / "mainline" / f"{date}.json"
                write_json(path, payload)
                index[date] = f"data/mainline/{date}.json"
            if dates and dates[-1] in index:
                latest_payload = build_mainline_payload(conn, dates[-1])
                if latest_payload:
                    write_json(output_dir / "main_line.json", latest_payload)
            return index
    except sqlite3.Error:
        return {}


def _price_limit_rate(ts_code: str, stock_name: str | None, trade_date: str) -> Decimal:
    """Return the daily upper-price-limit rate for an A-share stock."""
    normalized_code = str(ts_code or "").upper()
    symbol = normalized_code.split(".", 1)[0]
    if normalized_code.endswith(".BJ"):
        return Decimal("0.30")
    if symbol.startswith(("300", "301", "688", "689")):
        return Decimal("0.20")

    normalized_name = str(stock_name or "").upper().lstrip("*")
    if normalized_name.startswith("ST") and trade_date < MAIN_BOARD_ST_LIMIT_CHANGE_DATE:
        return Decimal("0.05")
    return Decimal("0.10")


def is_stock_limit_up(
    ts_code: str,
    stock_name: str | None,
    trade_date: str,
    pre_close: object,
    close: object,
) -> bool:
    """Return whether the stock closed at its rounded daily upper limit."""
    if pre_close is None or close is None:
        return False
    try:
        previous = Decimal(str(pre_close))
        current = Decimal(str(close)).quantize(PRICE_TICK, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return False
    if previous <= 0:
        return False

    rate = _price_limit_rate(ts_code, stock_name, trade_date)
    upper_limit = (previous * (Decimal("1") + rate)).quantize(
        PRICE_TICK,
        rounding=ROUND_HALF_UP,
    )
    return current == upper_limit


def _stock_limit_price(
    ts_code: str,
    stock_name: str | None,
    trade_date: str,
    pre_close: object,
    direction: int,
) -> Decimal | None:
    if pre_close is None:
        return None
    try:
        previous = Decimal(str(pre_close))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if previous <= 0:
        return None
    rate = _price_limit_rate(ts_code, stock_name, trade_date)
    multiplier = Decimal("1") + rate if direction > 0 else Decimal("1") - rate
    return (previous * multiplier).quantize(PRICE_TICK, rounding=ROUND_HALF_UP)


def is_stock_limit_down(
    ts_code: str,
    stock_name: str | None,
    trade_date: str,
    pre_close: object,
    close: object,
) -> bool:
    """Return whether the stock closed at its rounded daily lower limit."""
    limit_price = _stock_limit_price(ts_code, stock_name, trade_date, pre_close, -1)
    if limit_price is None or close is None:
        return False
    try:
        current = Decimal(str(close)).quantize(PRICE_TICK, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return False
    return current == limit_price


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _emotion_phase(score: float, change: float | None) -> tuple[str, str]:
    delta = change or 0.0
    if score >= 78:
        return "climax", "高潮"
    if score >= 63:
        return "warming", "升温"
    if score < 35:
        return "ice", "冰点"
    if delta <= -5:
        return "retreat", "退潮"
    if delta >= 4:
        return "repair", "修复"
    return "divergence", "混沌"


def _emotion_summary(point: dict[str, object]) -> str:
    phase = point["phase"]
    up_ratio = point["breadth"]["up_ratio_pct"]
    limit_up = point["limits"]["limit_up"]
    limit_down = point["limits"]["limit_down"]
    feedback = point["feedback"]["previous_limit_up_avg_pct"]
    if phase == "高潮":
        return f"赚钱效应处于高潮，{up_ratio:.1f}% 个股上涨、{limit_up} 家涨停；强势延续，但追高风险同步抬升。"
    if phase == "升温":
        return f"情绪持续升温，涨停 {limit_up} 家、跌停 {limit_down} 家，市场广度与趋势结构共同改善。"
    if phase == "修复":
        return f"市场从弱势区修复，上涨家数占比 {up_ratio:.1f}%；先观察修复能否连续两到三日。"
    if phase == "退潮":
        suffix = f"，昨日涨停今日平均 {feedback:+.2f}%" if feedback is not None else ""
        return f"情绪正在退潮，涨停与广度的承接转弱{suffix}；高位股亏钱效应需要优先回避。"
    if phase == "冰点":
        return f"情绪接近冰点，仅 {up_ratio:.1f}% 个股上涨、跌停 {limit_down} 家；反弹信号尚未确认。"
    return f"情绪处于混沌轮动，{up_ratio:.1f}% 个股上涨；局部热点不等于全市场主升。"


def _emotion_risk_flags(point: dict[str, object]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    score_change = point.get("score_change")
    limits = point["limits"]
    feedback = point["feedback"]
    activity = point["activity"]
    breadth = point["breadth"]
    if score_change is not None and score_change <= -8:
        flags.append({"level": "danger", "text": f"情绪分单日下降 {abs(score_change):.1f} 分"})
    if limits["open_board_rate_pct"] >= 30:
        flags.append({"level": "warning", "text": f"炸板率 {limits['open_board_rate_pct']:.1f}%，分歧偏大"})
    if feedback["previous_limit_up_avg_pct"] is not None and feedback["previous_limit_up_avg_pct"] < 0:
        flags.append({"level": "danger", "text": "昨日涨停股平均转亏，接力反馈偏弱"})
    if limits["limit_up"] >= 30 and breadth["up_ratio_pct"] < 50:
        flags.append({"level": "warning", "text": "涨停活跃但上涨家数不足，属于局部抱团"})
    if activity["amount_vs_5d_pct"] is not None and activity["amount_vs_5d_pct"] < -12:
        flags.append({"level": "warning", "text": "成交额低于近5日均值，增量资金不足"})
    if not flags:
        flags.append({"level": "normal", "text": "暂未出现显著退潮信号"})
    return flags[:3]


def _sector_pulses(day_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in day_rows:
        industry = str(row.get("industry") or "未分类").strip()
        groups[industry].append(row)

    pulses = []
    for industry, rows in groups.items():
        valid = [row for row in rows if row.get("pct_chg") is not None]
        if len(valid) < 5:
            continue
        avg_pct = sum(float(row["pct_chg"]) for row in valid) / len(valid)
        up_count = sum(float(row["pct_chg"]) > 0 for row in valid)
        up_ratio = up_count / len(valid) * 100
        limit_up_count = sum(bool(row.get("is_limit_up")) for row in valid)
        amount_billion = sum(float(row.get("amount") or 0) for row in valid) / 100000
        limit_density = limit_up_count / len(valid) * 100
        pulse_score = _clamp(35 + avg_pct * 10 + (up_ratio - 50) * 0.45 + limit_density * 1.5)
        if limit_up_count >= 3 and up_ratio >= 70:
            quality = "一致爆发"
        elif avg_pct >= 2 and up_ratio >= 60:
            quality = "扩散走强"
        elif limit_up_count >= 2 and up_ratio < 55:
            quality = "龙头独舞"
        else:
            quality = "局部活跃"
        pulses.append(
            {
                "industry": industry,
                "score": round(pulse_score, 1),
                "avg_pct": round(avg_pct, 2),
                "up_ratio_pct": round(up_ratio, 1),
                "limit_up_count": limit_up_count,
                "amount_billion": round(amount_billion, 1),
                "stock_count": len(valid),
                "quality": quality,
            }
        )
    pulses.sort(key=lambda row: (-row["score"], -row["limit_up_count"], -row["amount_billion"]))
    return pulses[:10]


def _build_emotion_payloads(
    conn: sqlite3.Connection,
    requested_dates: list[str],
    history_limit: int = 30,
) -> dict[str, dict[str, object]]:
    """Build explainable sentiment snapshots in one market-data pass."""
    if not requested_dates:
        return {}
    requested_dates = sorted(set(requested_dates))
    date = requested_dates[-1]
    conn.row_factory = sqlite3.Row
    available = [
        row["trade_date"]
        for row in conn.execute(
            "SELECT DISTINCT trade_date FROM daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT ?",
            (date, len(requested_dates) + history_limit + 65),
        ).fetchall()
    ]
    if not available or date not in available:
        return {}
    trade_dates = sorted(available)
    placeholders = ",".join("?" for _ in trade_dates)
    raw_rows = conn.execute(
        f"""SELECT d.trade_date, d.ts_code, d.high, d.close, d.pre_close,
                   d.pct_chg, d.amount, s.name, s.industry
            FROM daily d
            LEFT JOIN stock_basic s ON s.ts_code = d.ts_code
            WHERE d.trade_date IN ({placeholders})
            ORDER BY d.trade_date, d.ts_code""",
        trade_dates,
    ).fetchall()
    if not raw_rows:
        return {}

    rows_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for raw in raw_rows:
        rows_by_date[raw["trade_date"]].append(dict(raw))

    close_windows: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))
    limit_streaks: dict[str, int] = defaultdict(int)
    previous_limit_codes: set[str] = set()
    previous_amounts: deque[float] = deque(maxlen=5)
    points = []
    detail_by_date: dict[str, dict[str, object]] = {}

    for trade_date in trade_dates:
        day_rows = rows_by_date.get(trade_date, [])
        pct_values = [float(row["pct_chg"]) for row in day_rows if row.get("pct_chg") is not None]
        if not pct_values:
            continue
        current_codes = {str(row["ts_code"]) for row in day_rows}
        for stale_code in set(limit_streaks) - current_codes:
            limit_streaks[stale_code] = 0
        up_count = sum(value > 0 for value in pct_values)
        down_count = sum(value < 0 for value in pct_values)
        flat_count = len(pct_values) - up_count - down_count
        up_ratio = up_count / len(pct_values) * 100
        median_pct = float(median(pct_values))
        amount_billion = sum(float(row.get("amount") or 0) for row in day_rows) / 100000
        amount_vs_5d = (
            (amount_billion / (sum(previous_amounts) / len(previous_amounts)) - 1) * 100
            if previous_amounts and sum(previous_amounts) > 0
            else None
        )

        limit_up_codes: set[str] = set()
        limit_up_count = 0
        limit_down_count = 0
        touched_limit_count = 0
        above_ma20_count = 0
        ma20_eligible = 0
        new_high_count = 0
        new_low_count = 0
        distribution = {"rise_10": 0, "rise_5": 0, "rise": 0, "flat": 0, "fall": 0, "fall_5": 0, "fall_10": 0}

        for row in day_rows:
            ts_code = str(row["ts_code"])
            pct_chg = float(row["pct_chg"]) if row.get("pct_chg") is not None else 0.0
            is_limit_up = is_stock_limit_up(ts_code, row.get("name"), trade_date, row.get("pre_close"), row.get("close"))
            is_limit_down = is_stock_limit_down(ts_code, row.get("name"), trade_date, row.get("pre_close"), row.get("close"))
            row["is_limit_up"] = is_limit_up
            row["is_limit_down"] = is_limit_down
            if is_limit_up:
                limit_up_count += 1
                limit_up_codes.add(ts_code)
                limit_streaks[ts_code] += 1
            else:
                limit_streaks[ts_code] = 0
            if is_limit_down:
                limit_down_count += 1

            upper_price = _stock_limit_price(ts_code, row.get("name"), trade_date, row.get("pre_close"), 1)
            if upper_price is not None and row.get("high") is not None:
                high = Decimal(str(row["high"])).quantize(PRICE_TICK, rounding=ROUND_HALF_UP)
                if high >= upper_price:
                    touched_limit_count += 1

            history = close_windows[ts_code]
            close = float(row["close"]) if row.get("close") is not None else None
            if close is not None and len(history) >= 20:
                ma20_eligible += 1
                if close > sum(history) / len(history):
                    above_ma20_count += 1
                if close > max(history):
                    new_high_count += 1
                if close < min(history):
                    new_low_count += 1
            if close is not None:
                history.append(close)

            if pct_chg >= 9.8:
                distribution["rise_10"] += 1
            elif pct_chg >= 5:
                distribution["rise_5"] += 1
            elif pct_chg > 0:
                distribution["rise"] += 1
            elif pct_chg == 0:
                distribution["flat"] += 1
            elif pct_chg > -5:
                distribution["fall"] += 1
            elif pct_chg > -9.8:
                distribution["fall_5"] += 1
            else:
                distribution["fall_10"] += 1

        feedback_values = [
            float(row["pct_chg"])
            for row in day_rows
            if str(row["ts_code"]) in previous_limit_codes and row.get("pct_chg") is not None
        ]
        feedback_avg = sum(feedback_values) / len(feedback_values) if feedback_values else None
        feedback_positive = (
            sum(value > 0 for value in feedback_values) / len(feedback_values) * 100
            if feedback_values
            else None
        )
        open_board_count = max(0, touched_limit_count - limit_up_count)
        open_board_rate = open_board_count / touched_limit_count * 100 if touched_limit_count else 0.0
        trend_ratio = above_ma20_count / ma20_eligible * 100 if ma20_eligible else 50.0

        components = {
            "breadth": round(_clamp(up_ratio), 1),
            "limit_structure": round(_clamp(50 + (limit_up_count - limit_down_count) * 1.5 - open_board_rate * 0.25), 1),
            "profit_effect": round(_clamp(50 if feedback_avg is None else 50 + feedback_avg * 6), 1),
            "trend": round(_clamp(trend_ratio), 1),
            "activity": round(_clamp(50 if amount_vs_5d is None else 50 + amount_vs_5d), 1),
        }
        score = round(
            components["breadth"] * 0.25
            + components["limit_structure"] * 0.20
            + components["profit_effect"] * 0.20
            + components["trend"] * 0.20
            + components["activity"] * 0.15,
            1,
        )
        previous_score = points[-1]["score"] if points else None
        score_change = round(score - previous_score, 1) if previous_score is not None else None
        phase_code, phase = _emotion_phase(score, score_change)
        max_streak = max((limit_streaks[code] for code in limit_up_codes), default=0)

        point = {
            "date": trade_date,
            "score": score,
            "score_change": score_change,
            "phase_code": phase_code,
            "phase": phase,
            "breadth": {
                "up": up_count,
                "down": down_count,
                "flat": flat_count,
                "total": len(pct_values),
                "up_ratio_pct": round(up_ratio, 1),
                "median_pct": round(median_pct, 2),
            },
            "limits": {
                "limit_up": limit_up_count,
                "limit_down": limit_down_count,
                "touched_limit": touched_limit_count,
                "open_board": open_board_count,
                "open_board_rate_pct": round(open_board_rate, 1),
                "max_streak": max_streak,
            },
            "feedback": {
                "sample_count": len(feedback_values),
                "previous_limit_up_avg_pct": round(feedback_avg, 2) if feedback_avg is not None else None,
                "positive_ratio_pct": round(feedback_positive, 1) if feedback_positive is not None else None,
            },
            "trend": {
                "above_ma20_ratio_pct": round(trend_ratio, 1),
                "new_high_20d": new_high_count,
                "new_low_20d": new_low_count,
            },
            "activity": {
                "amount_billion": round(amount_billion, 1),
                "amount_vs_5d_pct": round(amount_vs_5d, 1) if amount_vs_5d is not None else None,
            },
            "components": components,
        }
        points.append(point)

        leaders = sorted(
            (
                {
                    "ts_code": str(row["ts_code"]),
                    "name": row.get("name") or str(row["ts_code"]),
                    "industry": row.get("industry") or "未分类",
                    "pct_chg": round(float(row.get("pct_chg") or 0), 2),
                    "amount_billion": round(float(row.get("amount") or 0) / 100000, 2),
                    "limit_streak": limit_streaks[str(row["ts_code"])],
                    "status": (
                        f"{limit_streaks[str(row['ts_code'])]}连板"
                        if limit_streaks[str(row["ts_code"])] >= 2
                        else "首板"
                    ),
                }
                for row in day_rows
                if row.get("is_limit_up")
            ),
            key=lambda row: (-row["limit_streak"], -row["amount_billion"], row["ts_code"]),
        )[:12]
        detail_by_date[trade_date] = {
            "distribution": distribution,
            "leaders": leaders,
            "sector_pulses": _sector_pulses(day_rows),
        }
        previous_limit_codes = limit_up_codes & current_codes
        previous_amounts.append(amount_billion)

    point_indexes = {point["date"]: index for index, point in enumerate(points)}
    payloads = {}
    for requested_date in requested_dates:
        point_index = point_indexes.get(requested_date)
        if point_index is None:
            continue
        target = points[point_index]
        detail = detail_by_date[requested_date]
        target["summary"] = _emotion_summary(target)
        target["risk_flags"] = _emotion_risk_flags(target)
        target["distribution"] = detail["distribution"]
        target["leaders"] = detail["leaders"]
        target["sector_pulses"] = detail["sector_pulses"]
        target["methodology"] = {
            "formula": "市场广度25% + 涨跌停结构20% + 昨涨停反馈20% + 20日趋势20% + 成交活跃度15%",
            "note": "分数用于描述当日交易情绪，不预测指数涨跌；阶段还结合分数单日变化判定。",
        }
        history_start = max(0, point_index - history_limit + 1)
        target["history"] = [
            {
                "date": point["date"],
                "score": point["score"],
                "score_change": point["score_change"],
                "phase": point["phase"],
                "phase_code": point["phase_code"],
                "up_ratio_pct": point["breadth"]["up_ratio_pct"],
                "limit_up": point["limits"]["limit_up"],
                "limit_down": point["limits"]["limit_down"],
            }
            for point in points[history_start : point_index + 1]
        ]
        payloads[requested_date] = target
    return payloads


def build_emotion_payload(
    conn: sqlite3.Connection,
    date: str,
    history_limit: int = 30,
) -> dict[str, object] | None:
    """Build one explainable whole-market sentiment snapshot."""
    return _build_emotion_payloads(conn, [date], history_limit).get(date)


def export_emotion_data(db_path: Path, output_dir: Path, dates: list[str]) -> dict[str, str]:
    if not db_path.exists() or not dates:
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            index = {}
            payloads = _build_emotion_payloads(conn, dates)
            for date, payload in payloads.items():
                path = output_dir / "emotion" / f"{date}.json"
                write_json(path, payload)
                index[date] = f"data/emotion/{date}.json"
            if index:
                latest_date = max(index)
                latest_payload = payloads.get(latest_date)
                if latest_payload:
                    write_json(output_dir / "emotion.json", latest_payload)
            return index
    except sqlite3.Error:
        return {}


def collect_emotion_codes(db_path: Path, dates: list[str]) -> set[str]:
    """Return recent liquid limit-up stocks used by the emotion leader table."""
    if not db_path.exists() or not dates:
        return set()
    codes: set[str] = set()
    try:
        with sqlite3.connect(db_path) as conn:
            payloads = _build_emotion_payloads(conn, dates[-30:])
            for payload in payloads.values():
                codes.update(
                    str(stock["ts_code"]).upper()
                    for stock in payload.get("leaders", [])
                    if stock.get("ts_code")
                )
    except sqlite3.Error:
        return set()
    return codes


def _build_concept_stock_data(
    conn: sqlite3.Connection,
    date: str,
    concept_code: str,
) -> tuple[list[dict[str, object]], int | None]:
    try:
        rows = conn.execute(
            """SELECT m.ts_code,
                      COALESCE(s.name, m.stock_name) AS name,
                      s.industry, d.pre_close, d.close, d.pct_chg, d.amount
               FROM concept_member_history m
               LEFT JOIN stock_basic s ON s.ts_code = m.ts_code
               LEFT JOIN daily d
                 ON d.ts_code = m.ts_code
                AND d.trade_date = m.trade_date
               WHERE m.trade_date = ? AND m.concept_code = ?
               ORDER BY m.member_rank, m.ts_code""",
            (date, concept_code),
        ).fetchall()
    except sqlite3.OperationalError:
        return [], None

    stock_rows = []
    limit_up_count = 0
    stocks_with_prices = 0
    for row in rows:
        stock_rows.append(
            {
                "trade_date": date,
                "ts_code": row["ts_code"],
                "name": row["name"],
                "industry": row["industry"],
                "close": (
                    round(float(row["close"]), 2) if row["close"] is not None else None
                ),
                "pct_chg": (
                    round(float(row["pct_chg"]), 2)
                    if row["pct_chg"] is not None
                    else None
                ),
                "amount": (
                    round(float(row["amount"]), 2)
                    if row["amount"] is not None
                    else None
                ),
            }
        )
        if row["pre_close"] is not None and row["close"] is not None:
            stocks_with_prices += 1
        if is_stock_limit_up(
            row["ts_code"],
            row["name"],
            date,
            row["pre_close"],
            row["close"],
        ):
            limit_up_count += 1
    return stock_rows, limit_up_count if stocks_with_prices else None


def build_concept_stock_rows(
    conn: sqlite3.Connection,
    date: str,
    concept_code: str,
) -> list[dict[str, object]]:
    return _build_concept_stock_data(conn, date, concept_code)[0]


def build_concept_payload(conn: sqlite3.Connection, date: str) -> dict[str, object] | None:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT trade_date, concept_code, concept_name, index_code, rank,
                  pct_chg, net_inflow_billion, breadth_pct, source
           FROM concept_ranking_history
           WHERE trade_date = ?
           ORDER BY rank
           LIMIT 10""",
        (date,),
    ).fetchall()
    if not rows:
        return None

    concepts = []
    for row in rows:
        stocks, limit_up_count = _build_concept_stock_data(conn, date, row["concept_code"])
        concepts.append(
            {
                "rank": int(row["rank"]),
                "concept_code": row["concept_code"],
                "concept_name": row["concept_name"],
                "index_code": row["index_code"],
                "pct_chg": round(float(row["pct_chg"]), 2) if row["pct_chg"] is not None else None,
                "net_inflow_billion": (
                    round(float(row["net_inflow_billion"]), 2)
                    if row["net_inflow_billion"] is not None
                    else None
                ),
                "breadth_pct": (
                    round(float(row["breadth_pct"]), 1)
                    if row["breadth_pct"] is not None
                    else None
                ),
                "limit_up_count": limit_up_count,
                "stocks": stocks,
            }
        )

    return {
        "date": date,
        "source": rows[0]["source"],
        "ranking_basis": "daily_pct_chg",
        "concepts": concepts,
    }


def export_concept_data(db_path: Path, output_dir: Path, dates: list[str]) -> dict[str, str]:
    if not db_path.exists() or not dates:
        return {}
    try:
        with sqlite3.connect(db_path) as conn:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='concept_ranking_history'"
            ).fetchone()
            if not exists:
                return {}

            index = {}
            for date in dates:
                payload = build_concept_payload(conn, date)
                if not payload:
                    continue
                path = output_dir / "concepts" / f"{date}.json"
                write_json(path, payload)
                index[date] = f"data/concepts/{date}.json"

            if index:
                latest_date = max(index)
                latest_payload = build_concept_payload(conn, latest_date)
                if latest_payload:
                    write_json(output_dir / "concept_ranking.json", latest_payload)
            return index
    except sqlite3.Error:
        return {}


def collect_concept_codes(db_path: Path, dates: list[str]) -> set[str]:
    """Return stocks belonging to exported top-ten concept boards."""
    if not db_path.exists() or not dates:
        return set()
    try:
        with sqlite3.connect(db_path) as conn:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='concept_member_history'"
            ).fetchone()
            if not exists:
                return set()

            ts_codes = set()
            for start in range(0, len(dates), 500):
                chunk = dates[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""SELECT DISTINCT m.ts_code
                        FROM concept_member_history m
                        JOIN concept_ranking_history r
                          ON r.trade_date = m.trade_date
                         AND r.concept_code = m.concept_code
                        WHERE m.trade_date IN ({placeholders})
                          AND r.rank <= 10""",
                    chunk,
                ).fetchall()
                ts_codes.update(str(row[0]).strip().upper() for row in rows if row[0])
            return ts_codes
    except sqlite3.Error:
        return set()


def collect_mainline_codes(db_path: Path, dates: list[str]) -> set[str]:
    """Return stocks that appear in exported main-line industry pools."""
    if not db_path.exists() or not dates:
        return set()

    try:
        with sqlite3.connect(db_path) as conn:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sector_ranking_history'"
            ).fetchone()
            if not exists:
                return set()

            ts_codes: set[str] = set()
            for start in range(0, len(dates), 500):
                chunk = dates[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"""SELECT DISTINCT d.ts_code
                        FROM sector_ranking_history r
                        JOIN stock_basic s
                          ON s.industry = r.industry
                         AND COALESCE(s.delist_date, '') = ''
                        JOIN daily d
                          ON d.ts_code = s.ts_code
                         AND d.trade_date = r.trade_date
                        WHERE r.trade_date IN ({placeholders})
                          AND r.rank <= 10""",
                    chunk,
                ).fetchall()
                ts_codes.update(str(row[0]).strip().upper() for row in rows if row[0])
            return ts_codes
    except sqlite3.Error:
        return set()


def build_signal_dates(search_df: pd.DataFrame, db_path: Path) -> dict[str, list[str]]:
    """Collect every exported screening date for each stock code."""
    if search_df.empty or "signal_date" not in search_df.columns:
        return {}

    code_columns = [column for column in search_df.columns if column in CODE_COLUMNS]
    if not code_columns:
        normalized_columns = {column.lower().replace("_", ""): column for column in search_df.columns}
        code_columns = [
            normalized_columns[candidate.lower().replace("_", "")]
            for candidate in CODE_COLUMNS
            if candidate.lower().replace("_", "") in normalized_columns
        ]
    if not code_columns:
        return {}

    raw_values: set[str] = set()
    for column in code_columns:
        raw_values.update(str(value).strip().upper() for value in search_df[column].dropna() if str(value).strip())
    code_map = resolve_code_map(raw_values, db_path)

    signals: dict[str, set[str]] = {}
    for _, row in search_df.iterrows():
        date = str(row.get("signal_date", "")).strip()
        if not DATE_RE.match(date):
            continue
        for column in code_columns:
            raw_code = str(row.get(column, "")).strip().upper()
            ts_code = code_map.get(raw_code)
            if ts_code:
                signals.setdefault(ts_code, set()).add(date)
                break

    return {ts_code: sorted(dates) for ts_code, dates in signals.items()}

def export_kline_data(
    ts_codes: set[str],
    signal_dates: dict[str, list[str]],
    db_path: Path,
    output_dir: Path,
    limit: int,
    generated_at: str,
    *,
    extended_ts_codes: set[str] | None = None,
    extended_limit: int = 260,
) -> dict[str, str]:
    if not ts_codes or not db_path.exists():
        return {}

    kline_dir = output_dir / "kline"
    kline_index: dict[str, str] = {}
    symbol_paths: dict[str, list[str]] = {}

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for ts_code in sorted(ts_codes):
            row_limit = max(limit, extended_limit) if ts_code in (extended_ts_codes or set()) else limit
            rows = conn.execute(
                """SELECT trade_date, open, high, low, close, pre_close, vol, amount
                   FROM daily
                   WHERE ts_code = ?
                   ORDER BY trade_date DESC
                   LIMIT ?""",
                (ts_code, row_limit),
            ).fetchall()
            if not rows:
                continue

            name_row = conn.execute(
                "SELECT name FROM stock_basic WHERE ts_code = ?",
                (ts_code,),
            ).fetchone()
            items = [dict(row) for row in reversed(rows)]
            payload = {
                "ts_code": ts_code,
                "name": name_row["name"] if name_row else "",
                "count": len(items),
                "kline": items,
                "signal_dates": signal_dates.get(ts_code, []),
                "generated_at": generated_at,
            }
            filename = f"{ts_code}.json"
            path = kline_dir / filename
            write_json(path, payload)

            relative = f"data/kline/{filename}"
            kline_index[ts_code] = relative
            symbol = ts_code.split(".", 1)[0]
            symbol_paths.setdefault(symbol, []).append(relative)

    for symbol, paths in symbol_paths.items():
        if len(paths) == 1:
            kline_index[symbol] = paths[0]

    return kline_index


def collect_strategy_codes(
    strategy_payload: dict[str, object],
    *,
    cases_only: bool = False,
) -> set[str]:
    """Collect stock codes needed for clickable strategy rows."""
    codes: set[str] = set()
    for strategy in strategy_payload.get("strategies", []):
        if not isinstance(strategy, dict):
            continue
        if not cases_only:
            for row in strategy.get("recommendations", []):
                if isinstance(row, dict) and row.get("ts_code"):
                    codes.add(str(row["ts_code"]).strip().upper())
        history = strategy.get("historical_cases", {})
        if not isinstance(history, dict):
            continue
        for bucket in ("wins", "losses"):
            for row in history.get(bucket, []):
                if isinstance(row, dict) and row.get("ts_code"):
                    codes.add(str(row["ts_code"]).strip().upper())
    return codes


def industry_counts(df: pd.DataFrame) -> dict[str, int]:
    if df.empty or "industry" not in df.columns:
        return {}

    values = df["industry"].fillna("").astype(str).str.strip()
    values = values.mask(values == "", "未分类")
    counts = values.value_counts()
    return {str(industry): int(count) for industry, count in counts.items()}


def build_industry_trends(
    daily_counts: dict[str, dict[str, int]],
    generated_at: str,
) -> dict[str, object]:
    dates = sorted(daily_counts)
    if not dates:
        return {
            "generated_at": generated_at,
            "dates": [],
            "latest_date": None,
            "previous_date": None,
            "industries": [],
            "latest": [],
            "new_latest": [],
            "removed_latest": [],
            "by_date": [],
        }

    latest_date = dates[-1]
    previous_date = dates[-2] if len(dates) >= 2 else None
    latest_counts = daily_counts.get(latest_date, {})
    previous_counts = daily_counts.get(previous_date, {}) if previous_date else {}

    all_industries = sorted({industry for counts in daily_counts.values() for industry in counts})
    first_seen = {}
    seen: set[str] = set()
    by_date = []
    for date in dates:
        counts = daily_counts[date]
        present = set(counts)
        new_industries = sorted(present - seen, key=lambda industry: (-counts[industry], industry))
        for industry in new_industries:
            first_seen[industry] = date
        by_date.append(
            {
                "date": date,
                "new_industries": [
                    {"industry": industry, "count": counts[industry]}
                    for industry in new_industries
                ],
            }
        )
        seen |= present

    industry_rows = []
    for industry in all_industries:
        counts = [
            {"date": date, "count": int(daily_counts.get(date, {}).get(industry, 0))}
            for date in dates
        ]
        latest_count = int(latest_counts.get(industry, 0))
        previous_count = int(previous_counts.get(industry, 0))
        industry_rows.append(
            {
                "industry": industry,
                "latest_count": latest_count,
                "previous_count": previous_count,
                "change": latest_count - previous_count,
                "is_new_latest": latest_count > 0 and previous_count == 0,
                "is_removed_latest": latest_count == 0 and previous_count > 0,
                "first_seen_date": first_seen.get(industry),
                "counts": counts,
            }
        )

    latest_rows = sorted(
        [row for row in industry_rows if row["latest_count"] > 0],
        key=lambda row: (-row["latest_count"], -row["change"], row["industry"]),
    )
    new_latest = [row for row in latest_rows if row["is_new_latest"]]
    removed_latest = sorted(
        [row for row in industry_rows if row["is_removed_latest"]],
        key=lambda row: (-row["previous_count"], row["industry"]),
    )

    return {
        "generated_at": generated_at,
        "dates": dates,
        "latest_date": latest_date,
        "previous_date": previous_date,
        "industries": industry_rows,
        "latest": latest_rows,
        "new_latest": new_latest,
        "removed_latest": removed_latest,
        "by_date": by_date,
    }


def export_static_data(
    data_dir: Path,
    output_dir: Path,
    db_path: Path = DEFAULT_DB_PATH,
    kline_limit: int = 120,
) -> dict[str, object]:
    data_dir = data_dir.resolve()
    output_dir = output_dir.resolve()
    db_path = db_path.resolve()

    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "dates").mkdir(parents=True, exist_ok=True)

    grouped: dict[str, list[Path]] = {}
    for path in csv_files(data_dir):
        date = csv_date(path)
        if date:
            grouped.setdefault(date, []).append(path)

    date_entries = []
    search_frames = []
    daily_industry_counts = {}
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for date in sorted(grouped, reverse=True):
        paths = grouped[date]
        df = combine_files(paths)
        daily_industry_counts[date] = industry_counts(df)
        search_df = df.copy()
        search_df.insert(0, "signal_date", date)
        search_frames.append(search_df)

        payload = frame_payload(df)
        payload.update(
            {
                "mode": "date",
                "date": date,
                "files": [relative_path(path) for path in paths],
                "row_count": len(df),
                "generated_at": generated_at,
            }
        )
        date_file = f"data/dates/{date}.json"
        write_json(output_dir / "dates" / f"{date}.json", payload)

        date_entries.append(
            {
                "date": date,
                "file": date_file,
                "files": [relative_path(path) for path in paths],
                "file_count": len(paths),
                "row_count": len(df),
            }
        )

    search_df = (
        order_columns(pd.concat(search_frames, ignore_index=True, sort=False))
        if search_frames
        else pd.DataFrame()
    )
    signal_dates = build_signal_dates(search_df, db_path)
    strategy_payload = build_strategy_dashboard(
        db_path,
        date_entries[0]["date"] if date_entries else None,
    )
    strategy_codes = collect_strategy_codes(strategy_payload)
    strategy_case_codes = collect_strategy_codes(strategy_payload, cases_only=True)
    mainline_index = export_mainline_data(db_path, output_dir, sorted(grouped))
    concept_index = export_concept_data(db_path, output_dir, sorted(grouped))
    emotion_index = export_emotion_data(db_path, output_dir, sorted(grouped))
    export_codes = resolve_export_codes(collect_code_values(search_df), db_path)
    export_codes.update(collect_mainline_codes(db_path, sorted(grouped)))
    export_codes.update(collect_concept_codes(db_path, sorted(grouped)))
    export_codes.update(collect_emotion_codes(db_path, sorted(grouped)))
    export_codes.update(strategy_codes)
    kline_index = export_kline_data(
        export_codes,
        signal_dates,
        db_path,
        output_dir,
        kline_limit,
        generated_at,
        extended_ts_codes=strategy_case_codes,
    )
    search_payload = frame_payload(search_df)
    search_payload.update(
        {
            "mode": "search_index",
            "row_count": len(search_df),
            "scanned_csv_count": sum(len(paths) for paths in grouped.values()),
            "generated_at": generated_at,
        }
    )
    write_json(output_dir / "search_index.json", search_payload)
    write_json(
        output_dir / "industry_trends.json",
        build_industry_trends(daily_industry_counts, generated_at),
    )
    write_json(output_dir / "strategies.json", strategy_payload)

    manifest = {
        "generated_at": generated_at,
        "latest_date": date_entries[0]["date"] if date_entries else None,
        "dates": date_entries,
        "search_index": "data/search_index.json",
        "industry_trends": "data/industry_trends.json",
        "strategies": "data/strategies.json",
        "mainline": "data/main_line.json" if mainline_index else None,
        "mainline_index": mainline_index,
        "concept_ranking": "data/concept_ranking.json" if concept_index else None,
        "concept_index": concept_index,
        "emotion": "data/emotion.json" if emotion_index else None,
        "emotion_index": emotion_index,
        "kline_limit": kline_limit,
        "kline_count": len({path for key, path in kline_index.items() if "." in key}),
        "kline_index": kline_index,
        "signal_dates": signal_dates,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def export_strategy_assets(
    output_dir: Path,
    db_path: Path = DEFAULT_DB_PATH,
    kline_limit: int = 120,
) -> dict[str, object]:
    """Refresh strategy assets without rewriting unrelated generated files."""
    output_dir = output_dir.resolve()
    db_path = db_path.resolve()
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError("manifest.json is missing; run a full web export first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    strategy_payload = build_strategy_dashboard(db_path, manifest.get("latest_date"))
    strategy_codes = collect_strategy_codes(strategy_payload)
    strategy_case_codes = collect_strategy_codes(strategy_payload, cases_only=True)
    signal_dates = dict(manifest.get("signal_dates") or {})
    strategy_kline_index = export_kline_data(
        strategy_codes,
        signal_dates,
        db_path,
        output_dir,
        kline_limit,
        generated_at,
        extended_ts_codes=strategy_case_codes,
    )
    kline_index = dict(manifest.get("kline_index") or {})
    kline_index.update(strategy_kline_index)
    manifest.update(
        {
            "generated_at": generated_at,
            "strategies": "data/strategies.json",
            "kline_index": kline_index,
            "kline_count": len({
                path for key, path in kline_index.items() if "." in key
            }),
        }
    )
    write_json(output_dir / "strategies.json", strategy_payload)
    write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    args = parse_args()
    if args.strategies_only:
        manifest = export_strategy_assets(args.output_dir, args.db_path, args.kline_limit)
        print(f"Strategies refreshed: {manifest['strategies']}")
        print(f"K-line files indexed: {manifest['kline_count']}")
        return 0
    manifest = export_static_data(args.data_dir, args.output_dir, args.db_path, args.kline_limit)
    print(f"Exported static web data to: {args.output_dir}")
    print(f"Dates: {len(manifest['dates'])}; latest: {manifest['latest_date']}")
    print(f"K-line files: {manifest['kline_count']}; limit: {manifest['kline_limit']}")
    print(f"Strategies: {manifest['strategies']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
