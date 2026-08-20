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

CREATE TABLE IF NOT EXISTS concept_ranking_history (
    trade_date          TEXT NOT NULL,
    concept_code        TEXT NOT NULL,
    concept_name        TEXT NOT NULL,
    index_code          TEXT,
    rank                INTEGER NOT NULL,
    pct_chg             REAL,
    net_inflow_billion  REAL,
    breadth_pct         REAL,
    source              TEXT NOT NULL,
    PRIMARY KEY (trade_date, concept_code)
);

CREATE INDEX IF NOT EXISTS idx_concept_ranking_date_rank
    ON concept_ranking_history(trade_date, rank);

CREATE TABLE IF NOT EXISTS concept_member_history (
    trade_date    TEXT NOT NULL,
    concept_code  TEXT NOT NULL,
    ts_code       TEXT NOT NULL,
    stock_name    TEXT,
    member_rank   INTEGER NOT NULL,
    PRIMARY KEY (trade_date, concept_code, ts_code)
);

CREATE INDEX IF NOT EXISTS idx_concept_member_date_concept
    ON concept_member_history(trade_date, concept_code, member_rank);

CREATE TABLE IF NOT EXISTS fundamental_annual (
    ts_code          TEXT NOT NULL,
    report_date      TEXT NOT NULL,
    announcement_date TEXT NOT NULL,
    name             TEXT,
    industry         TEXT,
    revenue          REAL,
    revenue_yoy      REAL,
    net_profit       REAL,
    net_profit_yoy   REAL,
    eps              REAL,
    book_value_per_share REAL,
    roe              REAL,
    ocf_per_share    REAL,
    gross_margin     REAL,
    debt_to_assets   REAL,
    source           TEXT NOT NULL,
    fetched_at       TEXT NOT NULL,
    PRIMARY KEY (ts_code, report_date)
);

CREATE INDEX IF NOT EXISTS idx_fundamental_annual_code_announcement
    ON fundamental_annual(ts_code, announcement_date);

"""


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
    print(f"initialized schema at {DB_PATH}")


if __name__ == "__main__":
    init_db()
