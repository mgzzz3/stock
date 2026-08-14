"""Fetch and persist the daily Tonghuashun concept-board ranking.

The public concept page exposes a market snapshot containing each board's
daily change, main-fund flow, and rising-stock ratio. The snapshot is stored
against the latest local trading date so the static web export can retain
history as the daily job runs.
"""

from __future__ import annotations

import argparse
import json
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from store import daily as daily_store
from store.db import connect


SOURCE_URL = "https://q.10jqka.com.cn/gn/"
SOURCE_NAME = "同花顺"
EXCLUDED_NAME_PREFIXES = ("同花顺",)

CREATE_TABLE_SQL = """
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
)
"""


class ConceptSnapshotParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.snapshot: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = dict(attrs)
        if values.get("id") == "gnSection":
            self.snapshot = values.get("value")


def _optional_float(value: object) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_concept_ranking(timeout: int = 30) -> list[dict[str, object]]:
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        page = response.read().decode("gb18030", errors="replace")

    parser = ConceptSnapshotParser()
    parser.feed(page)
    if not parser.snapshot:
        raise RuntimeError("同花顺概念页未返回行情快照")

    snapshot = json.loads(parser.snapshot)
    rows = []
    for item in snapshot.values():
        concept_name = str(item.get("platename") or "").strip()
        concept_code = str(item.get("cid") or "").strip()
        pct_chg = _optional_float(item.get("199112"))
        if (
            not concept_name
            or not concept_code
            or pct_chg is None
            or concept_name.startswith(EXCLUDED_NAME_PREFIXES)
        ):
            continue
        rows.append(
            {
                "concept_code": concept_code,
                "concept_name": concept_name,
                "index_code": str(item.get("platecode") or "").strip() or None,
                "pct_chg": pct_chg,
                "net_inflow_billion": _optional_float(item.get("zjjlr")),
                "breadth_pct": _optional_float(item.get("zfl")),
            }
        )

    if not rows:
        raise RuntimeError("同花顺概念行情快照为空")

    rows.sort(
        key=lambda row: (
            float(row["pct_chg"]),
            float(row["net_inflow_billion"] or 0),
        ),
        reverse=True,
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


def save_concept_ranking(trade_date: str, rows: list[dict[str, object]]) -> int:
    with connect() as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_concept_ranking_date_rank "
            "ON concept_ranking_history(trade_date, rank)"
        )
        conn.execute("DELETE FROM concept_ranking_history WHERE trade_date = ?", (trade_date,))
        conn.executemany(
            """INSERT INTO concept_ranking_history
               (trade_date, concept_code, concept_name, index_code, rank,
                pct_chg, net_inflow_billion, breadth_pct, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    trade_date,
                    row["concept_code"],
                    row["concept_name"],
                    row["index_code"],
                    row["rank"],
                    row["pct_chg"],
                    row["net_inflow_billion"],
                    row["breadth_pct"],
                    SOURCE_NAME,
                )
                for row in rows
            ],
        )
    return len(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="更新同花顺概念板块涨幅排名")
    parser.add_argument("trade_date", nargs="?", help="归档交易日，默认使用本地最新交易日")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    trade_date = args.trade_date or daily_store.last_global_trade_date()
    if not trade_date or len(trade_date) != 8 or not trade_date.isdigit():
        raise SystemExit("未找到有效交易日")

    rows = fetch_concept_ranking()
    count = save_concept_ranking(trade_date, rows)
    leaders = "、".join(f"{row['concept_name']} {row['pct_chg']:+.2f}%" for row in rows[:3])
    print(f"概念板块 {trade_date}: 已保存 {count} 个，前三名：{leaders}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
