from store import schema, stocks

from .tushare_client import get_pro

_FIELDS = (
    "ts_code,symbol,name,area,industry,market,"
    "list_date,delist_date,list_status,is_hs"
)


def fetch_and_store():
    schema.init_db()
    pro = get_pro()
    df = pro.stock_basic(list_status="L", fields=_FIELDS)
    n = stocks.upsert_many(df.to_dict("records"))
    print(f"stock_basic: upserted {n} listed stocks (total in DB: {stocks.count()})")


if __name__ == "__main__":
    fetch_and_store()
