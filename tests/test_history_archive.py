import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd

from ingest.history_archive import archive_day, date_batches, fetch_days, validate_day
from strategy.emotion import load_market, prepare_market


def day_frame(date='20200102', count=600):
    return pd.DataFrame({'ts_code': [f'{i:06d}.SZ' for i in range(count)],
        'trade_date': [date] * count, 'open': [10.] * count, 'high': [10.2] * count,
        'low': [9.9] * count, 'close': [10.1] * count, 'pre_close': [10.] * count,
        'change': [.1] * count, 'pct_chg': [1.] * count, 'vol': [200_000.] * count,
        'amount': [200_000.] * count})


class HistoryArchiveTests(unittest.TestCase):
    def test_validation_rejects_partial_duplicate_and_wrong_dates(self):
        frame = day_frame()
        self.assertEqual(validate_day(frame, '20200102')['row_count'], 600)
        for bad in (frame.iloc[:100], pd.concat([frame, frame.iloc[:1]]), frame.assign(trade_date='20200103')):
            with self.assertRaises(ValueError):
                validate_day(bad, '20200102')
        frame.loc[:20, 'open'] = float('nan')
        with self.assertRaises(ValueError):
            validate_day(frame, '20200102')

    def test_archive_is_verified_and_hashable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = archive_day(root, '20200102', day_frame())
            path = root / entry['path']
            self.assertEqual(entry['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(entry['row_count'], 600)
            self.assertFalse(path.with_suffix('.tmp').exists())
            restored = pd.read_csv(path, dtype={'ts_code': str, 'trade_date': str})
            pd.testing.assert_frame_equal(restored, day_frame())

    def test_batches_do_not_query_across_long_known_data_gaps(self):
        batches = date_batches(['20200102', '20200103', '20220505', '20220506'], size=10)
        self.assertEqual(batches, [['20200102', '20200103'], ['20220505', '20220506']])

    @patch('ingest.history_archive.time.sleep')
    def test_batch_pagination_preserves_all_rows(self, _sleep):
        pro = Mock()
        first, last = day_frame(count=6000), day_frame('20200103', count=700)
        pro.daily.side_effect = [first, last]
        result = fetch_days(pro, ['20200102', '20200103'])
        self.assertEqual(len(result), 6700)
        self.assertEqual(pro.daily.call_args_list[1].kwargs['offset'], 6000)

    @patch('ingest.history_archive.time.sleep')
    def test_ignored_pagination_fails_closed(self, _sleep):
        pro = Mock()
        pro.daily.side_effect = [day_frame(count=6000), day_frame(count=100)]
        with self.assertRaises(ValueError):
            fetch_days(pro, ['20200102'])

    def test_chunked_loader_matches_features_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / 'stock.db'
            archive = root / 'history_daily'
            archive.mkdir()
            early, late = day_frame('20200102'), day_frame('20200103')
            stocks = pd.DataFrame({'ts_code': early.ts_code, 'name': ['测试'] * 600,
                                   'industry': ['行业'] * 600, 'list_status': ['L'] * 600,
                                   'list_date': ['19900101'] * 600, 'delist_date': [''] * 600})
            with sqlite3.connect(db) as conn:
                late.to_sql('daily', conn, index=False)
                stocks.to_sql('stock_basic', conn, index=False)
            entry = archive_day(archive, '20200102', early)
            manifest = {'codes': early.ts_code.tolist(), 'files': {'20200102': entry},
                        'expected_sessions': ['20200102', '20200103'], 'calendar_source': 'fixture'}
            (archive / 'manifest.json').write_text(json.dumps(manifest))
            loaded = load_market(db, '20200103')
            direct = prepare_market(pd.concat([early, late], ignore_index=True), stocks)
            self.assertEqual(loaded.dates, direct.dates)
            for key in direct.features:
                np.testing.assert_allclose(loaded.features[key], direct.features[key], equal_nan=True)
            for key in direct.values:
                np.testing.assert_allclose(loaded.values[key], direct.values[key], equal_nan=True)
            self.assertEqual(loaded.data_audit['row_count'], 1200)
            self.assertEqual(loaded.data_audit['calendar_missing_sessions'], [])
            self.assertEqual(load_market(db, '20200102').data_audit['row_count'], 600)
            with (archive / entry['path']).open('ab') as file:
                file.write(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                load_market(db, '20200103')


if __name__ == '__main__':
    unittest.main()
