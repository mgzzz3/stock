from .db import DB_PATH, connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code     TEXT PRIMARY KEY,
    symbol      TEXT,
    name        TEXT,
    area        TEXT,
    industry    TEXT,
    market      TEXT,
    list_date   TEXT,
    delist_date TEXT,
    list_status TEXT,
    is_hs       TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_cal (
    exchange      TEXT NOT NULL,
    cal_date      TEXT NOT NULL,
    is_open       INTEGER NOT NULL,
    pretrade_date TEXT,
    PRIMARY KEY (exchange, cal_date)
);

CREATE TABLE IF NOT EXISTS daily (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    pre_close  REAL,
    change     REAL,
    pct_chg    REAL,
    vol        REAL,
    amount     REAL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_trade_date ON daily(trade_date);

CREATE TABLE IF NOT EXISTS kdj (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    k          REAL,
    d          REAL,
    j          REAL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_kdj_trade_date ON kdj(trade_date);

CREATE TABLE IF NOT EXISTS zhixing (
    ts_code     TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    trend_short REAL,
    bull_bear   REAL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_zhixing_trade_date ON zhixing(trade_date);

CREATE TABLE IF NOT EXISTS golden_pit (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    var2z      REAL,
    var3z      REAL,
    signal     INTEGER,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_golden_pit_trade_date ON golden_pit(trade_date);
CREATE INDEX IF NOT EXISTS idx_golden_pit_signal ON golden_pit(signal, trade_date);

CREATE TABLE IF NOT EXISTS signals (
    strategy   TEXT NOT NULL,
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    close      REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (strategy, ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_signals_strategy_date ON signals(strategy, trade_date);
"""


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
    print(f"initialized schema at {DB_PATH}")


if __name__ == "__main__":
    init_db()
