"""
Unit tests for refined MAMergerExtractor (Project Goals 4 & 5).
"""

import json
import unittest
from src.research.ma_extractor import MAMergerExtractor


class TestMAMergerExtractor(unittest.TestCase):

    def setUp(self):
        self.extractor = MAMergerExtractor()

    def test_extract_all_cash_deal(self):
        sample_text = (
            "Pursuant to the Merger Agreement with Microsoft Corporation, each share of common stock "
            "was cancelled and automatically converted into the right to receive $95.00 in cash without interest. "
            "The merger was completed on October 13, 2023."
        )
        result = self.extractor.extract_ma_terms_from_text(sample_text)
        self.assertEqual(result["deal_type"], "all_cash")
        self.assertEqual(result["cash_per_share"], 95.0)
        self.assertEqual(result["stock_exchange_ratio"], 0.0)
        self.assertEqual(result["acquirer_name"], "Microsoft Corporation")
        self.assertEqual(result["acquirer_ticker"], "MSFT")
        self.assertEqual(result["acquirer_cik"], "0000789019")
        self.assertEqual(result["effective_date"], "2023-10-13")

    def test_extract_mixed_cash_and_stock_deal(self):
        sample_text = (
            "Under the transaction with Teladoc Health, Inc., each share of common stock was converted into "
            "the right to receive 0.5920 of a share of common stock and $11.33 in cash per share. "
            "The transaction was consummated on October 30, 2020."
        )
        result = self.extractor.extract_ma_terms_from_text(sample_text)
        self.assertEqual(result["deal_type"], "mixed_cash_and_stock")
        self.assertEqual(result["cash_per_share"], 11.33)
        self.assertEqual(result["stock_exchange_ratio"], 0.592)
        self.assertIn("Teladoc Health", result["acquirer_name"])
        self.assertEqual(result["acquirer_ticker"], "TDOC")
        self.assertEqual(result["effective_date"], "2020-10-30")

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
        self.assertEqual(result["acquirer_ticker"], "CVX")

    def test_extract_cvr_deal(self):
        sample_text = (
            "Each share was converted into the right to receive $50.00 in cash and one contingent value right (CVR) "
            "representing the right to receive up to $9.00 in cash upon regulatory milestone approval."
        )
        result = self.extractor.extract_ma_terms_from_text(sample_text)
        self.assertTrue(result["has_cvr"])
        self.assertEqual(result["cash_per_share"], 50.0)
        self.assertEqual(result["cvr_amount"], 9.0)
        self.assertEqual(result["deal_type"], "cvr_cash")

    def test_build_proposed_fix_schema(self):
        merger_data = {
            "source": "sec",
            "source_id": "0001104659-23-108985",
            "source_url": "https://www.sec.gov/Archives/edgar/data/718877/000110465923108985/tm2328253d1_8k.htm",
            "form_type": "8-K",
            "filing_date": "2023-10-13",
            "effective_date": "2023-10-13",
            "target_name": "Activision Blizzard, Inc.",
            "target_cik": "0000718877",
            "acquirer_name": "Microsoft Corporation",
            "acquirer_ticker": "MSFT",
            "acquirer_cik": "0000789019",
            "deal_type": "all_cash",
            "cash_per_share": 95.0,
            "stock_exchange_ratio": 0.0,
            "has_cvr": False,
            "cvr_amount": 0.0,
            "excerpt": "Cancelled and converted into right to receive $95.00 in cash."
        }
        fix = self.extractor.build_proposed_fix(
            target_ticker="ATVI",
            security_id="sec_atvi123",
            merger_data=merger_data
        )
        self.assertTrue(fix["fix_id"].startswith("fix_"))
        self.assertEqual(fix["ticker"], "ATVI")
        self.assertEqual(fix["security_id"], "sec_atvi123")
        self.assertEqual(fix["date"], "2023-10-13")
        self.assertEqual(fix["fix_type"], "merger_acquisition")
        self.assertEqual(fix["action"], "flag_delisted_record_and_set_conversion_terms")
        self.assertEqual(fix["confidence"], 0.98)
        self.assertEqual(fix["source_id"], "0001104659-23-108985")

        # Verify JSON parsed payload
        payload = json.loads(fix["proposed_value"])
        self.assertEqual(payload["acquirer_ticker"], "MSFT")
        self.assertEqual(payload["cash_per_share"], 95.0)
        self.assertEqual(payload["deal_type"], "all_cash")


if __name__ == "__main__":
    unittest.main()
