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
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from search_stock_csv import order_columns, read_csv, relative_path


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "data"
DEFAULT_OUTPUT_DIR = ROOT / "web" / "data"
DATE_RE = re.compile(r"(?<!\d)(20\d{6})(?!\d)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export web/static JSON data.")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, type=Path)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
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


def export_static_data(data_dir: Path, output_dir: Path) -> dict[str, object]:
    data_dir = data_dir.resolve()
    output_dir = output_dir.resolve()

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
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    args = parse_args()
    manifest = export_static_data(args.data_dir, args.output_dir)
    print(f"Exported static web data to: {args.output_dir}")
    print(f"Dates: {len(manifest['dates'])}; latest: {manifest['latest_date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
