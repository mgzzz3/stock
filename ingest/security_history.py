"""Cache official SSE/SZSE delisting dates independently of Tushare quotas."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path

import pandas as pd
import requests

from store.db import connect

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / 'data/history_daily'


def fetch(root: Path = DEFAULT_ROOT) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    sse_path, szse_path = root / 'delisted_sse.json', root / 'delisted_szse.json'
    if not sse_path.exists():
        url = 'https://query.sse.com.cn/commonQuery.do'
        response = requests.get(url, params={
            'sqlId': 'COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L', 'isPagination': 'true',
            'STOCK_TYPE': '1,2,8', 'COMPANY_STATUS': '3', 'type': 'inParams',
            'pageHelp.pageSize': '500', 'pageHelp.pageNo': '1'},
            headers={'Referer': 'https://www.sse.com.cn/', 'User-Agent': 'Mozilla/5.0'}, timeout=20)
        response.raise_for_status()
        rows = response.json()['result']
        if not rows or len(rows) >= 500:
            raise ValueError('SSE delisting response empty or at pagination cap')
        sse_path.write_text(json.dumps({'source': url, 'rows': rows}, ensure_ascii=False))
    if not szse_path.exists():
        url = 'https://www.szse.cn/api/report/ShowReport'
        response = requests.get(url, params={'SHOWTYPE': 'xlsx', 'CATALOGID': '1793_ssgs', 'TABKEY': 'tab2'}, timeout=20)
        response.raise_for_status()
        rows = pd.read_excel(BytesIO(response.content), dtype=str).fillna('').to_dict('records')
        if not rows:
            raise ValueError('SZSE delisting response empty')
        szse_path.write_text(json.dumps({'source': url, 'rows': rows}, ensure_ascii=False))
    records = []
    for row in json.loads(sse_path.read_text())['rows']:
        code = str(row.get('A_STOCK_CODE') or '')
        if len(code) == 6 and code.startswith('6'):
            records.append({'ts_code': code + '.SH', 'name': row['COMPANY_ABBR'],
                            'list_date': row['LIST_DATE'], 'delist_date': row['DELIST_DATE'], 'source': 'SSE'})
    for row in json.loads(szse_path.read_text())['rows']:
        code = str(row['证券代码']).zfill(6)
        if code.startswith(('0', '3')):
            records.append({'ts_code': code + '.SZ', 'name': row['证券简称'],
                            'list_date': row['上市日期'], 'delist_date': row['终止上市日期'], 'source': 'SZSE'})
    for row in records:
        row['list_date'] = pd.Timestamp(row['list_date']).strftime('%Y%m%d')
        row['delist_date'] = pd.Timestamp(row['delist_date']).strftime('%Y%m%d')
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS security_delist_history (
            ts_code TEXT NOT NULL, delist_date TEXT NOT NULL, name TEXT, list_date TEXT,
            source TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(ts_code,delist_date,source))''')
        for row in records:
            conn.execute('''INSERT INTO security_delist_history VALUES (:ts_code,:delist_date,:name,:list_date,:source,:fetched_at)
                ON CONFLICT(ts_code,delist_date,source) DO UPDATE SET name=excluded.name,list_date=excluded.list_date,fetched_at=excluded.fetched_at''',
                         {**row, 'fetched_at': now})
            # Preserve the existing current master. Add missing identities for
            # chart labels; historical event dates live in their own table.
            conn.execute('''INSERT OR IGNORE INTO stock_basic
                (ts_code,symbol,name,list_date,delist_date,list_status,updated_at)
                VALUES (:ts_code,:symbol,:name,:list_date,:delist_date,'D',:updated_at)''',
                         {**row, 'symbol': row['ts_code'][:6], 'updated_at': now})
    payload = {'fetched_at': now, 'sources': ['https://www.sse.com.cn/assortment/stock/list/delisting/',
               'https://www.szse.cn/market/stock/suspend/index.html'], 'events': records}
    (root / 'delisting_events.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    return payload


if __name__ == '__main__':
    result = fetch()
    print('Official A-share delisting events:', len(result['events']))
