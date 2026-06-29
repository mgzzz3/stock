"""Export CSV signal files into static JSON for GitHub Pages.

Usage:
    uv run python export_web_data.py

The generated files live under web/data/ and can be served by GitHub Pages:
    web/data/manifest.json
    web/data/dates/<YYYYMMDD>.json
    web/data/search_index.json
    web/data/industry_trends.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from search_stock_csv import order_columns, read_csv, relative_path


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
) -> dict[str, str]:
    if not ts_codes or not db_path.exists():
        return {}

    kline_dir = output_dir / "kline"
    kline_index: dict[str, str] = {}
    symbol_paths: dict[str, list[str]] = {}

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for ts_code in sorted(ts_codes):
            rows = conn.execute(
                """SELECT trade_date, open, high, low, close, pre_close, vol, amount
                   FROM daily
                   WHERE ts_code = ?
                   ORDER BY trade_date DESC
                   LIMIT ?""",
                (ts_code, limit),
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
    kline_index = export_kline_data(
        resolve_export_codes(collect_code_values(search_df), db_path),
        signal_dates,
        db_path,
        output_dir,
        kline_limit,
        generated_at,
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
    mainline_index = export_mainline_data(db_path, output_dir, sorted(grouped))

    manifest = {
        "generated_at": generated_at,
        "latest_date": date_entries[0]["date"] if date_entries else None,
        "dates": date_entries,
        "search_index": "data/search_index.json",
        "industry_trends": "data/industry_trends.json",
        "mainline": "data/main_line.json" if mainline_index else None,
        "mainline_index": mainline_index,
        "kline_limit": kline_limit,
        "kline_count": len({path for key, path in kline_index.items() if "." in key}),
        "kline_index": kline_index,
        "signal_dates": signal_dates,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    args = parse_args()
    manifest = export_static_data(args.data_dir, args.output_dir, args.db_path, args.kline_limit)
    print(f"Exported static web data to: {args.output_dir}")
    print(f"Dates: {len(manifest['dates'])}; latest: {manifest['latest_date']}")
    print(f"K-line files: {manifest['kline_count']}; limit: {manifest['kline_limit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
