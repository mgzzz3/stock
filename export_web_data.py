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


def normalize_column_name(column: object) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(column).lower())


def recognized_code_columns(columns: pd.Index) -> list[str]:
    candidates = set(CODE_COLUMNS)
    normalized_candidates = {normalize_column_name(candidate) for candidate in CODE_COLUMNS}
    code_columns: list[str] = []
    for column in columns:
        if column in candidates or normalize_column_name(column) in normalized_candidates:
            code_columns.append(column)
    return code_columns


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


def combine_files(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        df = read_csv(path)
        df.insert(0, "source_file", relative_path(path))
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    return order_columns(pd.concat(frames, ignore_index=True, sort=False))


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

    for column in recognized_code_columns(df.columns):
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


def build_signal_dates(search_df: pd.DataFrame, db_path: Path) -> dict[str, list[str]]:
    """Collect every exported screening date for each stock code."""
    if search_df.empty or "signal_date" not in search_df.columns:
        return {}

    code_columns = recognized_code_columns(search_df.columns)
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

    manifest = {
        "generated_at": generated_at,
        "latest_date": date_entries[0]["date"] if date_entries else None,
        "dates": date_entries,
        "search_index": "data/search_index.json",
        "industry_trends": "data/industry_trends.json",
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
