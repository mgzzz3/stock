import unittest

import pandas as pd

from strategy import r1_reversal, technical_expansion, value_quality
from strategy.dashboard import _sparse_open_exit_curve


class StrategyExpansionTests(unittest.TestCase):
    def test_sparse_curve_marks_each_holding_day_and_initial_peak(self):
        frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 4,
                "trade_date": ["20260102", "20260105", "20260106", "20260107"],
                "adjusted_open": [100.0, 100.0, 110.0, 108.9],
                "adjusted_close": [100.0, 110.0, 99.0, 108.9],
            }
        )
        signal = pd.Series([True, False, False, False])

        curve = _sparse_open_exit_curve(
            frame,
            signal,
            "20260101",
            2,
            open_column="adjusted_open",
            close_column="adjusted_close",
        )

        self.assertEqual(len(curve["points"]), 3)
        self.assertAlmostEqual(curve["points"][0]["daily_return_pct"], 9.8)
        self.assertAlmostEqual(curve["max_drawdown_pct"], -10.0)

    def test_trend_alignment_fires_only_on_first_qualifying_day(self):
        dates = pd.bdate_range("2025-01-01", periods=170).strftime("%Y%m%d")
        rows = []
        for offset, date in enumerate(dates):
            close = 10 + offset * 0.03
            rows.append(
                {
                    "ts_code": "000001.SZ",
                    "trade_date": date,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "vol": 200_000,
                    "amount": 200_000,
                    "pct_chg": 0.3,
                }
            )
        featured = r1_reversal.add_features(pd.DataFrame(rows))
        featured = technical_expansion.add_features(featured, copy=False)

        self.assertEqual(int(featured["trend_signal"].sum()), 1)

    def test_technical_history_is_unchanged_by_future_mutation(self):
        dates = pd.bdate_range("2025-01-01", periods=170).strftime("%Y%m%d")
        frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 170,
                "trade_date": dates,
                "open": [10 + i * 0.03 for i in range(170)],
                "high": [(10 + i * 0.03) * 1.01 for i in range(170)],
                "low": [(10 + i * 0.03) * 0.99 for i in range(170)],
                "close": [10 + i * 0.03 for i in range(170)],
                "vol": [200_000] * 170,
                "amount": [200_000] * 170,
                "pct_chg": [0.3] * 170,
            }
        )
        original = technical_expansion.add_features(
            r1_reversal.add_features(frame), copy=False
        )
        changed = frame.copy()
        future = changed["trade_date"] > dates[149]
        changed.loc[future, ["open", "high", "low", "close"]] *= 4
        changed.loc[future, "pct_chg"] = -20
        mutated = technical_expansion.add_features(
            r1_reversal.add_features(changed), copy=False
        )

        historical = original["trade_date"] <= dates[149]
        columns = [
            "breakout_previous_high",
            "breakout_signal",
            "trend_ma20",
            "trend_ma60",
            "trend_ma120",
            "trend_signal",
        ]
        pd.testing.assert_frame_equal(
            original.loc[historical, columns],
            mutated.loc[historical, columns],
        )

    def test_value_strategy_requires_three_reports_available_by_signal_date(self):
        reports = []
        for year, announcement in (
            (2021, "20220401"),
            (2022, "20230401"),
            (2023, "20250401"),
        ):
            reports.append(
                {
                    "ts_code": "000001.SZ",
                    "report_date": f"{year}1231",
                    "announcement_date": announcement,
                    "name": "测试公司",
                    "industry": "消费",
                    "revenue_yoy": 10,
                    "net_profit_yoy": 12,
                    "eps": 1,
                    "book_value_per_share": 5,
                    "roe": 20,
                    "ocf_per_share": 1.2,
                    "gross_margin": 40,
                    "debt_to_assets": 30,
                }
            )
        prices = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20240430",
                    "close": 15,
                    "r1_amount_20": 200_000,
                }
            ]
        )
        selected, _, _ = value_quality.score_snapshots(
            pd.DataFrame(reports), prices, "20240510"
        )
        self.assertTrue(selected.empty)

        reports[2]["announcement_date"] = "20240401"
        selected, latest, context = value_quality.score_snapshots(
            pd.DataFrame(reports), prices, "20240510"
        )
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(latest), 1)
        self.assertEqual(context["report_date"], "20231231")
        self.assertEqual(int(selected.iloc[0]["report_count"]), 3)


if __name__ == "__main__":
    unittest.main()
