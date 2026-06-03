"""Search stock rows across CSV files under data/.

Usage:
    uv run python search_stock_csv.py 301297
    uv run python search_stock_csv.py 301297.SZ
    uv run python search_stock_csv.py fuled
    uv run python search_stock_csv.py "\u5bcc\u4e50\u5fb7"

The script recursively scans CSV files under data/ by default, finds rows whose
stock code or stock name matches the query, and prints the combined result.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd


DEFAULT_DATA_DIR = Path("data")
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")

CODE_COLUMNS = {
    "ts_code",
    "code",
    "symbol",
    "stock_code",
    "seccode",
    "security_code",
    "ticker",
    "gupiaodaima",
    "zhengquandaima",
    "股票代码",
    "证券代码",
}

NAME_COLUMNS = {
    "name",
    "stock_name",
    "short_name",
    "security_name",
    "gupiaomingcheng",
    "zhengquanjiancheng",
    "zhengquanmingcheng",
    "股票名称",
    "股票简称",
    "证券简称",
    "证券名称",
}

PREFERRED_COLUMNS = [
    "source_file",
    "ts_code",
    "code",
    "stock_code",
    "证券代码",
    "股票代码",
    "name",
    "stock_name",
    "股票名称",
    "股票简称",
    "证券简称",
    "trade_date",
    "date",
    "industry",
    "close",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search stock rows in CSV files under data/."
    )
    parser.add_argument("query", help="Stock name or code, e.g. 301297 or 301297.SZ")
    parser.add_argument(
        "--data-dir",
        default=DEFAULT_DATA_DIR,
        type=Path,
        help="Directory to scan recursively. Default: data",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional path to save the combined result as CSV.",
    )
    parser.add_argument(
        "--all-columns",
        action="store_true",
        help="Also search columns that do not look like stock code/name columns.",
    )
    return parser.parse_args()


def normalized_column(name: str) -> str:
    return re.sub(r"[\s_\-.]+", "", str(name).strip().lower())


def is_code_column(name: str) -> bool:
    raw = str(name).strip()
    norm = normalized_column(raw)
    return raw in CODE_COLUMNS or norm in {normalized_column(c) for c in CODE_COLUMNS}


def is_name_column(name: str) -> bool:
    raw = str(name).strip()
    norm = normalized_column(raw)
    return raw in NAME_COLUMNS or norm in {normalized_column(c) for c in NAME_COLUMNS}


def is_code_like(query: str) -> bool:
    q = query.strip().upper()
    return bool(re.fullmatch(r"\d{6}(\.(SH|SZ|BJ))?", q))


def code_variants(query: str) -> set[str]:
    q = query.strip().upper()
    variants = {q}
    if "." in q:
        variants.add(q.split(".", 1)[0])
    elif re.fullmatch(r"\d{6}", q):
        variants.update({f"{q}.SH", f"{q}.SZ", f"{q}.BJ"})
    return variants


def read_csv(path: Path) -> pd.DataFrame:
    last_error = None
    for encoding in ENCODINGS:
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise RuntimeError(f"could not decode with {', '.join(ENCODINGS)}") from last_error


def search_frame(df: pd.DataFrame, query: str, all_columns: bool) -> pd.DataFrame:
    if df.empty:
        return df

    code_cols = [c for c in df.columns if is_code_column(c)]
    name_cols = [c for c in df.columns if is_name_column(c)]
    target_cols = list(dict.fromkeys([*code_cols, *name_cols]))
    if all_columns or not target_cols:
        target_cols = list(df.columns)

    mask = pd.Series(False, index=df.index)
    code_query = is_code_like(query)
    variants = code_variants(query)

    for col in target_cols:
        values = df[col].astype(str).str.strip()
        if col in code_cols and code_query:
            upper_values = values.str.upper()
            bare_values = upper_values.str.split(".", n=1).str[0]
            mask |= upper_values.isin(variants) | bare_values.isin(variants)
        else:
            mask |= values.str.contains(query, case=False, regex=False, na=False)

    return df[mask].copy()


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def order_columns(df: pd.DataFrame) -> pd.DataFrame:
    preferred = [c for c in PREFERRED_COLUMNS if c in df.columns]
    rest = [c for c in df.columns if c not in preferred]
    return df[[*preferred, *rest]]


def search_csvs(data_dir: Path, query: str, all_columns: bool) -> tuple[pd.DataFrame, int]:
    csv_paths = sorted(data_dir.rglob("*.csv"))
    matches = []

    for path in csv_paths:
        try:
            df = read_csv(path)
        except Exception as exc:
            print(f"Skip unreadable CSV: {path} ({exc})", file=sys.stderr)
            continue

        hit = search_frame(df, query, all_columns)
        if hit.empty:
            continue

        hit.insert(0, "source_file", relative_path(path))
        matches.append(hit)

    if not matches:
        return pd.DataFrame(), len(csv_paths)

    combined = pd.concat(matches, ignore_index=True, sort=False)
    return order_columns(combined), len(csv_paths)


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir
    if not data_dir.exists():
        print(f"Data directory does not exist: {data_dir}", file=sys.stderr)
        return 1

    result, scanned = search_csvs(data_dir, args.query, args.all_columns)
    if result.empty:
        print(f"No rows found for {args.query!r}. Scanned {scanned} CSV file(s).")
        return 1

    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)

    print(f"Found {len(result)} row(s) for {args.query!r} in {scanned} CSV file(s).")
    print(result.to_string(index=False, na_rep=""))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"\nSaved combined result: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
