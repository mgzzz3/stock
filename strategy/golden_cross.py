"""MA20/MA60 golden-cross screener.

Find stocks whose short MA crossed ABOVE long MA on the most recent trade_date in DB
(or a date passed via CLI).

Usage:
    uv run python -m strategy.golden_cross               # latest date, MA20/MA60
    uv run python -m strategy.golden_cross 20260514      # specific date
    uv run python -m strategy.golden_cross 20260514 5 20 # short=5, long=20
"""
import sys
from datetime import datetime, timedelta

import pandas as pd

from . import indicators, loader


def find_crosses(short_window=20, long_window=60, on_date=None):
    on_date = on_date or loader.latest_trade_date()
    if on_date is None:
        raise RuntimeError("daily table is empty; run ingest.backfill first")

    # Pull a bit more than long_window worth of bars per stock — enough history
    # for the MA, plus margin for IPO-near-end-of-window edge cases.
    end_dt = datetime.strptime(on_date, "%Y%m%d").date()
    start_dt = end_dt - timedelta(days=long_window * 2 + 30)
    df = loader.load_all(start=start_dt.strftime("%Y%m%d"), end=on_date)

    hits = []
    for ts_code, g in df.groupby("ts_code", sort=False):
        if len(g) < long_window + 1:
            continue
        last_row = g.iloc[-1]
        if last_row["trade_date"] != on_date:
            continue  # this stock didn't trade on on_date (suspended / delisted)
        close = g["close"].reset_index(drop=True)
        s = indicators.ma(close, short_window)
        l = indicators.ma(close, long_window)
        if indicators.golden_cross(s, l).iloc[-1]:
            hits.append({
                "ts_code": ts_code,
                "trade_date": on_date,
                "close": last_row["close"],
                f"ma{short_window}": round(s.iloc[-1], 3),
                f"ma{long_window}": round(l.iloc[-1], 3),
            })

    out = pd.DataFrame(hits)
    if not out.empty:
        out = out.merge(loader.stock_names(), on="ts_code", how="left")
    return out


def _print(df, on_date, short, long):
    if df.empty:
        print(f"No MA{short}/MA{long} golden crosses on {on_date}.")
        return
    print(f"MA{short}/MA{long} golden crosses on {on_date}: {len(df)} stocks")
    cols = ["ts_code", "name", "industry", "close", f"ma{short}", f"ma{long}"]
    print(df[cols].to_string(index=False))


if __name__ == "__main__":
    args = sys.argv[1:]
    on_date = args[0] if len(args) >= 1 else None
    short = int(args[1]) if len(args) >= 2 else 20
    long = int(args[2]) if len(args) >= 3 else 60
    on_date = on_date or loader.latest_trade_date()
    result = find_crosses(short_window=short, long_window=long, on_date=on_date)
    _print(result, on_date, short, long)
