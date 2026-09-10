import json
import unittest

import numpy as np
import pandas as pd

from strategy import emotion


def market_fixture(days=20, stocks=2):
    dates = pd.bdate_range('2025-01-01', periods=days).strftime('%Y%m%d').tolist()
    shape = (days, stocks)
    return emotion.Market(dates, [f'{i:06d}.SZ' for i in range(stocks)],
        {'adj_open': np.ones(shape), 'adj_close': np.ones(shape),
         'entry_ok': np.ones(shape, bool),
         'next_sell': np.repeat(np.arange(days)[:, None], stocks, axis=1)},
        {'eligible': np.ones(shape, bool)}, pd.DataFrame(), {})


def price_fixture(days=120, stocks=4):
    dates = pd.bdate_range('2025-01-01', periods=days).strftime('%Y%m%d')
    rows = []
    for i in range(stocks):
        close = 10.
        for t, date in enumerate(dates):
            previous = close
            pct = [-2, -1, 1, 2, 0.3, -3, 3][t % 7] + i * .05
            close *= 1 + pct / 100
            rows.append({'ts_code': f'{i:06d}.SZ', 'trade_date': date,
                         'open': previous * 1.001, 'close': close, 'pre_close': previous,
                         'pct_chg': pct, 'vol': 200_000, 'amount': 200_000})
    stocks = pd.DataFrame({'ts_code': [f'{i:06d}.SZ' for i in range(stocks)],
                           'name': ['测试'] * stocks, 'industry': ['测试行业'] * stocks})
    return pd.DataFrame(rows), stocks


class EmotionTests(unittest.TestCase):
    def test_validation_status_retires_a_well_sampled_failed_rule(self):
        self.assertEqual(
            emotion.validation_status(20, False),
            ("retired", "长期样本未通过"),
        )
        self.assertEqual(
            emotion.validation_status(19, False),
            ("watch", "样本外证据不足"),
        )
        self.assertEqual(
            emotion.validation_status(20, True),
            ("watch", "历史初验通过"),
        )

    def test_cash_slots_fees_and_t_plus_one(self):
        m = market_fixture()
        m.values['adj_open'][6, 0] = 1.1
        result = emotion.replay_cohort(m, 0, np.array([0]))
        expected = 1 + (1.1 / 1.001 * .999 - 1) / 10
        self.assertAlmostEqual(result['path'][-1], expected)
        self.assertEqual(result['entry'], 1)
        self.assertEqual(result['end'], 6)
        self.assertLess(result['path'][0], 1)
        self.assertGreater(result['path'][0], .999)

    def test_unavailable_next_open_is_not_filled_later_or_replaced(self):
        m = market_fixture()
        m.values['entry_ok'][1, 0] = False
        result = emotion.replay_cohort(m, 0, np.array([0]))
        self.assertEqual(result['skipped'], 1)
        self.assertEqual(result['trades'], [])
        self.assertEqual(result['path'][-1], 1)

    def test_sell_lock_delays_exit_and_prevents_overlapping_cohorts(self):
        m = market_fixture()
        m.values['next_sell'][6, 0] = 9
        picks = [np.array([0]) for _ in m.dates]
        cohorts, curve = emotion.simulate(m, picks)
        self.assertEqual(cohorts[0]['end'], 9)
        self.assertTrue(cohorts[0]['trades'][0]['delayed'])
        self.assertEqual(cohorts[1]['signal'], 9)
        self.assertLess(curve[1]['drawdown_pct'], 0)

    def test_pending_exit_keeps_marking_and_never_becomes_completed_return(self):
        m = market_fixture()
        m.values['next_sell'][6, 0] = -1
        m.values['adj_close'][:, 0] = np.linspace(1, .8, len(m.dates))
        picks = [np.array([0]) for _ in m.dates]
        cohorts, curve = emotion.simulate(m, picks)
        stats = emotion.evidence(cohorts, curve)
        self.assertEqual(len(cohorts), 1)
        self.assertEqual(stats['cohort_count'], 0)
        self.assertEqual(stats['signal_count'], 0)
        self.assertEqual(stats['pending_trades'], 1)
        self.assertLess(stats['total_return_pct'], 0)

    def test_not_yet_due_exit_is_pending_not_delayed(self):
        m = market_fixture(days=5)
        cohort = emotion.replay_cohort(m, 1, np.array([0]))
        self.assertFalse(cohort['complete'])
        self.assertFalse(cohort['trades'][0]['delayed'])
        self.assertIsNone(cohort['trades'][0]['net'])

    def test_future_prices_and_appended_rows_cannot_rewrite_signals(self):
        frame, stocks = price_fixture()
        cutoff = sorted(frame.trade_date.unique())[99]
        original = emotion.prepare_market(frame, stocks, min_market=2)
        changed = frame.copy()
        changed.loc[changed.trade_date > cutoff, 'pct_chg'] = 50
        changed.loc[changed.trade_date > cutoff, ['open', 'close']] *= 4
        mutated = emotion.prepare_market(changed, stocks, min_market=2)
        prefix = emotion.prepare_market(frame[frame.trade_date <= cutoff], stocks, min_market=2)
        pd.testing.assert_frame_equal(original.sentiment.iloc[:100], mutated.sentiment.iloc[:100])
        pd.testing.assert_frame_equal(original.sentiment.iloc[:100], prefix.sentiment)
        for spec in emotion.SPECS:
            before = emotion.select_candidates(original, spec[0])[:100]
            after = emotion.select_candidates(mutated, spec[0])[:100]
            truncated = emotion.select_candidates(prefix, spec[0])
            for a, b, c in zip(before, after, truncated):
                np.testing.assert_array_equal(a, b)
                np.testing.assert_array_equal(a, c)

    def test_all_four_rules_trigger_and_keep_deterministic_top_ten(self):
        m = market_fixture(days=20, stocks=12)
        shape = (20, 12)
        m.values['pct_chg'] = np.ones(shape)
        m.features.update(ret5=np.full(shape, -.05), ret20=np.full(shape, .1),
                          above_ma20=np.ones(shape, bool), volume_ratio=np.full(shape, .8),
                          amount20=np.full(shape, 200_000.))
        m.sentiment = pd.DataFrame({'breadth': [.5] * 20, 'breadth_prev': [.5] * 20,
            'market_ret20': [.02] * 20, 'median_pct': [0.] * 20,
            'breadth_mean5_prev': [.5] * 20, 'breadth_max5_prev': [.6] * 20})
        m.sentiment.loc[5, ['breadth', 'breadth_prev']] = [.5, .2]
        m.sentiment.loc[7, ['breadth', 'breadth_mean5_prev', 'median_pct']] = [.7, .4, .8]
        m.sentiment.loc[10, ['breadth', 'median_pct']] = [.35, -.5]
        m.sentiment.loc[15, ['breadth', 'breadth_prev', 'breadth_max5_prev']] = [.5, .7, .9]
        m.values['pct_chg'][15] = -1
        for (strategy_id, *_), t in zip(emotion.SPECS, [5, 7, 10, 15]):
            selections = emotion.select_candidates(m, strategy_id)
            np.testing.assert_array_equal(selections[t], np.arange(10))
            self.assertFalse(len(selections[0]))

    def test_market_coverage_failure_disables_all_signals(self):
        frame, stocks = price_fixture()
        market = emotion.prepare_market(frame, stocks)
        self.assertTrue(market.sentiment.breadth.isna().all())
        for spec in emotion.SPECS:
            self.assertFalse(any(len(p) for p in emotion.select_candidates(market, spec[0])))

    def test_gate_embargo_requires_both_strategy_and_baseline_to_finish(self):
        m = market_fixture(days=300)
        cohorts = [{'signal': i * 7, 'end': i * 7 + 6, 'complete': True,
                    'baseline_end': i * 7 + 6, 'baseline_return': .01,
                    'path': np.array([1.02]), 'trades': [{}] * 10} for i in range(8)]
        allowed, windows = emotion.walk_forward(m, cohorts)
        self.assertTrue(windows[0]['approved'])
        self.assertFalse(allowed[:252].any())
        # The eighth baseline is not yet available at the first test boundary.
        cohorts[-1]['baseline_end'] = 252
        _, windows = emotion.walk_forward(m, cohorts)
        self.assertFalse(windows[0]['approved'])
        self.assertEqual(windows[0]['training_cohort_count'], 7)
        cohorts[-1]['baseline_end'] = 55
        cohorts[-1]['end'] = 252
        _, windows = emotion.walk_forward(m, cohorts)
        self.assertFalse(windows[0]['approved'])
        self.assertEqual(windows[0]['training_cohort_count'], 7)

    def test_future_outcomes_cannot_change_earlier_gate(self):
        m = market_fixture(days=300)
        cohorts = [{'signal': i * 7, 'end': i * 7 + 6, 'complete': True,
                    'baseline_end': i * 7 + 6, 'baseline_return': .01,
                    'path': np.array([1.02]), 'trades': [{}] * 10} for i in range(8)]
        future = {'signal': 250, 'end': 256, 'complete': True, 'baseline_end': 256,
                  'baseline_return': .01, 'path': np.array([1.9]), 'trades': [{}] * 10}
        _, before = emotion.walk_forward(m, cohorts + [future])
        future['path'] = np.array([.1])
        _, after = emotion.walk_forward(m, cohorts + [future])
        self.assertEqual(before[0], after[0])

    def test_baseline_cost_matches_stress_scenario(self):
        m = market_fixture()
        cohort = emotion.replay_cohort(m, 0, np.array([0]), slots=1, cost=.0025)
        emotion.attach_baselines(m, [cohort], {}, cost=.0025)
        self.assertAlmostEqual(cohort['path'][-1] - 1, cohort['baseline_return'])

    def test_missing_bar_and_ex_right_reference_are_handled(self):
        frame, stocks = price_fixture()
        code = frame.ts_code.iloc[0]
        date = sorted(frame.trade_date.unique())[90]
        row = (frame.ts_code == code) & (frame.trade_date == date)
        frame.loc[row, ['open', 'close', 'pre_close']] *= .5
        m = emotion.prepare_market(frame, stocks, min_market=2)
        self.assertTrue(m.values['entry_ok'][90, 0])
        missing = emotion.prepare_market(frame[~row], stocks, min_market=2)
        self.assertFalse(missing.values['entry_ok'][90, 0])
        self.assertEqual(missing.values['next_sell'][90, 0], 91)

    def test_empty_signal_dashboard_is_json_safe_and_conservative(self):
        frame, stocks = price_fixture()
        market = emotion.prepare_market(frame, stocks)
        payload = emotion.build_from_market(market)
        json.dumps(payload, allow_nan=False)
        self.assertEqual(len(payload), 4)
        for strategy in payload:
            self.assertEqual(strategy['status'], 'watch')
            self.assertEqual(strategy['metrics']['signal_count'], 0)
            self.assertEqual(strategy['historical_cases']['wins'], [])
            self.assertFalse(strategy['validation']['historically_supported'])


if __name__ == '__main__':
    unittest.main()
