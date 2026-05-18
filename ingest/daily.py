import sys
import time
from datetime import date, datetime, timedelta

from tqdm import tqdm

from store import daily, schema

from .tushare_client import get_pro


def fetch_for_date(trade_date):
    """Pull every stock's daily bar for one trading day."""
    schema.init_db()
    df = get_pro().daily(trade_date=trade_date)
    n = daily.upsert_many(df.to_dict("records"))
    print(f"daily: upserted {n} bars for trade_date={trade_date}")
    return n


def fetch_for_code(ts_code, start_date, end_date):
    """Pull one stock's daily bars across a date range."""
    schema.init_db()
    df = get_pro().daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    n = daily.upsert_many(df.to_dict("records"))
    print(f"daily: upserted {n} bars for {ts_code} [{start_date}..{end_date}]")
    return n


def fetch_range(start_date, end_date, sleep_seconds=1.3, max_retries=4):
    """Iterate weekdays from start_date to end_date inclusive (YYYYMMDD strings),
    calling daily(trade_date=X) for each. Empty results (holidays, future dates,
    or pre-close on current day) are skipped. Idempotent — safe to re-run.

    Default sleep_seconds=1.3 keeps us under Tushare's 50 calls/min limit on `daily`.
    Rate-limit errors are caught and trigger a 60s sleep (full quota-window reset)
    rather than exponential backoff."""
    schema.init_db()
    pro = get_pro()
    start, end = _parse(start_date), _parse(end_date)
    if start > end:
        print(f"start_date {start_date} > end_date {end_date}; nothing to do")
        return

    weekdays = []
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri; Chinese holidays still pass here but return empty
            weekdays.append(d)
        d += timedelta(days=1)

    print(f"fetch_range: {start_date} → {end_date}  ({len(weekdays)} weekdays)")
    total_bars = 0
    trading_days = 0
    bar = tqdm(weekdays, unit="day")
    for d in bar:
        ds = d.strftime("%Y%m%d")
        df = _call_with_retry(pro, ds, max_retries, bar)
        if df is None:
            continue  # error already reported via bar.write
        if len(df) == 0:
            bar.write(f"  {ds}  skipped (holiday or no data yet)")
            time.sleep(sleep_seconds)
            continue
        n = daily.upsert_many(df.to_dict("records"))
        total_bars += n
        trading_days += 1
        bar.set_postfix(date=ds, bars=n, total=total_bars)
        time.sleep(sleep_seconds)
    print(f"done: {total_bars} bars across {trading_days} trading days")


def _parse(s):
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _call_with_retry(pro, trade_date, max_retries, bar):
    for attempt in range(1, max_retries + 1):
        try:
            return pro.daily(trade_date=trade_date)
        except Exception as e:
            msg = str(e)
            is_rate_limit = "频率超限" in msg or "rate" in msg.lower()
            if attempt == max_retries:
                bar.write(f"  {trade_date}  FAILED after {max_retries} retries: {e}")
                return None
            backoff = 60 if is_rate_limit else 2 ** attempt
            kind = "rate-limited" if is_rate_limit else "error"
            bar.write(
                f"  {trade_date}  {kind} (try {attempt}/{max_retries}): {msg}; "
                f"sleeping {backoff}s"
            )
            time.sleep(backoff)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 1:
        fetch_for_date(args[0])
    elif len(args) == 3 and args[0] == "--range":
        fetch_range(args[1], args[2])
    elif len(args) == 3:
        fetch_for_code(args[0], args[1], args[2])
    else:
        ds = datetime.now().strftime("%Y%m%d")
        print(f"no args; defaulting to fetch_for_date({ds})")
        fetch_for_date(ds)
