"""
Unit tests for MAMergerExtractor (Project Goals 4 & 5).
"""

import unittest
from src.research.ma_extractor import MAMergerExtractor


class TestMAMergerExtractor(unittest.TestCase):

    def setUp(self):
        self.extractor = MAMergerExtractor()

    def test_extract_all_cash_deal(self):
        sample_text = (
            "Pursuant to the Merger Agreement with Microsoft Corporation, each share of common stock "
            "was cancelled and automatically converted into the right to receive $95.00 in cash without interest."
        )
        result = self.extractor.extract_ma_terms_from_text(sample_text)
        self.assertEqual(result["deal_type"], "all_cash")
        self.assertEqual(result["cash_per_share"], 95.0)
        self.assertEqual(result["stock_exchange_ratio"], 0.0)
        self.assertEqual(result["acquirer_name"], "Microsoft Corporation")

    def test_extract_mixed_cash_and_stock_deal(self):
        sample_text = (
            "Under the transaction with Teladoc Health, Inc., each share of common stock was converted into "
            "the right to receive 0.5920 of a share of common stock and $11.33 in cash per share."
        )
        result = self.extractor.extract_ma_terms_from_text(sample_text)
        self.assertEqual(result["deal_type"], "mixed_cash_and_stock")
        self.assertEqual(result["cash_per_share"], 11.33)
        self.assertEqual(result["stock_exchange_ratio"], 0.592)
        self.assertIn(result["acquirer_name"], ["Teladoc Health, Inc.", "Teladoc Health, Inc"])

    def test_extract_all_stock_deal(self):
        sample_text = (
            "In connection with the merger with Chevron Corporation, shareholders are entitled to receive "
            "an exchange ratio of 0.1024 shares of Chevron common stock for each share owned."
        )
        result = self.extractor.extract_ma_terms_from_text(sample_text)
        self.assertEqual(result["deal_type"], "all_stock")
        self.assertEqual(result["cash_per_share"], 0.0)
        self.assertEqual(result["stock_exchange_ratio"], 0.1024)
        self.assertEqual(result["acquirer_name"], "Chevron Corporation")


if __name__ == "__main__":
    unittest.main()
