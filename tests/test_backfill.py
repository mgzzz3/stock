import unittest
from unittest.mock import patch

from ingest.backfill import backfill, main


class BackfillTests(unittest.TestCase):
    @patch("ingest.backfill.fetch_range")
    def test_default_backfill_fetches_five_years(self, fetch_range):
        backfill(end_date="20260610")
        start, end = fetch_range.call_args.args
        self.assertEqual(end, "20260610")
        self.assertTrue("202106" <= start <= "202107")

    @patch("ingest.backfill.fetch_range")
    def test_years_option_controls_history_range(self, fetch_range):
        main(["--years", "8"])
        start, end = fetch_range.call_args.args
        self.assertGreaterEqual(int(end[:4]) - int(start[:4]), 7)

    @patch("ingest.backfill.fetch_range")
    def test_custom_range_is_preserved(self, fetch_range):
        main(["20200101", "20210101"])
        fetch_range.assert_called_once_with("20200101", "20210101")


if __name__ == "__main__":
    unittest.main()
