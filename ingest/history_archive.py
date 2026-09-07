"""Download missing market sessions into a resumable compressed daily archive.

Raw bars stay out of the large SQLite database. Existing database sessions are
preserved; the manifest records hashes, coverage and failures for auditing.
Run: python -m ingest.history_archive --start 20150101 --end 20260904
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd

from ingest.tushare_client import get_pro
from store.daily import COLUMNS
from store import schema, stocks, trade_cal

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / 'data/history_daily'


def write_manifest(path: Path, payload: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def validate_day(frame: pd.DataFrame, date: str, *, minimum_rows: int = 500) -> dict:
    missing = set(COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f'{date}: missing columns {sorted(missing)}')
    if len(frame) < minimum_rows:
        raise ValueError(f'{date}: only {len(frame)} rows; expected a whole-market session')
    if not frame['trade_date'].astype(str).eq(date).all():
        raise ValueError(f'{date}: response contains another session')
    if frame['ts_code'].duplicated().any():
        raise ValueError(f'{date}: duplicate security codes')
    prices = frame[['open', 'close', 'pre_close']].apply(pd.to_numeric, errors='coerce')
    valid = (np.isfinite(prices).all(axis=1) & prices.gt(0).all(axis=1)
             & pd.to_numeric(frame['pct_chg'], errors='coerce').gt(-100)
             & pd.to_numeric(frame['vol'], errors='coerce').gt(0))
    if int(valid.sum()) < minimum_rows or valid.mean() < .99:
        raise ValueError(f'{date}: usable rows {int(valid.sum())}/{len(frame)} below quality gate')
    return {'row_count': len(frame), 'usable_row_count': int(valid.sum()), 'invalid_row_count': int((~valid).sum())}


def fetch_day(pro, date: str) -> pd.DataFrame:
    pages, offset = [], 0
    while True:
        page = pro.daily(trade_date=date, fields=','.join(COLUMNS), limit=6000, offset=offset)
        pages.append(page)
        if len(page) < 6000:
            break
        offset += len(page)
        if offset > 30_000:
            raise ValueError(f'{date}: pagination did not terminate')
    return pd.concat(pages, ignore_index=True)


def fetch_days(pro, dates: list[str], *, interval: float = 1.3) -> pd.DataFrame:
    """Use the documented date range and offset pagination to amortize calls."""
    pages, offset = [], 0
    while True:
        began = time.monotonic()
        page = pro.daily(start_date=dates[0], end_date=dates[-1],
                         fields=','.join(COLUMNS), limit=6000, offset=offset)
        pages.append(page)
        time.sleep(max(0, interval - (time.monotonic() - began)))
        if len(page) < 6000:
            break
        offset += len(page)
        if offset > 100_000:
            raise ValueError('Date batch pagination did not terminate')
    data = pd.concat(pages, ignore_index=True)
    if data.duplicated(['trade_date', 'ts_code']).any():
        raise ValueError('Date batch contains duplicate keys; pagination may be unsupported')
    return data[data.trade_date.astype(str).isin(dates)]


def date_batches(dates: list[str], size: int = 10) -> list[list[str]]:
    batches = []
    for date in dates:
        if (not batches or len(batches[-1]) >= size
                or (pd.Timestamp(date) - pd.Timestamp(batches[-1][-1])).days > 10):
            batches.append([])
        batches[-1].append(date)
    return batches


def archive_day(root: Path, date: str, frame: pd.DataFrame) -> dict:
    audit = validate_day(frame, date)
    relative = f'{date[:4]}/{date}.csv.gz'
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    frame.loc[:, list(COLUMNS)].sort_values('ts_code').to_csv(
        temporary, index=False, compression={'method': 'gzip', 'compresslevel': 6, 'mtime': 0})
    # Verify the persisted representation before declaring a session complete.
    restored = pd.read_csv(temporary, compression='gzip', dtype={'ts_code': str, 'trade_date': str})
    validate_day(restored, date)
    temporary.replace(path)
    return {**audit, 'path': relative, 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'fetched_at': datetime.now(timezone.utc).isoformat()}


def download(start: str, end: str, root: Path, *, interval: float = 1.3, min_free_mb: int = 512) -> dict:
    schema.init_db()
    pro = get_pro()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        'format_version': 1, 'source': 'Tushare daily', 'files': {}, 'codes': []}
    codes = set(manifest['codes'])
    calendar_path = root / 'calendar_sina.json'
    if calendar_path.exists():
        saved = json.loads(calendar_path.read_text())
        if min(saved['dates']) > start or max(saved['dates']) < end:
            raise RuntimeError('Cached public calendar does not cover the requested range')
        open_dates = set(saved['dates'])
        all_dates = pd.date_range(start, end).strftime('%Y%m%d').tolist()
        previous = ''
        rows = []
        for date in all_dates:
            rows.append({'exchange': 'SSE', 'cal_date': date, 'is_open': int(date in open_dates), 'pretrade_date': previous})
            if date in open_dates:
                previous = date
        calendar = pd.DataFrame(rows)
        manifest['calendar_source'] = saved['source']
    else:
        calendar = pro.trade_cal(exchange='SSE', start_date=start, end_date=end,
                                 fields='exchange,cal_date,is_open,pretrade_date')
        manifest['calendar_source'] = 'Tushare trade_cal SSE'
    if calendar.empty:
        raise RuntimeError('Trading calendar unavailable; refusing to infer sessions from weekdays')
    trade_cal.upsert_many(calendar.to_dict('records'))
    dates = sorted(calendar.loc[calendar.is_open.astype(int).eq(1), 'cal_date'].astype(str).tolist())
    manifest.update(requested_start=start, requested_end=end, expected_sessions=dates)
    metadata_counts = {}
    manifest['metadata_errors'] = {}
    for status in ('L', 'D', 'P'):
        try:
            data = pro.stock_basic(list_status=status, fields=','.join(stocks.COLUMNS))
            if len(data) >= 6000:
                raise RuntimeError('Stock metadata reached provider row cap; pagination required')
            stocks.upsert_many(data.to_dict('records'))
            metadata_counts[status] = len(data)
            time.sleep(interval)
        except Exception as error:
            import os
            message = str(error).replace(os.getenv('TUSHARE_TOKEN', '\0'), '[REDACTED]')[:300]
            manifest['metadata_errors'][status] = message
            print(f'Metadata refresh paused: {message}; continuing historical bars.', flush=True)
            break
    manifest['metadata_counts'] = metadata_counts
    print('metadata', metadata_counts, flush=True)
    from store.db import connect
    with connect() as conn:
        db_counts = dict(conn.execute('SELECT trade_date,count(*) FROM daily WHERE trade_date BETWEEN ? AND ? GROUP BY trade_date', (start, end)).fetchall())
        codes.update(row[0] for row in conn.execute('SELECT DISTINCT ts_code FROM daily'))
    # An obviously partial local session must be re-fetched, not skipped.
    existing = {date for date, count in db_counts.items() if count >= 500}
    manifest['existing_db_sessions'] = {date: db_counts[date] for date in sorted(existing)}
    validated = set()
    for date, item in manifest['files'].items():
        path = root / item['path']
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']:
            validated.add(date)
    manifest['files'] = {date: item for date, item in manifest['files'].items() if date in validated}
    pending = [date for date in dates if date not in existing and date not in validated]
    manifest['failures'] = {}
    print(f'coverage: {len(dates)} expected sessions, {len(existing)} in SQLite, {len(validated)} archived; fetching {len(pending)}', flush=True)
    began = time.monotonic()
    consecutive_failures = 0
    number = 0
    for batch in date_batches(pending):
        date = batch[0]
        if shutil.disk_usage(root).free < min_free_mb * 1024 ** 2:
            manifest['failures'][date] = f'Disk reserve reached ({min_free_mb} MiB)'
            break
        for attempt in range(4):
            try:
                frame = fetch_days(pro, batch, interval=interval)
                for day in batch:
                    daily_frame = frame[frame.trade_date.astype(str).eq(day)]
                    item = archive_day(root, day, daily_frame)
                    manifest['files'][day] = item
                    codes.update(daily_frame.ts_code.astype(str))
                consecutive_failures = 0
                break
            except Exception as error:
                import os
                message = str(error).replace(os.getenv('TUSHARE_TOKEN', '\0'), '[REDACTED]')[:300]
                limited = any(word in message.lower() for word in ('频率', '每分钟', 'rate limit'))
                if attempt == 3:
                    manifest['failures'][date] = message
                    consecutive_failures += 1
                    print(f'{date}: failed: {message}', flush=True)
                    break
                if limited:
                    interval = max(interval, 1.3)
                print(f'{date}: retry {attempt + 1}, {"rate limited" if limited else type(error).__name__}', flush=True)
                time.sleep(60 if limited else 2 ** (attempt + 1))
        number += len(batch)
        manifest['codes'] = sorted(codes)
        manifest['updated_at'] = datetime.now(timezone.utc).isoformat()
        manifest['missing_sessions'] = [d for d in dates if d not in existing and d not in manifest['files']]
        write_manifest(manifest_path, manifest)
        total = sum(item['row_count'] for item in manifest['files'].values())
        size = sum(item['bytes'] for item in manifest['files'].values()) / 1024 ** 2
        print(f'{number}/{len(pending)} date={batch[-1]}, archived_rows={total:,}, gzip={size:.1f} MiB, elapsed={time.monotonic()-began:.0f}s', flush=True)
        if consecutive_failures >= 3:
            print('Stopping after three consecutive failed batches; completed files are resumable.', flush=True)
            break
    manifest['codes'] = sorted(codes)
    manifest['missing_sessions'] = [d for d in dates if d not in existing and d not in manifest['files']]
    manifest['complete'] = not manifest['missing_sessions'] and not manifest['failures']
    manifest['updated_at'] = datetime.now(timezone.utc).isoformat()
    write_manifest(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='20150101')
    parser.add_argument('--end', required=True, help='Last completed and published trading date, YYYYMMDD')
    parser.add_argument('--archive-dir', type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument('--interval', type=float, default=1.3)
    args = parser.parse_args()
    if args.start > args.end:
        parser.error('--start must be before --end')
    result = download(args.start, args.end, args.archive_dir, interval=args.interval)
    print('archive complete:', result['complete'], 'missing sessions:', len(result['missing_sessions']), flush=True)
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
