import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from export_web_data import build_concept_payload, combine_files, is_stock_limit_up


class CombineWebDataTests(unittest.TestCase):
    def test_predictions_annotate_signals_and_keep_unmatched_picks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            signal_path = root / "signals" / "b1_20260609.csv"
            prediction_path = root / "predictions" / "next_day_20260609.csv"
            signal_path.parent.mkdir()
            prediction_path.parent.mkdir()

            pd.DataFrame(
                [
                    {"ts_code": "000001.SZ", "name": "平安银行", "close": 10.0},
                    {"ts_code": "000002.SZ", "name": "万科A", "close": 8.0},
                ]
            ).to_csv(signal_path, index=False)
            pd.DataFrame(
                [
                    {
                        "ts_code": "000002.SZ",
                        "name": "万科A",
                        "prob_up": 0.68,
                        "reasons": "短期动量",
                        "next_trade_date": "20260610",
                    },
                    {
                        "ts_code": "000003.SZ",
                        "name": "国华网安",
                        "prob_up": 0.61,
                        "reasons": "相对强度",
                        "next_trade_date": "20260610",
                    },
                ]
            ).to_csv(prediction_path, index=False)

            combined = combine_files([signal_path, prediction_path])

        self.assertEqual(list(combined["ts_code"]), ["000002.SZ", "000003.SZ", "000001.SZ"])
        predicted = combined.set_index("ts_code")
        self.assertAlmostEqual(float(predicted.loc["000002.SZ", "prob_up"]), 0.68)
        self.assertEqual(predicted.loc["000002.SZ", "prediction_rank"], 1)
        self.assertEqual(predicted.loc["000003.SZ", "prediction_rank"], 2)
        self.assertTrue(pd.isna(predicted.loc["000001.SZ", "prob_up"]))
        self.assertEqual(len(combined), 3)

    def test_prediction_file_without_b1_signal_file_exports_predictions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prediction_path = Path(temp_dir) / "predictions" / "next_day_20260609.csv"
            prediction_path.parent.mkdir()
            pd.DataFrame([
                {"ts_code": "920510.BJ", "prob_up": 0.72},
            ]).to_csv(prediction_path, index=False)

            combined = combine_files([prediction_path])

        self.assertEqual(len(combined), 1)
        self.assertEqual(combined.loc[0, "ts_code"], "920510.BJ")
        self.assertEqual(combined.loc[0, "prediction_rank"], 1)
        self.assertAlmostEqual(float(combined.loc[0, "prob_up"]), 0.72)

    def test_predictions_match_signal_rows_across_code_formats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            signal_path = root / "signals" / "b1_20260609.csv"
            prediction_path = root / "predictions" / "next_day_20260609.csv"
            signal_path.parent.mkdir()
            prediction_path.parent.mkdir()

            pd.DataFrame(
                [{"stock_code": "000002", "name": "万科A", "close": 8.0}]
            ).to_csv(signal_path, index=False)
            pd.DataFrame(
                [{"ts_code": "000002.SZ", "prob_up": 0.68, "reasons": "短期动量"}]
            ).to_csv(prediction_path, index=False)

            combined = combine_files([signal_path, prediction_path])

        self.assertEqual(len(combined), 1)
        self.assertEqual(combined.loc[0, "stock_code"], "000002")
        self.assertAlmostEqual(float(combined.loc[0, "prob_up"]), 0.68)
        self.assertEqual(combined.loc[0, "prediction_rank"], 1)

    def test_regular_csvs_still_concatenate_without_prediction_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "signals" / "b1_20260609.csv"
            second = root / "signals" / "b2_20260609.csv"
            first.parent.mkdir()
            pd.DataFrame([{"ts_code": "000001.SZ"}]).to_csv(first, index=False)
            pd.DataFrame([{"ts_code": "000002.SZ"}]).to_csv(second, index=False)

            combined = combine_files([first, second])

        self.assertEqual(len(combined), 2)
        self.assertNotIn("prob_up", combined.columns)
        self.assertIn("source_file", combined.columns)


class ConceptLimitUpTests(unittest.TestCase):
    def test_limit_up_uses_each_markets_price_limit(self):
        cases = [
            ("600000.SH", "浦发银行", "20260817", 10, 11, True),
            ("300001.SZ", "特锐德", "20260817", 10, 12, True),
            ("688001.SH", "华兴源创", "20260817", 10, 12, True),
            ("920001.BJ", "纬达光电", "20260817", 10, 13, True),
            ("600000.SH", "浦发银行", "20260817", 10, 10.99, False),
        ]

        for ts_code, name, date, pre_close, close, expected in cases:
            with self.subTest(ts_code=ts_code, close=close):
                self.assertEqual(
                    is_stock_limit_up(ts_code, name, date, pre_close, close),
                    expected,
                )

    def test_main_board_st_limit_changed_from_five_to_ten_percent(self):
        self.assertTrue(is_stock_limit_up("600001.SH", "*ST示例", "20260703", 10, 10.5))
        self.assertTrue(is_stock_limit_up("600001.SH", "*ST示例", "20260706", 10, 11))
        self.assertFalse(is_stock_limit_up("600001.SH", "*ST示例", "20260706", 10, 10.5))

    def test_concept_payload_includes_limit_up_count(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE concept_ranking_history (
                trade_date TEXT, concept_code TEXT, concept_name TEXT, index_code TEXT,
                rank INTEGER, pct_chg REAL, net_inflow_billion REAL,
                breadth_pct REAL, source TEXT
            );
            CREATE TABLE concept_member_history (
                trade_date TEXT, concept_code TEXT, ts_code TEXT,
                stock_name TEXT, member_rank INTEGER
            );
            CREATE TABLE stock_basic (
                ts_code TEXT, name TEXT, industry TEXT
            );
            CREATE TABLE daily (
                ts_code TEXT, trade_date TEXT, pre_close REAL, close REAL,
                pct_chg REAL, amount REAL
            );
            INSERT INTO concept_ranking_history VALUES
                ('20260817', 'C1', '测试概念', 'I1', 1, 5.2, 2.1, 80, '测试');
            INSERT INTO concept_member_history VALUES
                ('20260817', 'C1', '600001.SH', '主板涨停', 1),
                ('20260817', 'C1', '300001.SZ', '创业板涨停', 2),
                ('20260817', 'C1', '688001.SH', '未涨停', 3);
            INSERT INTO stock_basic VALUES
                ('600001.SH', '主板涨停', '银行'),
                ('300001.SZ', '创业板涨停', '软件'),
                ('688001.SH', '未涨停', '电子');
            INSERT INTO daily VALUES
                ('600001.SH', '20260817', 10, 11, 10, 100),
                ('300001.SZ', '20260817', 10, 12, 20, 200),
                ('688001.SH', '20260817', 10, 11.99, 19.9, 300);
            """
        )

        payload = build_concept_payload(conn, "20260817")

        self.assertIsNotNone(payload)
        self.assertEqual(payload["concepts"][0]["limit_up_count"], 2)
        conn.close()

    def test_concept_payload_uses_none_when_member_prices_are_unavailable(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE concept_ranking_history (
                trade_date TEXT, concept_code TEXT, concept_name TEXT, index_code TEXT,
                rank INTEGER, pct_chg REAL, net_inflow_billion REAL,
                breadth_pct REAL, source TEXT
            );
            CREATE TABLE concept_member_history (
                trade_date TEXT, concept_code TEXT, ts_code TEXT,
                stock_name TEXT, member_rank INTEGER
            );
            CREATE TABLE stock_basic (ts_code TEXT, name TEXT, industry TEXT);
            CREATE TABLE daily (
                ts_code TEXT, trade_date TEXT, pre_close REAL, close REAL,
                pct_chg REAL, amount REAL
            );
            INSERT INTO concept_ranking_history VALUES
                ('20260813', 'C1', '缺少成分数据', 'I1', 1, 1, 1, 50, '测试');
            """
        )

        payload = build_concept_payload(conn, "20260813")

        self.assertIsNotNone(payload)
        self.assertIsNone(payload["concepts"][0]["limit_up_count"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
