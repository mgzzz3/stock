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

import py_mini_racer
import requests
from akshare.datasets import get_ths_js
from bs4 import BeautifulSoup

from store import daily as daily_store
from store.db import connect


SOURCE_URL = "https://q.10jqka.com.cn/gn/"
SOURCE_NAME = "同花顺"
EXCLUDED_NAME_PREFIXES = ("同花顺",)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/89.0.4389.90 Safari/537.36"
)
MEMBER_PAGE_URL = "http://q.10jqka.com.cn/gn/detail/page/{page}/ajax/1/code/{concept_code}/"
# Anonymous THS requests are redirected to login after the fifth page.
MAX_MEMBER_PAGES = 5

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

CREATE_MEMBER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS concept_member_history (
    trade_date    TEXT NOT NULL,
    concept_code  TEXT NOT NULL,
    ts_code       TEXT NOT NULL,
    stock_name    TEXT,
    member_rank   INTEGER NOT NULL,
    PRIMARY KEY (trade_date, concept_code, ts_code)
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


def _new_ths_cookie() -> str:
    js_runtime = py_mini_racer.MiniRacer()
    js_runtime.eval(get_ths_js().read_text(encoding="utf-8"))
    return str(js_runtime.call("v"))


def _refresh_ths_cookie(session: requests.Session) -> None:
    session.headers["Cookie"] = f"v={_new_ths_cookie()}"


def _ths_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    _refresh_ths_cookie(session)
    return session


def _parse_member_page(page: str) -> tuple[list[dict[str, object]], int]:
    soup = BeautifulSoup(page, "lxml")
    page_info = soup.select_one(".page_info")
    page_count = 1
    if page_info and "/" in page_info.get_text(strip=True):
        try:
            page_count = int(page_info.get_text(strip=True).split("/", 1)[1])
        except ValueError:
            page_count = 1

    members = []
    for tr in soup.select("table tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
        if len(cells) < 3 or not cells[1].isdigit() or len(cells[1]) != 6:
            continue
        try:
            member_rank = int(cells[0])
        except ValueError:
            member_rank = len(members) + 1
        members.append(
            {
                "symbol": cells[1],
                "stock_name": cells[2],
                "member_rank": member_rank,
            }
        )
    return members, max(1, min(page_count, MAX_MEMBER_PAGES))


def fetch_concept_members(
    concept_code: str,
    session: requests.Session,
    timeout: int = 30,
) -> list[dict[str, object]]:
    def fetch_page(page_number: int) -> tuple[list[dict[str, object]], int]:
        response = None
        for _ in range(3):
            response = session.get(
                MEMBER_PAGE_URL.format(page=page_number, concept_code=concept_code),
                timeout=timeout,
            )
            if response.status_code not in (401, 403):
                break
            _refresh_ths_cookie(session)
        assert response is not None
        response.raise_for_status()
        response.encoding = "gb18030"
        page_members, page_count = _parse_member_page(response.text)
        if not page_members:
            raise RuntimeError(f"概念 {concept_code} 第 {page_number} 页未返回成分股")
        return page_members, page_count

    members, page_count = fetch_page(1)
    for page_number in range(2, page_count + 1):
        page_members, _ = fetch_page(page_number)
        members.extend(page_members)

    deduplicated = {}
    for member in members:
        deduplicated.setdefault(member["symbol"], member)
    return list(deduplicated.values())


def _resolve_member_codes(conn, memberships: dict[str, list[dict[str, object]]]) -> dict[str, str]:
    symbols = sorted(
        {
            str(member["symbol"])
            for members in memberships.values()
            for member in members
        }
    )
    mapping = {}
    for start in range(0, len(symbols), 500):
        chunk = symbols[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT symbol, ts_code FROM stock_basic WHERE symbol IN ({placeholders})",
            chunk,
        ).fetchall()
        mapping.update({row["symbol"]: row["ts_code"] for row in rows})
    return mapping


def save_concept_ranking(
    trade_date: str,
    rows: list[dict[str, object]],
    memberships: dict[str, list[dict[str, object]]],
) -> tuple[int, int]:
    with connect() as conn:
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_MEMBER_TABLE_SQL)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_concept_ranking_date_rank "
            "ON concept_ranking_history(trade_date, rank)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_concept_member_date_concept "
            "ON concept_member_history(trade_date, concept_code, member_rank)"
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

        code_map = _resolve_member_codes(conn, memberships)
        member_rows = []
        for concept_code, members in memberships.items():
            conn.execute(
                "DELETE FROM concept_member_history WHERE trade_date = ? AND concept_code = ?",
                (trade_date, concept_code),
            )
            for member in members:
                ts_code = code_map.get(str(member["symbol"]))
                if not ts_code:
                    continue
                member_rows.append(
                    (
                        trade_date,
                        concept_code,
                        ts_code,
                        member["stock_name"],
                        member["member_rank"],
                    )
                )
        conn.executemany(
            """INSERT INTO concept_member_history
               (trade_date, concept_code, ts_code, stock_name, member_rank)
               VALUES (?, ?, ?, ?, ?)""",
            member_rows,
        )
    return len(rows), len(member_rows)


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
    session = _ths_session()
    memberships = {}
    for row in rows[:10]:
        concept_code = str(row["concept_code"])
        try:
            memberships[concept_code] = fetch_concept_members(concept_code, session)
        except (requests.RequestException, RuntimeError) as error:
            print(f"warning: {row['concept_name']} 成分股获取失败: {error}")

    count, member_count = save_concept_ranking(trade_date, rows, memberships)
    leaders = "、".join(f"{row['concept_name']} {row['pct_chg']:+.2f}%" for row in rows[:3])
    print(
        f"概念板块 {trade_date}: 已保存 {count} 个概念、{member_count} 条成分关系，"
        f"前三名：{leaders}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
