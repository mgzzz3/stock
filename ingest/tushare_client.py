import os

import truststore
from dotenv import load_dotenv

truststore.inject_into_ssl()
load_dotenv()

import tushare as ts  # noqa: E402 — must follow truststore.inject_into_ssl()

_pro = None


def get_pro():
    global _pro
    if _pro is None:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            raise RuntimeError(
                "TUSHARE_TOKEN not set. Copy .env.example to .env and fill it in."
            )
        ts.set_token(token)
        _pro = ts.pro_api()
    return _pro
