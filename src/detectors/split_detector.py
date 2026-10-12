"""
Split Anomaly Detector.
Identifies:
1. Missing Forward & Reverse Stock Splits (overnight price discontinuity matching standard ratios while SPLIT_RATIO == 1.0).
2. Bad / Inverted Split Ratios (recorded SPLIT_RATIO mismatching actual price movement).
"""

import hashlib
from typing import List, Union, Dict, Any
import polars as pl

from src.detectors.base import BaseDetector
from src.models.schemas import AnomalyAlert, ProposedFix
from src.config import SPLIT_DETECTION_CONFIG


class SplitDetector(BaseDetector):
    """Detects missing and corrupted stock split corporate actions."""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(name="SplitDetector")
        self.config = config or SPLIT_DETECTION_CONFIG

    def run(self, data: Union[pl.DataFrame, pl.LazyFrame]) -> List[AnomalyAlert]:
        """
        Scans stock data and identifies split anomalies.
        """
        if isinstance(data, pl.LazyFrame):
            df = data.collect()
        else:
            df = data

        if len(df) == 0:
            return []

        # Sort temporally per security
        df = df.sort(["SECURITY_ID", "DATE"])

        # Compute prior close and day-over-day price ratio
        df = df.with_columns([
            pl.col("CLOSE").shift(1).over("SECURITY_ID").alias("PREV_CLOSE"),
            pl.col("VOLUME").shift(1).over("SECURITY_ID").alias("PREV_VOLUME"),
        ])
        
        df = df.with_columns([
            (pl.col("CLOSE") / pl.col("PREV_CLOSE")).alias("PRICE_RATIO")
        ])

        min_price = self.config.get("min_price_threshold", 0.50)
        split_targets = self.config.get("split_targets", [])

        alerts: List[AnomalyAlert] = []

        # 1. Missing Splits: SPLIT_RATIO == 1.0 but PRICE_RATIO matches a split target
        # Filter for valid rows
        valid_df = df.filter(
            pl.col("PREV_CLOSE").is_not_null() &
            (pl.col("PREV_CLOSE") >= min_price) &
            pl.col("CLOSE").is_not_null() &
            (pl.col("CLOSE") > 0) &
            (pl.col("SPLIT_RATIO") == 1.0)
        )

        for target in split_targets:
            ratio = target["ratio"]
            tol = target["tolerance"]
            expected_split_ratio = target["split_ratio"]
            label = target["label"]

            low_bound = ratio * (1.0 - tol)
            high_bound = ratio * (1.0 + tol)

            suspects = valid_df.filter(
                (pl.col("PRICE_RATIO") >= low_bound) & (pl.col("PRICE_RATIO") <= high_bound)
            )

            for row in suspects.iter_rows(named=True):
                price_ratio = row["PRICE_RATIO"]
                delta_pct = abs(price_ratio - ratio) / ratio
                # Confidence score: closer to exact ratio gives higher confidence (0.80 to 0.98)
                confidence = max(0.75, min(0.98, 1.0 - delta_pct * 1.5))
                
                alert_id = hashlib.sha256(
                    f"{row['SECURITY_ID']}_{row['DATE']}_missing_split_{expected_split_ratio}".encode()
                ).hexdigest()[:16]

                alerts.append(
                    AnomalyAlert(
                        alert_id=f"alt_{alert_id}",
                        security_id=row["SECURITY_ID"],
                        ticker=row.get("TICKER"),
                        company_id=row.get("COMPANY_ID"),
                        cik=str(row["CIK"]) if row.get("CIK") is not None else None,
                        date=row["DATE"],
                        anomaly_type="missing_split",
                        detected_value=expected_split_ratio,
                        current_value=row["SPLIT_RATIO"],
                        confidence=round(confidence, 3),
                        metrics={
                            "price_ratio": round(price_ratio, 4),
                            "prev_close": row["PREV_CLOSE"],
                            "close": row["CLOSE"],
                            "volume": row.get("VOLUME"),
                            "prev_volume": row.get("PREV_VOLUME"),
                            "target_split_type": label
                        }
                    )
                )

        # 2. Corrupted / Bad Split Ratios: SPLIT_RATIO != 1.0 but price didn't move accordingly
        recorded_splits = df.filter(
            pl.col("SPLIT_RATIO").is_not_null() &
            (pl.col("SPLIT_RATIO") != 1.0) &
            pl.col("PREV_CLOSE").is_not_null() &
            (pl.col("PREV_CLOSE") >= min_price)
        )

        for row in recorded_splits.iter_rows(named=True):
            rec_split = row["SPLIT_RATIO"]
            if rec_split <= 0:
                # Impossible split ratio (negative or zero)
                alert_id = hashlib.sha256(f"{row['SECURITY_ID']}_{row['DATE']}_invalid_split_sign".encode()).hexdigest()[:16]
                alerts.append(
                    AnomalyAlert(
                        alert_id=f"alt_{alert_id}",
                        security_id=row["SECURITY_ID"],
                        ticker=row.get("TICKER"),
                        company_id=row.get("COMPANY_ID"),
                        cik=str(row["CIK"]) if row.get("CIK") is not None else None,
                        date=row["DATE"],
                        anomaly_type="bad_split_ratio",
                        detected_value=None,
                        current_value=rec_split,
                        confidence=0.99,
                        metrics={"issue": "Non-positive split ratio", "close": row["CLOSE"]}
                    )
                )
            else:
                # Expected price ratio for a split is ~ 1.0 / split_ratio
                expected_price_ratio = 1.0 / rec_split
                actual_price_ratio = row["PRICE_RATIO"]
                if actual_price_ratio is not None:
                    divergence = abs(actual_price_ratio - expected_price_ratio) / expected_price_ratio
                    # If price moved in the complete opposite direction or diverged by > 35%
                    if divergence > 0.35:
                        alert_id = hashlib.sha256(f"{row['SECURITY_ID']}_{row['DATE']}_bad_split_ratio".encode()).hexdigest()[:16]
                        alerts.append(
                            AnomalyAlert(
                                alert_id=f"alt_{alert_id}",
                                security_id=row["SECURITY_ID"],
                                ticker=row.get("TICKER"),
                                company_id=row.get("COMPANY_ID"),
                                cik=str(row["CIK"]) if row.get("CIK") is not None else None,
                                date=row["DATE"],
                                anomaly_type="bad_split_ratio",
                                detected_value=round(1.0 / actual_price_ratio, 2) if actual_price_ratio > 0 else None,
                                current_value=rec_split,
                                confidence=0.85,
                                metrics={
                                    "divergence_pct": round(divergence * 100, 1),
                                    "price_ratio": round(actual_price_ratio, 4),
                                    "expected_price_ratio": round(expected_price_ratio, 4),
                                    "prev_close": row["PREV_CLOSE"],
                                    "close": row["CLOSE"]
                                }
                            )
                        )

        return alerts

    @staticmethod
    def to_proposed_fixes(alerts: List[AnomalyAlert]) -> List[ProposedFix]:
        """Converts anomaly alerts into the project's standard ProposedFix format."""
        fixes = []
        for alert in alerts:
            action = "create" if alert.anomaly_type == "missing_split" else "update"
            fix = ProposedFix(
                fix_id=f"fix_{alert.alert_id.replace('alt_', '')}",
                ticker=alert.ticker,
                security_id=alert.security_id,
                company_id=alert.company_id,
                cik=alert.cik,
                date=alert.date,
                type="split",
                field="SPLIT_RATIO",
                current_value=alert.current_value or 1.0,
                value=alert.detected_value,
                action=action,
                confidence=alert.confidence,
                source="algorithmic_anomaly",
                supporting_evidence=(
                    f"Identified {alert.metrics.get('target_split_type', 'split')} via overnight price movement: "
                    f"close dropped from ${alert.metrics.get('prev_close')} to ${alert.metrics.get('close')} "
                    f"(ratio: {alert.metrics.get('price_ratio')}) while SPLIT_RATIO was {alert.current_value}."
                )
            )
            fixes.append(fix)
        return fixes
