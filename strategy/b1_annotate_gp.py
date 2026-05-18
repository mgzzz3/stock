"""Annotate b1's CSV with 黄金坑 (golden_pit) info.

Run AFTER strategy.b1 has produced data/signals/b1_<date>.csv. Reads that CSV,
looks up each ticker's golden_pit values within a 90-day calendar lookback
ending on the b1 trade_date, appends four columns, and rewrites the CSV
in place:

  - gp_signal       : 1 if golden_pit fired on the b1 trade_date, else 0
  - gp_var2z        : VAR2Z value on the b1 trade_date (3 decimals)
  - gp_last_signal  : most recent golden_pit signal date in the 90-day window
  - gp_days_since   : trading days between gp_last_signal and the b1 trade_date

Assumes indicators.golden_pit was rebuilt against the same daily data the b1
screen used. The daily.sh pipeline calls `indicators.golden_pit` first.

Usage:
    uv run python -m strategy.b1_annotate_gp              # latest b1_*.csv
    uv run python -m strategy.b1_annotate_gp 20260518     # specific date
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from store.db import connect

CSV_DIR = Path("data/signals")
LOOKBACK_DAYS = 90


def _latest_csv() -> Path:
    files = sorted(CSV_DIR.glob("b1_*.csv"))
    if not files:
        raise FileNotFoundError(f"no b1_*.csv files in {CSV_DIR}")
    return files[-1]


def annotate(csv_path: Path) -> Path:
    on_date = csv_path.stem.split("_")[-1]  # b1_<YYYYMMDD>.csv
    end_dt = datetime.strptime(on_date, "%Y%m%d").date()
    start = (end_dt - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")

    # Force string for date-like columns and nullable Int64 for the integer
    # column, otherwise pandas promotes them to float on the rewrite (because
    # of NA rows) and the YYYYMMDD becomes "20260514.0".
    hits = pd.read_csv(
        csv_path,
        encoding="utf-8-sig",
        dtype={"ts_code": str, "last_signal": str, "days_since": "Int64"},
    )
    # `last_signal` may parse as the literal string "nan" for missing rows.
    hits["last_signal"] = hits["last_signal"].where(hits["last_signal"] != "nan")
    if hits.empty:
        print(f"{csv_path.name}: empty, nothing to annotate")
        return csv_path

    tickers = hits["ts_code"].tolist()
    placeholders = ",".join("?" * len(tickers))
    sql = (
        f"SELECT ts_code, trade_date, var2z, signal FROM golden_pit "
        f"WHERE ts_code IN ({placeholders}) "
        f"AND trade_date BETWEEN ? AND ? "
        f"ORDER BY ts_code, trade_date"
    )
    with connect() as conn:
        gp = pd.read_sql_query(sql, conn, params=tickers + [start, on_date])

    if gp.empty:
        print(f"{csv_path.name}: golden_pit has no data for these tickers "
              f"in [{start}, {on_date}] — was indicators.golden_pit rebuilt?")
        # Still write empty columns so downstream consumers see a stable schema.
        hits["gp_signal"] = pd.NA
        hits["gp_var2z"] = pd.NA
        hits["gp_last_signal"] = pd.NA
        hits["gp_days_since"] = pd.NA
        hits.to_csv(csv_path, index=False, encoding="utf-8-sig")
        return csv_path

    today = gp[gp["trade_date"] == on_date].set_index("ts_code")
    today_signal = today["signal"]
    today_var2z = today["var2z"]

    fired = gp[gp["signal"] == 1]
    last_signal = fired.groupby("ts_code")["trade_date"].max()

    # Trading-day index derived from the loaded golden_pit rows. This is the
    # same approach b1.py uses — count by position in the unique-dates list
    # rather than calendar diff, so weekends/holidays don't inflate the gap.
    trading_days = sorted(gp["trade_date"].unique())
    date_idx = {d: i for i, d in enumerate(trading_days)}
    on_idx = date_idx.get(on_date)

    def _days_since(d):
        if d is None or pd.isna(d) or d not in date_idx or on_idx is None:
            return None
        return on_idx - date_idx[d]

    hits["gp_signal"] = hits["ts_code"].map(today_signal).astype("Int64")
    hits["gp_var2z"] = hits["ts_code"].map(today_var2z).round(3)
    hits["gp_last_signal"] = hits["ts_code"].map(last_signal)
    hits["gp_days_since"] = hits["gp_last_signal"].apply(_days_since).astype("Int64")

    hits.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = CSV_DIR / f"b1_{sys.argv[1]}.csv"
        if not path.exists():
            raise FileNotFoundError(path)
    else:
        path = _latest_csv()

    annotate(path)
    print(f"annotated: {path}")
