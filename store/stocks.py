from datetime import UTC, datetime

from .db import connect

COLUMNS = (
    "ts_code", "symbol", "name", "area", "industry",
    "market", "list_date", "delist_date", "list_status", "is_hs",
)

_UPSERT = f"""
INSERT INTO stock_basic ({", ".join(COLUMNS)}, updated_at)
VALUES ({", ".join(f":{c}" for c in COLUMNS)}, :updated_at)
ON CONFLICT(ts_code) DO UPDATE SET
  {", ".join(f"{c}=excluded.{c}" for c in COLUMNS if c != "ts_code")},
  updated_at=excluded.updated_at
"""


def upsert_many(rows):
    now = datetime.now(UTC).isoformat()
    payload = [{c: r.get(c) for c in COLUMNS} | {"updated_at": now} for r in rows]
    with connect() as conn:
        conn.executemany(_UPSERT, payload)
    return len(payload)


def count():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
