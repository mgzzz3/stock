from .db import connect

COLUMNS = (
    "ts_code", "trade_date", "open", "high", "low", "close",
    "pre_close", "change", "pct_chg", "vol", "amount",
)

_UPSERT = f"""
INSERT INTO daily ({", ".join(COLUMNS)})
VALUES ({", ".join(f":{c}" for c in COLUMNS)})
ON CONFLICT(ts_code, trade_date) DO UPDATE SET
  {", ".join(f"{c}=excluded.{c}" for c in COLUMNS if c not in ("ts_code", "trade_date"))}
"""


def upsert_many(rows):
    payload = [{c: r.get(c) for c in COLUMNS} for r in rows]
    with connect() as conn:
        conn.executemany(_UPSERT, payload)
    return len(payload)


def last_trade_date(ts_code):
    with connect() as conn:
        row = conn.execute(
            "SELECT MAX(trade_date) FROM daily WHERE ts_code=?", (ts_code,)
        ).fetchone()
    return row[0] if row and row[0] else None


def last_global_trade_date():
    """Latest trade_date across all stocks (None if table is empty)."""
    with connect() as conn:
        row = conn.execute("SELECT MAX(trade_date) FROM daily").fetchone()
    return row[0] if row and row[0] else None
