import tempfile
import unittest
from pathlib import Path

import pandas as pd

from export_web_data import combine_files


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


if __name__ == "__main__":
    unittest.main()
