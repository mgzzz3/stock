"""Fetch conservative point-in-time inputs for the value-quality strategy.

Annual quality data comes from Eastmoney via AkShare and retains the latest
announcement date exposed by the source.  A report is never available to the
strategy before that date.  Historical PE/PB proxies are calculated later from
the report's EPS/book value per share and the price known on the signal date.

Usage:
    python -m ingest.fundamentals --history
    python -m ingest.fundamentals
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sqlite3

import akshare as ak
import pandas as pd

from store import schema
from store.db import connect


SOURCE = "eastmoney-akshare"
MIN_HISTORY_YEAR = 2021
REFRESH_DAYS = 7


def _ts_code(value: object) -> str | None:
    code = str(value or "").split(".")[0].zfill(6)
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith(("60", "68", "90")):
        return f"{code}.SH"
    if code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    if code.startswith(("43", "83", "87", "88", "92")):
        return f"{code}.BJ"
    return None


def _date_text(value: object) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y%m%d")


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _annual_frame(report_date: str) -> pd.DataFrame:
    performance = ak.stock_yjbb_em(date=report_date).copy()
    balance = ak.stock_zcfz_em(date=report_date).copy()
    performance["ts_code"] = performance["股票代码"].map(_ts_code)
    balance["ts_code"] = balance["股票代码"].map(_ts_code)
    performance["performance_announcement"] = performance["最新公告日期"].map(_date_text)
    balance["balance_announcement"] = balance["公告日期"].map(_date_text)
    performance = performance.dropna(subset=["ts_code"]).drop_duplicates("ts_code", keep="last")
    balance = balance.dropna(subset=["ts_code"]).drop_duplicates("ts_code", keep="last")
    merged = performance.merge(
        balance[["ts_code", "资产负债率", "balance_announcement"]],
        on="ts_code",
        how="left",
    )
    merged["announcement_date"] = (
        merged[["performance_announcement", "balance_announcement"]]
        .fillna("")
        .max(axis=1)
        .replace("", pd.NA)
    )
    merged = merged.dropna(subset=["announcement_date"])
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return pd.DataFrame(
        {
            "ts_code": merged["ts_code"],
            "report_date": report_date,
            "announcement_date": merged["announcement_date"],
            "name": merged["股票简称"],
            "industry": merged["所处行业"],
            "revenue": _number(merged["营业总收入-营业总收入"]),
            "revenue_yoy": _number(merged["营业总收入-同比增长"]),
            "net_profit": _number(merged["净利润-净利润"]),
            "net_profit_yoy": _number(merged["净利润-同比增长"]),
            "eps": _number(merged["每股收益"]),
            "book_value_per_share": _number(merged["每股净资产"]),
            "roe": _number(merged["净资产收益率"]),
            "ocf_per_share": _number(merged["每股经营现金流量"]),
            "gross_margin": _number(merged["销售毛利率"]),
            "debt_to_assets": _number(merged["资产负债率"]),
            "source": SOURCE,
            "fetched_at": fetched_at,
        }
    )


def _upsert_fundamentals(conn: sqlite3.Connection, frame: pd.DataFrame) -> int:
    columns = list(frame.columns)
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(
        f"{column}=excluded.{column}"
        for column in columns
        if column not in {"ts_code", "report_date"}
    )
    sql = (
        f"INSERT INTO fundamental_annual ({','.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(ts_code, report_date) DO UPDATE SET {updates}"
    )
    values = frame.where(pd.notna(frame), None).itertuples(index=False, name=None)
    conn.executemany(sql, list(values))
    return int(len(frame))


def refresh(*, history: bool = False, force: bool = False) -> None:
    schema.init_db()
    current_year = datetime.now().year
    years = list(range(max(MIN_HISTORY_YEAR, current_year - 5), current_year))
    if not history:
        years = years[-2:]
    with connect() as conn:
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(fundamental_annual)")
        }
        if "eps" not in columns:
            conn.execute("ALTER TABLE fundamental_annual ADD COLUMN eps REAL")
        if "book_value_per_share" not in columns:
            conn.execute(
                "ALTER TABLE fundamental_annual ADD COLUMN book_value_per_share REAL"
            )
        for year in years:
            report_date = f"{year}1231"
            recent = conn.execute(
                """SELECT fetched_at FROM fundamental_annual
                   WHERE report_date = ? ORDER BY fetched_at DESC LIMIT 1""",
                (report_date,),
            ).fetchone()
            if recent and not force:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(str(recent[0]))
                if age.days < REFRESH_DAYS:
                    print(f"fundamental {report_date}: fresh, skipped")
                    continue
            frame = _annual_frame(report_date)
            count = _upsert_fundamentals(conn, frame)
            conn.commit()
            print(f"fundamental {report_date}: {count} rows")

        conn.execute("PRAGMA optimize")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    refresh(history=args.history, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
