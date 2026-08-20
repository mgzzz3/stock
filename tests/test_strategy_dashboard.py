import unittest

import pandas as pd

from strategy import r1_reversal
from strategy.dashboard import (
    WALK_FORWARD_GATES,
    _curve_from_aggregates,
    _credibility_payload,
    _event_metrics,
    _golden_recommendations,
    _historical_cases,
    _walk_forward_selection,
)


class StrategyDashboardTests(unittest.TestCase):
    def test_b1_status_is_not_force_disabled(self):
        self.assertNotIn("force_disabled", WALK_FORWARD_GATES["b1_pullback"])

    def test_curve_uses_equal_weight_daily_returns_and_tracks_drawdown(self):
        aggregate = pd.DataFrame(
            {
                "return_sum": [0.20, -0.20, 0.10],
                "position_count": [2, 2, 2],
            },
            index=["20260105", "20260106", "20260107"],
        )

        curve = _curve_from_aggregates([aggregate])

        self.assertEqual(len(curve["points"]), 3)
        self.assertAlmostEqual(curve["points"][0]["nav"], 1.1)
        self.assertAlmostEqual(curve["points"][1]["nav"], 0.99)
        self.assertAlmostEqual(curve["max_drawdown_pct"], -10.0)

    def test_historical_cases_include_recent_wins_losses_and_oos_scope(self):
        frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
                "trade_date": ["20260102", "20260105", "20260106"],
                "entry_index": [1, 2, 3],
                "actual_ret": [0.03, -0.01, 0.01],
                "trend_short": [9.0, 9.2, 9.4],
                "bull_bear": [10.0, 10.0, 10.0],
                "stop_t2": [False, True, False],
                "stop_t3": [False, False, True],
            }
        )
        signal = pd.Series(True, index=frame.index)
        oos = pd.Series([True, False, False], index=frame.index)
        exit_index = pd.Series([2, 3, 4], index=frame.index)
        lookup = pd.DataFrame(
            {
                "ts_code": frame["ts_code"],
                "name": ["股票一", "股票二", "股票三"],
                "industry": ["银行", "软件", "机械"],
            }
        )

        cases = _historical_cases(
            frame,
            signal,
            oos,
            "actual_ret",
            exit_index,
            "20260101",
            lookup,
            {1: "20260105", 2: "20260106", 3: "20260107", 4: "20260108"},
            "b2_reversion",
        )

        self.assertEqual(cases["completed_count"], 3)
        self.assertEqual(cases["win_count"], 2)
        self.assertEqual(cases["loss_count"], 1)
        self.assertEqual(cases["wins"][-1]["evidence_label"], "滚动样本外")
        self.assertEqual(cases["losses"][0]["exit_reason"], "第2日开盘触发止损")

    def test_credibility_counts_stocks_dates_and_oos_completed_trades(self):
        frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000001.SZ", "000002.SZ"],
                "trade_date": ["20260102", "20260105", "20260105"],
                "ret": [0.01, 0.02, float("nan")],
            }
        )
        signal = pd.Series(True, index=frame.index)
        oos = pd.Series([True, False, True], index=frame.index)
        walk_forward = {"metrics": {"enabled_windows": 2, "total_windows": 5}}

        credibility = _credibility_payload(
            frame,
            signal,
            oos,
            "ret",
            "20260101",
            "20261231",
            walk_forward,
        )

        self.assertEqual(credibility["completed_trade_count"], 2)
        self.assertEqual(credibility["unique_stock_count"], 1)
        self.assertEqual(credibility["signal_date_count"], 2)
        self.assertEqual(credibility["oos_completed_trade_count"], 1)
        self.assertEqual(credibility["evidence_level"], "rolling_oos")

    def test_curve_treats_starting_cash_as_the_initial_peak(self):
        aggregate = pd.DataFrame(
            {"return_sum": [-0.10], "position_count": [1]},
            index=["20260105"],
        )

        curve = _curve_from_aggregates([aggregate])

        self.assertAlmostEqual(curve["latest_nav"], 0.9)
        self.assertAlmostEqual(curve["max_drawdown_pct"], -10.0)

    def test_event_metrics_deduct_round_trip_cost(self):
        signals = pd.DataFrame(
            {
                "trade_date": ["20260105", "20260106"],
                "ret": [0.01, 0.03],
            }
        )
        baseline = pd.DataFrame(
            {
                "trade_date": ["20260105", "20260106"],
                "ret": [0.005, 0.015],
            }
        )

        metrics = _event_metrics(
            signals,
            baseline,
            "ret",
            {"max_drawdown_pct": -4.0, "latest_nav": 1.2},
            "20260101",
            "20260131",
        )

        self.assertEqual(metrics["mean_return_pct"], 2.0)
        self.assertEqual(metrics["net_mean_return_pct"], 1.8)
        self.assertEqual(metrics["excess_return_pct"], 1.0)

    def test_golden_recommendations_filter_st_and_prefer_mainline_industry(self):
        current = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "close": 10.4,
                    "ma20": 10.1,
                    "ma60": 10.0,
                    "amount": 500_000,
                    "pct_chg": 2.0,
                },
                {
                    "ts_code": "000002.SZ",
                    "close": 10.2,
                    "ma20": 10.1,
                    "ma60": 10.0,
                    "amount": 900_000,
                    "pct_chg": 1.0,
                },
                {
                    "ts_code": "000003.SZ",
                    "close": 10.1,
                    "ma20": 10.05,
                    "ma60": 10.0,
                    "amount": 900_000,
                    "pct_chg": 1.0,
                },
            ]
        )
        lookup = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "主线股票", "industry": "黄金"},
                {"ts_code": "000002.SZ", "name": "普通股票", "industry": "软件"},
                {"ts_code": "000003.SZ", "name": "ST风险", "industry": "黄金"},
            ]
        )

        rows = _golden_recommendations(
            current,
            lookup,
            {"黄金": {"score": 0.8, "rank": 1}},
        )

        self.assertEqual(rows[0]["ts_code"], "000001.SZ")
        self.assertNotIn("000003.SZ", {row["ts_code"] for row in rows})
        self.assertIn("行业主线排名第 1", rows[0]["reasons"])

    def test_walk_forward_embargo_excludes_trades_finishing_on_test_start(self):
        rows = []
        dates = pd.bdate_range("2026-01-02", periods=12).strftime("%Y%m%d")
        for stock in ("000001.SZ", "000002.SZ"):
            for trade_index, date in enumerate(dates):
                rows.append(
                    {
                        "ts_code": stock,
                        "trade_date": date,
                        "trade_index": trade_index,
                        "ret": 0.02,
                        "exit_index": trade_index + 1 if trade_index < 11 else float("nan"),
                    }
                )
        frame = pd.DataFrame(rows)
        signal = pd.Series(True, index=frame.index)
        gate = {
            "min_signal_count": 1,
            "min_net_mean": 0,
            "min_excess": 0,
            "min_win_rate": 0.5,
        }

        selected, result = _walk_forward_selection(
            frame,
            signal,
            "ret",
            frame["exit_index"],
            str(dates[0]),
            gate,
            training_days=5,
            test_days=3,
        )

        first = result["windows"][0]
        # Four eligible signal dates × two stocks.  Signals at index 4 exit at
        # index 5, exactly when testing starts, so the strict embargo drops them.
        self.assertEqual(first["training_signal_count"], 8)
        self.assertTrue(first["approved"])
        self.assertTrue(selected[frame["trade_index"].between(5, 7)].all())

    def test_future_test_returns_cannot_change_first_window_approval(self):
        dates = pd.bdate_range("2026-01-02", periods=10).strftime("%Y%m%d")
        frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 10,
                "trade_date": dates,
                "trade_index": range(10),
                "ret": [0.02] * 10,
                "exit_index": [*range(1, 10), float("nan")],
            }
        )
        gate = {
            "min_signal_count": 1,
            "min_net_mean": 0,
            "min_excess": 0,
            "min_win_rate": 0.5,
        }
        signal = pd.Series(True, index=frame.index)
        _, original = _walk_forward_selection(
            frame, signal, "ret", frame["exit_index"], str(dates[0]), gate,
            training_days=5, test_days=3,
        )

        changed = frame.copy()
        changed.loc[changed["trade_index"] >= 5, "ret"] = -0.9
        _, mutated = _walk_forward_selection(
            changed, signal, "ret", changed["exit_index"], str(dates[0]), gate,
            training_days=5, test_days=3,
        )

        self.assertEqual(original["windows"][0], mutated["windows"][0])

    def test_r1_features_do_not_change_when_future_prices_are_mutated(self):
        dates = pd.bdate_range("2025-09-01", periods=90).strftime("%Y%m%d")
        rows = []
        for stock_offset, stock in enumerate(("000001.SZ", "000002.SZ")):
            for offset, date in enumerate(dates):
                rows.append(
                    {
                        "ts_code": stock,
                        "trade_date": date,
                        "open": 10 + stock_offset + offset * 0.03,
                        "close": 10 + stock_offset + offset * 0.03,
                        "amount": 200_000 + offset,
                        "pct_chg": 0.3,
                    }
                )
        frame = pd.DataFrame(rows)
        original = r1_reversal.add_features(frame)

        changed = frame.copy()
        future = changed["trade_date"] > dates[74]
        changed.loc[future, "close"] *= 5
        changed.loc[future, "amount"] *= 10
        mutated = r1_reversal.add_features(changed)

        historical = original["trade_date"] <= dates[74]
        columns = [
            "r1_formation_return",
            "r1_market_return_20",
            "r1_amount_20",
            "r1_market_median_20",
        ]
        pd.testing.assert_frame_equal(
            original.loc[historical, columns],
            mutated.loc[historical, columns],
        )

    def test_r1_adjusted_index_ignores_false_ex_right_price_drop(self):
        dates = pd.bdate_range("2025-09-01", periods=70).strftime("%Y%m%d")
        close = [10.0] * 40 + [5.0] * 30
        frame = pd.DataFrame(
            {
                "ts_code": ["000001.SZ"] * 70,
                "trade_date": dates,
                "open": close,
                "close": close,
                "amount": [200_000] * 70,
                # A zero pct_chg on the halving date models an ex-right move:
                # adjusted shareholder wealth did not lose 50%.
                "pct_chg": [0.0] * 70,
            }
        )

        featured = r1_reversal.add_features(frame)

        self.assertAlmostEqual(float(featured.iloc[-1]["r1_formation_return"]), 0.0)

    def test_r1_uses_only_completed_months_and_enforces_market_gate(self):
        rows = []
        for date, market_return in (
            ("20260130", 0.04),
            ("20260227", -0.03),
            ("20260313", 0.08),
        ):
            for offset in range(10):
                rows.append(
                    {
                        "ts_code": f"{offset:06d}.SZ",
                        "trade_date": date,
                        "close": 10.0,
                        "r1_amount_20": 200_000 + offset,
                        "r1_formation_return": -0.20 + offset * 0.01,
                        "r1_market_median_20": market_return,
                    }
                )
        frame = pd.DataFrame(rows)

        signal, observations, context = r1_reversal.select_signals(
            frame,
            "20260313",
        )

        self.assertEqual(context["latest_signal_date"], "20260227")
        self.assertFalse(context["market_regime_open"])
        self.assertEqual(len(observations), 1)
        self.assertEqual(str(observations.iloc[0]["trade_date"]), "20260227")
        self.assertFalse(signal[frame["trade_date"] == "20260227"].any())
        self.assertFalse(signal[frame["trade_date"] == "20260313"].any())


if __name__ == "__main__":
    unittest.main()
