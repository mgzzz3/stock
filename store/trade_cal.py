from .db import connect

_UPSERT = """
INSERT INTO trade_cal (exchange, cal_date, is_open, pretrade_date)
VALUES (:exchange, :cal_date, :is_open, :pretrade_date)
ON CONFLICT(exchange, cal_date) DO UPDATE SET
  is_open=excluded.is_open,
  pretrade_date=excluded.pretrade_date
"""


def upsert_many(rows):
    payload = [
        {
            "exchange": r["exchange"],
            "cal_date": r["cal_date"],
            "is_open": int(r["is_open"]),
            "pretrade_date": r.get("pretrade_date"),
        }
        for r in rows
    ]
    with connect() as conn:
        conn.executemany(_UPSERT, payload)
    return len(payload)


def open_dates(exchange, start_date, end_date):
    """Return list of YYYYMMDD strings where the exchange was open."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT cal_date FROM trade_cal "
            "WHERE exchange=? AND is_open=1 AND cal_date BETWEEN ? AND ? "
            "ORDER BY cal_date",
            (exchange, start_date, end_date),
        ).fetchall()
    return [r[0] for r in rows]
