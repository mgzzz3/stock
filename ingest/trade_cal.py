from datetime import datetime

from store import schema, trade_cal

from .tushare_client import get_pro


def fetch_and_store(start_date="20100101", end_date=None, exchange="SSE"):
    schema.init_db()
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    df = get_pro().trade_cal(
        exchange=exchange, start_date=start_date, end_date=end_date
    )
    n = trade_cal.upsert_many(df.to_dict("records"))
    print(f"trade_cal: upserted {n} days for {exchange} [{start_date}..{end_date}]")


if __name__ == "__main__":
    fetch_and_store()
