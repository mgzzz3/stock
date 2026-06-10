import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from strategy.next_day import (
    FEATURES,
    build_dataset,
    fit_model,
    load_b1_pool,
    prediction_table,
    score_rows,
    train_and_score,
)


class NextDayTests(unittest.TestCase):
    def make_bars(self, stocks=12, days=70):
        rng = np.random.default_rng(7)
        dates = pd.bdate_range("2025-01-02", periods=days).strftime("%Y%m%d")
        rows = []
        for stock in range(stocks):
            close = 10.0 + stock
            for index, date in enumerate(dates):
                previous = close
                overnight = rng.normal(0, 0.004)
                open_price = previous * (1 + overnight)
                # A deterministic, learnable relation based only on yesterday's move.
                drift = (0.012 if index > 0 and rows[-1]["close"] > rows[-1]["pre_close"] else -0.008)
                close = open_price * (1 + drift + rng.normal(0, 0.003))
                high = max(open_price, close) * 1.005
                low = min(open_price, close) * 0.995
                rows.append({
                    "ts_code": f"{stock:06d}.SZ", "trade_date": date,
                    "open": open_price, "high": high, "low": low, "close": close,
                    "pre_close": previous, "vol": 100_000 + index * 100,
                    "amount": 100_000, "name": f"股票{stock}", "industry": "测试",
                })
        return pd.DataFrame(rows)

    def test_features_and_target_use_next_intraday_return(self):
        bars = self.make_bars(stocks=1, days=30)
        dataset = build_dataset(bars)
        row = dataset.iloc[-2]
        next_bar = bars.iloc[-1]
        expected = next_bar["close"] / next_bar["open"] - 1
        self.assertAlmostEqual(row["next_ret"], expected)
        self.assertEqual(row["target"], float(expected > 0))
        self.assertTrue(pd.isna(dataset.iloc[-1]["target"]))

    def test_training_excludes_signal_date_label(self):
        dataset = build_dataset(self.make_bars())
        signal_date = sorted(dataset["trade_date"].unique())[-1]
        model, scored = train_and_score(dataset, signal_date, min_training_rows=100)
        self.assertLess(model.training_end, signal_date)
        self.assertEqual(set(scored["trade_date"]), {signal_date})
        self.assertTrue(scored["prob_up"].between(0, 1).all())

    def test_future_price_changes_do_not_change_historical_prediction(self):
        bars = self.make_bars()
        dataset = build_dataset(bars)
        dates = sorted(dataset["trade_date"].unique())
        signal_date = dates[-5]
        model, scored = train_and_score(dataset, signal_date, min_training_rows=100)

        changed = bars.copy()
        future = changed["trade_date"] > signal_date
        changed.loc[future, ["open", "high", "low", "close"]] *= 10
        changed_dataset = build_dataset(changed)
        changed_model, changed_scored = train_and_score(
            changed_dataset, signal_date, min_training_rows=100
        )

        self.assertTrue(np.allclose(model.weights, changed_model.weights))
        self.assertTrue(np.allclose(scored["prob_up"], changed_scored["prob_up"]))

    def test_load_b1_pool_uses_daily_csv_instead_of_database_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            signal_dir = Path(temp_dir)
            pd.DataFrame({
                "ts_code": ["000002.SZ", "000007.SZ"],
                "name": ["万科A", "全新好"],
            }).to_csv(signal_dir / "b1_20260609.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame({
                "ts_code": ["920510.BJ"],
            }).to_csv(signal_dir / "b1_20260610.csv", index=False)

            pool = load_b1_pool("20260609", "20260609", signal_dir=signal_dir)

        self.assertEqual(set(pool["ts_code"]), {"000002.SZ", "000007.SZ"})
        self.assertEqual(set(pool["trade_date"]), {"20260609"})
        self.assertNotIn("920510.BJ", set(pool["ts_code"]))

    def test_prediction_table_only_scores_b1_pool_members(self):
        dataset = build_dataset(self.make_bars())
        signal_date = str(dataset["trade_date"].max())
        b1_codes = ["000002.SZ", "000007.SZ"]
        b1_pool = pd.DataFrame({
            "ts_code": b1_codes,
            "trade_date": [signal_date, signal_date],
        })

        _, picks = prediction_table(
            dataset,
            b1_pool,
            signal_date,
            top=0,
            train_days=50,
            min_training_rows=100,
            min_amount=0,
        )

        self.assertEqual(set(picks["ts_code"]), set(b1_codes))
        self.assertEqual(set(picks["prediction_pool"]), {"b1"})

    def test_prediction_table_requires_persisted_b1_pool(self):
        dataset = build_dataset(self.make_bars())
        signal_date = str(dataset["trade_date"].max())
        empty_pool = pd.DataFrame(columns=["ts_code", "trade_date"])

        with self.assertRaisesRegex(ValueError, "strategy.b1"):
            prediction_table(
                dataset,
                empty_pool,
                signal_date,
                train_days=50,
                min_training_rows=100,
                min_amount=0,
            )

    def test_positive_feature_contribution_increases_probability(self):
        rows = pd.DataFrame({feature: np.linspace(-1, 1, 200) for feature in FEATURES})
        rows["target"] = (rows[FEATURES[0]] > 0).astype(float)
        rows["trade_date"] = pd.bdate_range("2025-01-01", periods=200).strftime("%Y%m%d")
        model = fit_model(rows, iterations=500)
        scored = score_rows(model, rows.iloc[[10, 190]])
        self.assertLess(scored.iloc[0]["prob_up"], scored.iloc[1]["prob_up"])
        self.assertIn("上涨概率", scored.iloc[1]["reasons"])


if __name__ == "__main__":
    unittest.main()
