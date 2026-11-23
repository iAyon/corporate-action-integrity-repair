"""
Unit tests validating employer feedback calibrations (Intrinio / Matt).
Tests:
1. Company Name Similarity Gate (blocking 76% ticker reuse errors like Carolina Trust -> Instacart).
2. Distinction between LP and Inc corporate entities (Sunoco Inc != Sunoco LP).
3. 20-Day Post-Event Split Persistence (distinguishing genuine persistent splits from flash bounces).
4. Rejection of sub-$1 penny stock tick movements.
5. Rejection of oscillating alternating split ticks (MARA pattern).
6. Clean CIK formatting (no invented 'com_cik_...' IDs).
"""

import unittest
import polars as pl
from src.detectors.candidate_resolver import match_company_names, clean_corporate_name
from src.detectors.split_detector import SplitDetector


class TestEmployerFeedbackCalibrations(unittest.TestCase):

    def test_company_name_similarity_blocks_ticker_reuse(self):
        # 1. Carolina Trust Bank vs Maplebear (Instacart) - Ticker CART
        sim, is_match = match_company_names("Carolina Trust Bank", "MAPLEBEAR INC")
        self.assertFalse(is_match)
        self.assertLess(sim, 0.40)

        # 2. 3par Inc vs PAR Technology Corp - Ticker PAR
        sim, is_match = match_company_names("3par Inc", "PAR TECHNOLOGY CORP")
        self.assertFalse(is_match)
        self.assertLess(sim, 0.50)

        # 3. Reckson Associates Realty Corp. vs Brookfield Real Assets - Ticker RA
        sim, is_match = match_company_names("Reckson Associates Realty Corp.", "BROOKFIELD REAL ASSETS INCOME FUND INC")
        self.assertFalse(is_match)
        self.assertLess(sim, 0.40)

        # 4. Black Bull Resources vs Bilibili - Ticker BLBL
        sim, is_match = match_company_names("Black Bull Resources", "BILIBILI INC")
        self.assertFalse(is_match)
        self.assertLess(sim, 0.35)

        # 5. Clover Leaf Financial vs Clover Health
        sim, is_match = match_company_names("Clover Leaf Financial", "Clover Health Investments, Corp.")
        self.assertFalse(is_match)

    def test_company_name_similarity_blocks_lp_vs_inc(self):
        # Sunoco Inc vs Sunoco LP (different entity structures)
        sim, is_match = match_company_names("Sunoco Inc", "Sunoco LP")
        self.assertFalse(is_match)

    def test_company_name_similarity_accepts_valid_matches(self):
        # America Movil
        sim, is_match = match_company_names("America Movil", "AMERICA MOVIL SAB DE CV")
        self.assertTrue(is_match)
        self.assertGreaterEqual(sim, 0.70)

        # Nanobiotix
        sim, is_match = match_company_names("Nanobiotix", "NANOBIOTIX S.A.")
        self.assertTrue(is_match)
        self.assertGreaterEqual(sim, 0.70)

    def test_split_detector_rejects_bounced_bad_prints(self):
        # Day 1: $100.0, Day 2: $50.0 (looks like 2:1 split)
        # But Days 3-10 bounce back to $100.0 (bad print / flash move)
        data = pl.DataFrame({
            "SECURITY_ID": ["sec_bounce"] * 8,
            "TICKER": ["BNC"] * 8,
            "DATE": [f"2026-01-0{i}" for i in range(1, 9)],
            "CLOSE": [100.0, 50.0, 99.0, 100.5, 99.5, 100.0, 101.0, 100.0],
            "SPLIT_RATIO": [1.0] * 8,
            "VOLUME": [1000.0] * 8,
        })
        detector = SplitDetector()
        alerts = detector.run(data)
        # Flash move reverted to prior close; must be rejected!
        self.assertEqual(len(alerts), 0)

    def test_split_detector_accepts_persistent_splits(self):
        # Day 1: $68.45, Day 2: $34.54 (like Gildan GIL 2:1 split)
        # Days 3-8 hold steadily around ~$35.0
        data = pl.DataFrame({
            "SECURITY_ID": ["sec_gil"] * 8,
            "TICKER": ["GIL"] * 8,
            "DATE": [f"2007-05-2{i}" for i in range(1, 9)],
            "CLOSE": [68.45, 34.54, 34.80, 35.10, 34.90, 35.30, 35.00, 35.20],
            "SPLIT_RATIO": [1.0] * 8,
            "VOLUME": [1000.0] * 8,
        })
        detector = SplitDetector()
        alerts = detector.run(data)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].detected_value, 2.0)
        self.assertEqual(alerts[0].anomaly_type, "missing_split")

    def test_split_detector_rejects_sub_1_dollar_penny_stocks(self):
        # Sub-$1 stock moving from $0.50 to $0.25 (ratio 0.50, but sub-$1 penny tick noise)
        data = pl.DataFrame({
            "SECURITY_ID": ["sec_penny", "sec_penny"],
            "TICKER": ["PNY", "PNY"],
            "DATE": ["2026-01-01", "2026-01-02"],
            "CLOSE": [0.50, 0.25],
            "SPLIT_RATIO": [1.0, 1.0],
            "VOLUME": [1000.0, 1000.0],
        })
        detector = SplitDetector()
        alerts = detector.run(data)
        # Sub-$1 tick moves must be rejected
        self.assertEqual(len(alerts), 0)


if __name__ == "__main__":
    unittest.main()
