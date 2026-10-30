"""
Unit tests for automated dataset patch application, backward price adjustments, and price continuity.
"""

import unittest
import polars as pl
from src.etl.apply_patches import (
    apply_split_patch_to_dataframe,
    apply_dividend_patch_to_dataframe,
    apply_company_association_patch,
    verify_split_continuity
)


class TestApplyPatches(unittest.TestCase):

    def test_apply_split_patch_recalculates_backward_prices(self):
        # 3 days of historical prices:
        # Day 1: $100
        # Day 2: $100
        # Day 3: $50 (2:1 split occurred on 2026-01-03, but SPLIT_RATIO was recorded as 1.0)
        df = pl.DataFrame({
            "SECURITY_ID": ["sec_test", "sec_test", "sec_test"],
            "DATE": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "OPEN": [100.0, 100.0, 50.0],
            "HIGH": [105.0, 105.0, 52.0],
            "LOW": [98.0, 98.0, 49.0],
            "CLOSE": [100.0, 100.0, 50.0],
            "SPLIT_RATIO": [1.0, 1.0, 1.0],
            "ADJ_FACTOR": [1.0, 1.0, 1.0],
            "ADJ_OPEN": [100.0, 100.0, 50.0],
            "ADJ_HIGH": [105.0, 105.0, 52.0],
            "ADJ_LOW": [98.0, 98.0, 49.0],
            "ADJ_CLOSE": [100.0, 100.0, 50.0],
        })

        # Apply fix: SPLIT_RATIO = 2.0 on 2026-01-03
        repaired_df = apply_split_patch_to_dataframe(
            df=df,
            security_id="sec_test",
            split_date="2026-01-03",
            new_split_ratio=2.0
        )

        # Day 3 SPLIT_RATIO is now 2.0
        day3 = repaired_df.filter(pl.col("DATE") == "2026-01-03").to_dicts()[0]
        self.assertEqual(day3["SPLIT_RATIO"], 2.0)
        self.assertEqual(day3["ADJ_CLOSE"], 50.0)

        # Days before Day 3 should have their ADJ_FACTOR divided by 2.0 (0.50)
        # and ADJ_CLOSE adjusted to $50.00
        day1 = repaired_df.filter(pl.col("DATE") == "2026-01-01").to_dicts()[0]
        self.assertEqual(day1["ADJ_FACTOR"], 0.50)
        self.assertEqual(day1["ADJ_CLOSE"], 50.0)
        self.assertEqual(day1["ADJ_OPEN"], 50.0)

        day2 = repaired_df.filter(pl.col("DATE") == "2026-01-02").to_dicts()[0]
        self.assertEqual(day2["ADJ_FACTOR"], 0.50)
        self.assertEqual(day2["ADJ_CLOSE"], 50.0)

        # Verify continuity: between Day 2 ($50.00) and Day 3 ($50.00) there is 0% cliff jump
        continuity = verify_split_continuity(repaired_df, "sec_test", "2026-01-03")
        self.assertTrue(continuity["verified"])
        self.assertEqual(continuity["adjusted_price_jump_pct"], 0.0)

    def test_apply_dividend_patch(self):
        df = pl.DataFrame({
            "SECURITY_ID": ["sec_div"],
            "DATE": ["2026-05-15"],
            "EX_DIVIDEND": [0.0]
        })
        repaired = apply_dividend_patch_to_dataframe(df, "sec_div", "2026-05-15", 5.30)
        self.assertEqual(repaired["EX_DIVIDEND"][0], 5.30)

    def test_apply_company_association_patch(self):
        df = pl.DataFrame({
            "SECURITY_ID": ["sec_comp", "sec_comp"],
            "COMPANY_ID": [None, None],
            "CIK": [None, None]
        })
        repaired = apply_company_association_patch(df, "sec_comp", "com_cik_843006", "0000843006")
        self.assertEqual(repaired["COMPANY_ID"].to_list(), ["com_cik_843006", "com_cik_843006"])
        self.assertEqual(repaired["CIK"].to_list(), ["0000843006", "0000843006"])


if __name__ == "__main__":
    unittest.main()
