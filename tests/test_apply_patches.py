"""
Unit tests for automated dataset patch application and backward price adjustments.
"""

import unittest
import polars as pl
from src.etl.apply_patches import apply_split_patch_to_dataframe


class TestApplyPatches(unittest.TestCase):

    def test_apply_split_patch_recalculates_backward_prices(self):
        # 3 days of historical prices:
        # Day 1: $100
        # Day 2: $100
        # Day 3: $50 (2:1 split occurred on 2026-01-03, but SPLIT_RATIO was recorded as 1.0)
        df = pl.DataFrame({
            "SECURITY_ID": ["sec_test", "sec_test", "sec_test"],
            "DATE": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "CLOSE": [100.0, 100.0, 50.0],
            "SPLIT_RATIO": [1.0, 1.0, 1.0],
            "ADJ_FACTOR": [1.0, 1.0, 1.0],
            "ADJ_CLOSE": [100.0, 100.0, 50.0],
        })

        # Apply fix: SPLIT_RATIO = 2.0 on 2026-01-03
        repaired_df = apply_split_patch_to_dataframe(
            df=df,
            security_id="sec_test",
            split_date="2026-01-03",
            new_split_ratio=2.0
        )

        # Verified expectations:
        # Day 3 SPLIT_RATIO is now 2.0
        day3 = repaired_df.filter(pl.col("DATE") == "2026-01-03").to_dicts()[0]
        self.assertEqual(day3["SPLIT_RATIO"], 2.0)
        self.assertEqual(day3["ADJ_CLOSE"], 50.0)

        # Days before Day 3 (2026-01-01 and 2026-01-02) should have their ADJ_FACTOR divided by 2.0 (0.50)
        # and ADJ_CLOSE adjusted to $50.00
        day1 = repaired_df.filter(pl.col("DATE") == "2026-01-01").to_dicts()[0]
        self.assertEqual(day1["ADJ_FACTOR"], 0.50)
        self.assertEqual(day1["ADJ_CLOSE"], 50.0)

        day2 = repaired_df.filter(pl.col("DATE") == "2026-01-02").to_dicts()[0]
        self.assertEqual(day2["ADJ_FACTOR"], 0.50)
        self.assertEqual(day2["ADJ_CLOSE"], 50.0)


if __name__ == "__main__":
    unittest.main()
