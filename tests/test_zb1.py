import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from strategy.zb1 import build_strategy, exit_fill, load_rankings, simulate


def bar(date, code="A", opening=100, high=100, low=100, close=100, **extra):
    return {"trade_date": date, "ts_code": code, "open": opening,
            "high": high, "low": low, "close": close, "vol": 100, **extra}


def candidates(date, codes):
    return [{"trade_date": date, "ts_code": code, "prediction_rank": rank}
            for rank, code in enumerate(codes, 1)]


def adjusted(opening=100, high=100, low=100):
    return {"adj_open": opening, "adj_high": high, "adj_low": low}


class ZB1Tests(unittest.TestCase):
    def industry_rankings(self, pool_rows, prediction_codes, date="20260701"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "signals").mkdir()
            (root / "predictions").mkdir()
            pd.DataFrame(pool_rows).to_csv(root / "signals" / f"b1_{date}.csv", index=False)
            pd.DataFrame({"ts_code": prediction_codes, "trade_date": [date] * len(prediction_codes),
                          "prob_up": [0.8] * len(prediction_codes),
                          "industry": ["预测文件旧行业"] * len(prediction_codes)}).to_csv(
                              root / "predictions" / f"next_day_{date}.csv", index=False)
            return load_rankings(root, date)[date]

    def test_largest_industry_count_uses_full_pool_not_prediction_subset(self):
        pool = [{"ts_code": code, "industry": "软件"} for code in "ABCD"]
        pool += [{"ts_code": code, "industry": "银行"} for code in "EFG"]
        pool += [{"ts_code": "E", "industry": "银行"}] * 5
        rows = self.industry_rankings(pool, ["E", "F", "G", "C", "A"])
        self.assertEqual([r["ts_code"] for r in rows], ["C", "A"])
        self.assertEqual([r["prediction_rank"] for r in rows], [4, 5])
        self.assertTrue(all(r["industry"] == "软件" and r["b1_industry_count"] == 4 for r in rows))
        # Only two predictions in the largest industry: no smaller-industry fill.
        dates = ["20260701", "20260702"]
        result = simulate(pd.DataFrame([bar(d, c) for d in dates for c in "ACEFG"]),
                          {dates[0]: rows}, dates)
        self.assertEqual({p["ts_code"] for p in result["holdings"]}, {"A", "C"})
        self.assertAlmostEqual(result["cash"], 1 / 3)

    def test_tied_largest_industries_merge_then_take_prediction_top_three(self):
        pool = [{"ts_code": c, "industry": "软件" if c in "ABC" else "银行"} for c in "ABCDEF"]
        pool += [{"ts_code": "G", "industry": "白酒"}]
        rows = self.industry_rankings(pool, ["G", "E", "B", "F", "A", "C", "D"])
        dates = ["20260701", "20260702"]
        result = simulate(pd.DataFrame([bar(d, c) for d in dates for c in "ABCDEFG"]), {dates[0]: rows}, dates)
        self.assertEqual([p["ts_code"] for p in result["holdings"]], ["E", "B", "F"])

    def test_largest_industry_without_predictions_does_not_fall_back(self):
        pool = [{"ts_code": c, "industry": "软件"} for c in "ABC"]
        pool += [{"ts_code": "D", "industry": "银行"}]
        self.assertEqual(self.industry_rankings(pool, ["D"]), [])

    def test_missing_industries_do_not_become_largest_industry(self):
        pool = [{"ts_code": "A", "industry": "软件"}]
        pool += [{"ts_code": c, "industry": None} for c in "BCD"]
        rows = self.industry_rankings(pool, ["B", "C", "D", "A"])
        self.assertEqual([r["ts_code"] for r in rows], ["A"])
        self.assertEqual(self.industry_rankings([{"ts_code": "A"}], ["A"]), [])

    def test_industry_selection_counts_held_stocks_before_skipping_them(self):
        dates = ["20260701", "20260702", "20260703"]
        pool = [{"ts_code": c, "industry": "软件" if c in "ABC" else "银行"} for c in "ABCDE"]
        rows = self.industry_rankings(pool, ["D", "E", "A", "B", "C"], dates[1])
        ranks = {dates[0]: candidates(dates[0], "A"), dates[1]: rows}
        result = simulate(pd.DataFrame([bar(d, c) for d in dates for c in "ABCDE"]), ranks, dates)
        self.assertEqual([p["ts_code"] for p in result["holdings"]], ["A", "B", "C"])
        self.assertEqual(result["trades"], [])

    def test_exactly_fifteen_does_not_activate(self):
        position = {"entry_adjusted": 100, "profit_armed": False}
        self.assertIsNone(exit_fill(position, adjusted(110, 115, 109), can_sell=True))
        self.assertFalse(position["profit_armed"])

    def test_armed_is_retained_until_ten_percent_exit(self):
        position = {"entry_adjusted": 100, "profit_armed": False}
        self.assertIsNone(exit_fill(position, adjusted(116, 120, 112), can_sell=True))
        self.assertTrue(position["profit_armed"])
        self.assertIsNone(exit_fill(position, adjusted(114, 114, 111), can_sell=True))
        price, reason = exit_fill(position, adjusted(113, 113, 110), can_sell=True)
        self.assertAlmostEqual(price, 110)
        self.assertIn("回撤", reason)

    def test_stop_boundary_and_gap_use_executable_price(self):
        for opening, low, expected in [(100, 95, 95), (92, 90, 92)]:
            with self.subTest(opening=opening):
                p = {"entry_adjusted": 100, "profit_armed": False}
                fill = exit_fill(p, adjusted(opening, 100, low), can_sell=True)
                self.assertAlmostEqual(fill[0], expected)
                self.assertIn("止损", fill[1])

    def test_armed_gap_below_ten_sells_at_open_not_threshold(self):
        p = {"entry_adjusted": 100, "profit_armed": True}
        self.assertEqual(exit_fill(p, adjusted(105, 108, 104), can_sell=True)[0], 105)

    def test_ambiguous_bar_uses_stop_before_activation(self):
        p = {"entry_adjusted": 100, "profit_armed": False}
        self.assertEqual(exit_fill(p, adjusted(100, 120, 94), can_sell=True)[0], 95)
        p = {"entry_adjusted": 100, "profit_armed": False}
        self.assertAlmostEqual(exit_fill(p, adjusted(111, 120, 105), can_sell=True)[0], 110)

    def test_buy_day_can_arm_but_cannot_sell(self):
        p = {"entry_adjusted": 100, "profit_armed": False}
        self.assertIsNone(exit_fill(p, adjusted(100, 120, 90), can_sell=False))
        self.assertTrue(p["profit_armed"])
        self.assertEqual(exit_fill(p, adjusted(105, 110, 100), can_sell=True)[0], 105)

    def test_top_three_next_session_and_no_rotation_or_expiry(self):
        dates = [f"202607{i:02d}" for i in range(1, 29)]
        bars = pd.DataFrame([bar(date, code) for date in dates for code in "ABCD"])
        rankings = {date: candidates(date, "ABCD" if date == dates[0] else "DCBA") for date in dates}
        result = simulate(bars, rankings, dates)
        self.assertEqual(result["curve"][0]["position_count"], 0)
        self.assertEqual({p["ts_code"] for p in result["holdings"]}, set("ABC"))
        self.assertTrue(all(p["entry_date"] == dates[1] for p in result["holdings"]))
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["pending_buys"], [])
        self.assertAlmostEqual(result["curve"][-1]["nav"], 1 / 1.001, places=6)

    def test_sell_then_next_session_refill_skips_held_codes(self):
        dates = ["20260701", "20260702", "20260703", "20260706"]
        rows = [bar(date, code) for date in dates for code in "ABCD"]
        rows = [bar(r["trade_date"], "A", low=95) if r["trade_date"] == dates[2] and r["ts_code"] == "A" else r for r in rows]
        ranks = {dates[0]: candidates(dates[0], "ABCD"), dates[2]: candidates(dates[2], "BCDA")}
        result = simulate(pd.DataFrame(rows), ranks, dates)
        self.assertEqual([p["position_count"] for p in result["curve"]], [0, 3, 2, 3])
        self.assertEqual(result["trades"][0]["exit_date"], dates[2])
        new = next(p for p in result["holdings"] if p["ts_code"] == "D")
        self.assertEqual(new["signal_date"], dates[2])
        self.assertEqual(new["entry_date"], dates[3])
        self.assertTrue(all(p["cash"] >= -1e-8 for p in result["curve"]))

    def test_missing_bar_does_not_delay_buy_order_or_liquidate_holding(self):
        dates = ["20260701", "20260702", "20260703", "20260706"]
        rows = [bar(dates[0], "A"), bar(dates[1], "A"), bar(dates[3], "A"), bar(dates[2], "B")]
        result = simulate(pd.DataFrame(rows), {dates[0]: candidates(dates[0], "AB")}, dates)
        self.assertEqual(len(result["holdings"]), 1)
        self.assertEqual(result["holdings"][0]["ts_code"], "A")
        self.assertEqual([p["position_count"] for p in result["curve"]], [0, 1, 1, 1])

    def test_split_does_not_cause_false_stop(self):
        dates = ["20260701", "20260702", "20260703"]
        bars = pd.DataFrame([bar(dates[0], pct_chg=0), bar(dates[1], pct_chg=0),
                             bar(dates[2], opening=50, high=50, low=50, close=50, pct_chg=0)])
        result = simulate(bars, {dates[0]: candidates(dates[0], "A")}, dates)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["holdings"][0]["holding_return_pct"], 0)
        self.assertAlmostEqual(result["holdings"][0]["stop_price"], 47.5)

    def test_no_future_rankings_and_unfilled_slots_remain_cash(self):
        dates = ["20260701", "20260702"]
        result = simulate(pd.DataFrame([bar(d) for d in dates]), {dates[1]: candidates(dates[1], "A")}, dates)
        self.assertEqual(result["holdings"], [])
        self.assertEqual(len(result["pending_buys"]), 1)
        self.assertEqual(result["cash"], 1)

    def test_future_bars_and_predictions_do_not_change_past_curve(self):
        dates = ["20260701", "20260702", "20260703", "20260706"]
        bars = pd.DataFrame([bar(date, code) for date in dates for code in "ABCD"])
        ranks = {date: candidates(date, "ABCD") for date in dates}
        before = simulate(bars, ranks, dates)
        bars.loc[bars["trade_date"].eq(dates[-1]), ["open", "high", "low", "close"]] = 50
        ranks[dates[-1]] = candidates(dates[-1], "DCBA")
        after = simulate(bars, ranks, dates)
        self.assertEqual(before["curve"][:-1], after["curve"][:-1])

    def test_entry_uses_next_open_and_zero_volume_is_not_tradable(self):
        dates = ["20260701", "20260702", "20260703"]
        bars = pd.DataFrame([bar(dates[0]), bar(dates[1], opening=110, high=110, low=110, close=110),
                             bar(dates[2], opening=50, high=50, low=50, close=50, vol=0)])
        result = simulate(bars, {dates[0]: candidates(dates[0], "A")}, dates)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["holdings"][0]["entry_price"], 110)
        self.assertEqual(result["holdings"][0]["holding_return_pct"], 0)
        self.assertEqual(result["holdings"][0]["price_date"], dates[1])

    def test_loader_uses_saved_order_final_pool_and_date_cutoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "signals").mkdir()
            (root / "predictions").mkdir()
            for date in ["20260701", "20260702"]:
                pd.DataFrame({"ts_code": ["A", "B", "C"], "industry": ["软件"] * 3}).to_csv(root / "signals" / f"b1_{date}.csv", index=False)
                pd.DataFrame({"ts_code": ["D", "B", "A", "B", "C"], "trade_date": [date] * 5,
                              "prob_up": [0.99, 0.8, 0.9, 0.8, None]}).to_csv(root / "predictions" / f"next_day_{date}.csv", index=False)
            rankings = load_rankings(root, "20260701")
            self.assertEqual(list(rankings), ["20260701"])
            self.assertEqual([p["ts_code"] for p in rankings["20260701"]], ["B", "A"])
            self.assertEqual([p["prediction_rank"] for p in rankings["20260701"]], [2, 3])

    def test_empty_archive_has_valid_payload_and_no_buys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stock.db"
            with sqlite3.connect(path) as conn:
                pd.DataFrame([bar("20260701", pct_chg=0)]).to_sql("daily", conn, index=False)
            payload = build_strategy(path, "20260701")
            self.assertEqual(payload["id"], "zb1")
            self.assertEqual(payload["recommendations"], [])
            self.assertEqual(payload["metrics"]["signal_count"], 0)
            json.dumps(payload, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
