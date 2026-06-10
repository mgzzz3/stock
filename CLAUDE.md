# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A-share (中国 A 股) quantitative analysis pipeline in Python:

1. **`ingest/`** — pull raw market data from [Tushare](https://tushare.pro/) → `store`.
2. **`store/`** — SQLite persistence (schema + per-table repos). Holds both raw bars and computed indicators.
3. **`indicators/`** — read raw daily bars from `store`, compute derived indicators (KDJ, …), write them back to `store`. ETL between raw and analysis-ready layers.
4. **`strategy/`** — quant strategies / backtests. Reads from `store` (raw + indicators), never recomputes.

**Module boundaries:**
- `ingest` writes to `store`; never reads `indicators` or `strategy`.
- `indicators` reads `daily` from `store`, writes indicator tables to `store`; never imports from `ingest` or `strategy`.
- `strategy` reads from `store` (often via `strategy.loader` or via `indicators.<x>.load`); never writes, never calls Tushare.

This separation lets strategies reuse pre-computed indicators across many runs without redoing the math. Adding a new indicator = one table in `store/schema.py` + one file in `indicators/` exposing `compute_one()` / `rebuild()` / `load()`.

## Tooling & environment

- **Package manager:** `uv` (configured as an application — `[tool.uv] package = false`).
- **Python:** 3.13+.
- **Database:** SQLite, path from `STOCK_DB_PATH` env var (default `./data/stock.db`).
- **Secrets:** `TUSHARE_TOKEN` in `.env` (gitignored), loaded via `python-dotenv`.

### Required flags on this machine

- `uv sync --system-certs` — corporate TLS chain isn't in uv's bundled trust store; plain `uv sync` fails with `UnknownIssuer`.
- `truststore.inject_into_ssl()` is called in `ingest/tushare_client.py` before importing `tushare`, so `requests` uses the system trust store at runtime. **Do not reorder the imports** in that file.

### Common commands

```bash
uv sync --system-certs                              # install/refresh deps
uv run python -m store.schema                       # init schema (idempotent; ingest auto-calls it)
uv run python -m ingest.stock_basic                 # pull listed stocks → stock_basic

# Daily bars — single-shot
uv run python -m ingest.daily 20260514              # one trade date (all stocks)
uv run python -m ingest.daily 000001.SZ 20240101 20241231  # one stock across a range
uv run python -m ingest.daily --range 20260501 20260514    # range, all stocks (uses fetch_range)

# Daily bars — bulk
uv run python -m ingest.backfill                    # last 5 years → today
uv run python -m ingest.backfill 20250101 20260101  # custom range
uv run python -m ingest.incremental                 # max(trade_date) in DB → today
```

`backfill` and `incremental` both delegate to `ingest.daily.fetch_range`, which:
- iterates **weekdays only** (skips Sat/Sun client-side without API calls),
- treats empty API responses as non-trading days (Chinese public holidays, future dates) and skips them,
- sleeps **1.3s between calls by default** to stay under Tushare's 50/min limit on `daily` (see below),
- detects rate-limit errors (`频率超限`) and sleeps a full **60s** before retrying — exponential backoff is used for other errors,
- is **idempotent** (`ON CONFLICT DO UPDATE`) — safe to re-run after interruption.

The default five-year backfill takes roughly 25–35 minutes at the safe pacing, depending on holidays and rate limits.

### Tushare rate limit (critical)

The `daily` endpoint is throttled to **50 calls/minute** at the current account tier. The error message is `抱歉，您访问接口(daily)频率超限(50次/分钟)`. Implications:

- Never lower `sleep_seconds` below ~1.2 without confirming the account tier was upgraded.
- If a long backfill leaves gap days (FAILED entries in the log), the simplest recovery is to re-run `ingest.backfill` with the same range — successful days no-op via the upsert, failed days retry. Or pass the gap range explicitly.
- The rate-limit window is per-minute; on `频率超限` the retry sleeps a full 60s rather than 2/4/8s exponential — this is intentional, do not "optimize" it back to short backoffs.

## Recommended workflow

**First-time setup on a fresh checkout**

```bash
uv sync --system-certs
uv run python -m ingest.stock_basic    # one-shot, list of A-share tickers
uv run python -m ingest.backfill       # one-shot, default last 5 years of daily bars
```

**Ongoing**

```bash
uv run python -m ingest.incremental    # run daily (or before any analysis session)
```

**Full daily refresh (one shot)**

```bash
./daily.sh                              # incremental → kdj → zhixing → b1
```

`daily.sh` runs the four steps in order, all idempotent, all fail-fast. Suitable for cron / launchd after 16:30 China time. Output: terminal trace + `data/signals/b1_<date>.csv` + new `signals` table rows.

`incremental` is the workhorse for keeping the DB current. It reads `MAX(trade_date)` and pulls forward to today, skipping weekends/holidays. Run it before doing any strategy work so signals aren't computed on stale data.

**When to re-run `stock_basic`**

`stock_basic` is a snapshot of *currently listed* (`list_status=L`) names. New IPOs and delistings change the set, so re-run it monthly or before universe-sensitive analysis. Without re-running, you'll silently miss new listings (though `daily` ingest will still pull their bars — `daily` doesn't filter by `stock_basic`).

**Dedup guarantees**

Both tables have composite primary keys that make duplicates impossible at the DB level:
- `stock_basic` — PK `ts_code`
- `daily` — PK `(ts_code, trade_date)`

Every ingest uses `ON CONFLICT ... DO UPDATE`, so re-running over an existing range overwrites rather than appends. **No deduplication step is needed before computing indicators** — the schema enforces it. If you ever see `COUNT(*) != COUNT(DISTINCT ts_code, trade_date)` on `daily`, something is wrong with the schema, not the data.

**Recovering from an interrupted backfill**

Just re-run `ingest.backfill` (or `ingest.incremental` if some progress was made). The upserts are idempotent, and `incremental` will figure out where to resume from the DB itself.

## Indicators module

`indicators/` holds **persisted** derived signals — computed once from `daily`, stored in their own tables, queried many times by strategies. Each indicator family is a single file:

```
indicators/
├── kdj.py          # K, D, J (N=9, SMA convention, K(0)=D(0)=50)
├── zhixing.py      # 知行合一 — trend_short = EMA(EMA(C,10),10),
│                   #             bull_bear   = mean of MA(C, 14/28/57/114)
└── (future: macd.py, rsi.py, boll.py, ...)
```

Each indicator file exposes the same three-function API:

- **`compute_one(...)`** — pure function on numpy/pandas arrays, returns the indicator values. Useful for tests and one-off computation.
- **`rebuild()`** — full recompute over the entire `daily` table, upserts to the indicator's storage table. Idempotent. CLI entrypoint.
- **`load(ts_code=None, start=None, end=None)`** — read the persisted values. Returns a DataFrame (single-stock indexed by `trade_date` when `ts_code` given, otherwise long-format).

```bash
uv run python -m indicators.kdj         # full rebuild (~2s for 1.3M rows)
uv run python -m indicators.zhixing     # 知行合一 trend_short + bull_bear (~3s)
```

**Incremental updates**: not yet implemented. After `ingest.incremental` adds new daily rows, you must re-run `indicators.<name>` to pick them up. Full rebuilds are fast enough (~2s for KDJ on 1.3M rows) that this is fine for now. If/when it stops being fine, KDJ-like recursive indicators need to seed from the last persisted K/D — design with care.

**Storage convention**: indicator tables share the PK shape `(ts_code, trade_date)` with `daily`. Don't store the parameter (e.g. N=9) in the table — fix one canonical parameterization per indicator and document it in the module docstring. If you need multiple Ns, split into separate tables (`kdj_9`, `kdj_14`) rather than adding a column.

**Adding a new indicator** — checklist:
1. Add table to `store/schema.py` with PK `(ts_code, trade_date)`.
2. Create `indicators/<name>.py` with `compute_one`, `rebuild`, `load`, `__main__`.
3. Run `uv run python -m indicators.<name>` once to populate.
4. From a strategy: `from indicators import <name>; df = <name>.load(...)`.

## Strategy module

`strategy/` is read-only against the DB. Layers:

- **`strategy/loader.py`** — pandas-DataFrame access to `daily` and `stock_basic`. Strategies must go through this, not raw SQL.
  - `load_one(ts_code, start=None, end=None)` → single-stock timeseries, indexed by `trade_date`.
  - `load_all(start, end, columns=("close",))` → long-format `(ts_code, trade_date, *columns)` across all stocks. Restrict `columns` for memory.
  - `latest_trade_date()` / `stock_names()` — helpers.
- **`strategy/indicators.py`** — small set of pure helper functions on pandas Series (`ma`, `golden_cross`, `death_cross`) used inline by strategy scripts. **This is separate from the top-level `indicators/` package** — `strategy/indicators.py` is one-off cheap math, the `indicators/` package is persisted DB-backed signals. For anything heavy or reused across strategies, add it to `indicators/`, not here.
- **`strategy/<screener>.py`** — composes loader + indicators into a runnable screen.

```bash
uv run python -m strategy.golden_cross              # MA20/MA60 screen on latest trade_date
uv run python -m strategy.golden_cross 20260514     # specific date
uv run python -m strategy.golden_cross 20260514 5 20  # short=5, long=20

uv run python -m strategy.backtest_cross            # historical scan, last 180 days, MA20/MA60
uv run python -m strategy.backtest_cross 20251101 20260331       # custom range
uv run python -m strategy.backtest_cross 20251101 20260331 5 20  # custom range + MAs

uv run python -m strategy.b1                        # strategy b1 — 5-condition pullback screen, latest date
uv run python -m strategy.b1 20260514               # specific date
uv run python -m strategy.b1_backtest               # b1 historical backtest, last 180 days
uv run python -m strategy.b1_backtest 20251101 20260331  # custom range
```

**Strategy b1** (`strategy/b1.py`) filters one trade_date for stocks satisfying ALL of:
1. 缩量 (vol < MA(vol, 5))
2. KDJ J < 15 (oversold; reads `indicators.kdj`)
3. close > MA(close, 60)
4. 知行短期趋势线 > 知行多空线 (reads `indicators.zhixing`)
5. close > 知行多空线

Each run of `strategy.b1`:
- prints summary + per-condition pass counts + industry distribution (top 10) + sorted hit table
- writes `data/signals/b1_<date>.csv` (UTF-8 with BOM for Excel)
- persists hits into the `signals` table with `strategy='b1'` (idempotent — PK includes trade_date)
- shows each hit's prior b1 signal within a 90-day calendar lookback and the trading-days-since count; `—` / NA means no prior trigger in that window

MA60 and vol_MA5 are computed inline; if added to `indicators/` later, swap the inline math for a `.load()` call.

`strategy/b1_backtest.py` runs b1 over a historical window and reports per-horizon mean / median / win-rate alongside a market baseline (mean forward return across all stocks on the same signal dates). This is signal-level evaluation only — portfolio-level metrics (max drawdown, Sharpe) require a position-construction rule (top-N, hold-H, max concurrent positions) layered on top.

`backtest_cross` reports per-horizon **mean / median / win-rate** alongside a **market baseline** (mean forward return across all stocks on the same signal dates). The *lift* column is what matters — raw signal returns in a trending market confound the signal's edge with the market drift, so always read the lift, not the absolute number.

**Strategy conventions**

- `trade_date` in DataFrames stays as a YYYYMMDD string — match what `store.daily` returns. Don't convert to `datetime64[ns]` unless a specific indicator needs it; ad-hoc conversions break joins.
- For backtests over long windows, load the *minimum* date range needed (`load_all(start, end)`) — the full table is 1M+ rows.
- `groupby('ts_code', sort=False)` preserves the DB's `(ts_code, trade_date)` ordering — don't re-sort inside the group unless the indicator demands it.

## Schema (`store/schema.py`)

- `stock_basic` — PK `ts_code`. Listed-only by default; extend `ingest/stock_basic.py` to also pull `list_status=D|P` if delisted/paused are needed.
- `trade_cal` — PK `(exchange, cal_date)`. **Currently unused** — see permissions note below.
- `daily` — PK `(ts_code, trade_date)`. OHLCV + pct_chg. Indexed on `trade_date` for date-slice queries.
- `signals` — PK `(strategy, ts_code, trade_date)`. Append-only record of which strategies fired for which stocks on which days. Written by `strategy.b1` (and any future strategy that calls `store.signals.upsert_many`). Useful for follow-up tracking across runs.

All upserts use `ON CONFLICT ... DO UPDATE` so re-ingestion is idempotent.

## Tushare permissions

The current `TUSHARE_TOKEN` has access to `stock_basic` and `daily` but **not** `trade_cal` (raises `没有接口(trade_cal)访问权限`). Until the account is upgraded:

- Don't rely on `ingest/trade_cal.py` — it will fail. Code is left in place for when permission is granted.
- To detect non-trading days, call `ingest.daily.fetch_for_date(date)` and check the returned row count — 0 rows means market was closed.
- For date math, avoid `pandas.bdate_range` (Western business calendar). Either pull `daily` with a date range (Tushare skips non-trading days server-side) or work date-by-date.

## Conventions

- **Date format:** YYYYMMDD strings throughout (matches Tushare's wire format). Don't silently convert to ISO `YYYY-MM-DD` — it breaks join keys.
- **Rate limits:** Tushare throttles by user score. For long backfills, iterate by trade_date with sleeps; the `ON CONFLICT` upserts make re-runs safe after throttling.
- **Module boundaries:** Schema changes live in `store/schema.py`. If `ingest/` or `strategy/` needs a new column, add it there first, then consume it.
- **Imports in `ingest/`:** Always `from store import <module>` (absolute). Don't do relative imports across the three top-level packages.
