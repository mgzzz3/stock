"""Backfill multiple years of daily bars (or a custom range).

The default five-year history gives the prediction model several market cycles
instead of the previous one-year sample. Existing rows are upserted, so reruns
are safe.

Usage:
    uv run python -m ingest.backfill                       # default: last 5 years
    uv run python -m ingest.backfill --years 8             # last 8 years
    uv run python -m ingest.backfill 20200101 20260101     # custom YYYYMMDD range
"""
import argparse
from datetime import date, datetime, timedelta

from .daily import fetch_range

DEFAULT_HISTORY_YEARS = 5


def backfill(start_date=None, end_date=None, *, years=DEFAULT_HISTORY_YEARS):
    end = date.today() if end_date is None else _parse(end_date)
    start = (
        end - timedelta(days=round(365.25 * years))
        if start_date is None
        else _parse(start_date)
    )
    fetch_range(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))


def _parse(value):
    return datetime.strptime(value, "%Y%m%d").date()


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start_date", nargs="?")
    parser.add_argument("end_date", nargs="?")
    parser.add_argument(
        "--years",
        type=int,
        default=DEFAULT_HISTORY_YEARS,
        help=f"未指定日期时回填的年数，默认 {DEFAULT_HISTORY_YEARS}",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if (args.start_date is None) != (args.end_date is None):
        raise SystemExit("请同时提供 start_date 和 end_date，或都不提供")
    if args.years <= 0:
        raise SystemExit("--years 必须大于 0")
    backfill(args.start_date, args.end_date, years=args.years)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
