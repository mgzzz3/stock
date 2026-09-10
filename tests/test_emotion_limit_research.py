import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from reports.emotion_limit_research import limit_regimes


class LimitSentimentResearchTests(unittest.TestCase):
    def test_limit_regimes_use_only_main_board_for_the_market_trigger(self):
        pct = np.zeros((7, 3))
        pct[1, 1] = 20.0  # GEM move must not count as a 10% main-board limit.
        pct[2, 0] = 10.0
        market = SimpleNamespace(
            codes=["600001.SH", "300001.SZ", "920001.BJ"],
            values={"pct_chg": pct},
            features={"eligible": np.ones_like(pct, dtype=bool)},
            sentiment=pd.DataFrame({
                "breadth": [.5, .7, .7, .5, .5, .5, .5],
                "market_ret20": [.1] * 7,
            }),
        )

        regimes = limit_regimes(market)

        self.assertFalse(regimes["limit_up_expansion"][1])
        self.assertTrue(regimes["limit_up_expansion"][2])
        self.assertTrue(regimes["limit_up_cooling"][6])


if __name__ == "__main__":
    unittest.main()
