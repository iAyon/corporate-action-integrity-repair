"""
Unit tests for SplitDetector using Python's standard unittest framework.
"""

import unittest
import polars as pl
from src.detectors.split_detector import SplitDetector


class TestSplitDetector(unittest.TestCase):

    def setUp(self):
        self.detector = SplitDetector()

    def test_split_detector_no_anomalies(self):
        data = pl.DataFrame({
            "SECURITY_ID": ["sec_1", "sec_1", "sec_1"],
            "TICKER": ["TEST", "TEST", "TEST"],
            "DATE": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "CLOSE": [100.0, 101.5, 102.0],
            "SPLIT_RATIO": [1.0, 1.0, 1.0],
            "VOLUME": [1000.0, 1200.0, 1100.0],
        })
        alerts = self.detector.run(data)
        self.assertEqual(len(alerts), 0)

    def test_split_detector_missing_2_for_1_split(self):
        # Day 2 price drops from 100 to 50 (ratio 0.50), but SPLIT_RATIO is 1.0
        data = pl.DataFrame({
            "SECURITY_ID": ["sec_1", "sec_1"],
            "TICKER": ["AAPL", "AAPL"],
            "DATE": ["2026-01-01", "2026-01-02"],
            "CLOSE": [100.0, 50.0],
            "SPLIT_RATIO": [1.0, 1.0],
            "VOLUME": [1000.0, 2500.0],
        })
        alerts = self.detector.run(data)
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.anomaly_type, "missing_split")
        self.assertEqual(alert.detected_value, 2.0)
        self.assertGreaterEqual(alert.confidence, 0.90)
        self.assertEqual(alert.metrics["price_ratio"], 0.5)

        # Test conversion to proposed fix
        fixes = self.detector.to_proposed_fixes(alerts)
        self.assertEqual(len(fixes), 1)
        fix = fixes[0]
        self.assertEqual(fix.type, "split")
        self.assertEqual(fix.field, "SPLIT_RATIO")
        self.assertEqual(fix.value, 2.0)
        self.assertEqual(fix.action, "create")
        self.assertEqual(fix.ticker, "AAPL")

    def test_split_detector_missing_reverse_split(self):
        # Reverse split 1:5: Price jumps from 2.0 to 10.0 (ratio 5.0)
        data = pl.DataFrame({
            "SECURITY_ID": ["sec_2", "sec_2"],
            "TICKER": ["REV", "REV"],
            "DATE": ["2026-01-01", "2026-01-02"],
            "CLOSE": [2.0, 10.0],
            "SPLIT_RATIO": [1.0, 1.0],
            "VOLUME": [500.0, 1500.0],
        })
        alerts = self.detector.run(data)
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.anomaly_type, "missing_split")
        self.assertEqual(alert.detected_value, 0.2)
        self.assertEqual(alert.metrics["price_ratio"], 5.0)

    def test_split_detector_bad_split_ratio(self):
        # Recorded SPLIT_RATIO = 2.0, but price remained unchanged at 100.0
        data = pl.DataFrame({
            "SECURITY_ID": ["sec_3", "sec_3"],
            "TICKER": ["BAD", "BAD"],
            "DATE": ["2026-01-01", "2026-01-02"],
            "CLOSE": [100.0, 100.0],
            "SPLIT_RATIO": [1.0, 2.0],  # Claims split occurred, but price never halved
            "VOLUME": [1000.0, 1000.0],
        })
        alerts = self.detector.run(data)
        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.anomaly_type, "bad_split_ratio")
        self.assertEqual(alert.current_value, 2.0)


if __name__ == "__main__":
    unittest.main()
