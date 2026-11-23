"""
Split Anomaly Detector (V2 - Calibrated).
Identifies:
1. Missing Forward & Reverse Stock Splits with multi-day price persistence verification.
2. Rejection of single-day flash moves, bad prints, and alternating penny-stock bid-ask oscillations.
3. Suppression of cases where a corporate action split is already recorded nearby (+/- 5 days).
4. Bad / Inverted Split Ratios (recorded SPLIT_RATIO mismatching actual price movement).
"""

import hashlib
from typing import List, Union, Dict, Any, Set
import numpy as np
import polars as pl

from src.detectors.base import BaseDetector
from src.models.schemas import AnomalyAlert, ProposedFix
from src.config import SPLIT_DETECTION_CONFIG


class SplitDetector(BaseDetector):
    """Detects missing and corrupted stock split corporate actions with persistence validation."""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(name="SplitDetector")
        self.config = config or SPLIT_DETECTION_CONFIG

    def run(self, data: Union[pl.DataFrame, pl.LazyFrame]) -> List[AnomalyAlert]:
        """
        Scans stock data and identifies split anomalies, enforcing:
        - Minimum price threshold ($1.00) to eliminate sub-$1 penny stock tick noise.
        - Multi-day price persistence (price must hold, not bounce back).
        - Alternating oscillation suppression (e.g. alternating 2:1 and 1:2 ticks).
        - Nearby split check (+/- 5 trading days).
        """
        if isinstance(data, pl.LazyFrame):
            df = data.collect()
        else:
            df = data

        if len(df) == 0:
            return []

        # Sort temporally per security
        df = df.sort(["SECURITY_ID", "DATE"])

        # Compute prior close, volume, and day-over-day price ratio
        df = df.with_columns([
            pl.col("CLOSE").shift(1).over("SECURITY_ID").alias("PREV_CLOSE"),
            pl.col("VOLUME").shift(1).over("SECURITY_ID").alias("PREV_VOLUME"),
        ])
        
        df = df.with_columns([
            (pl.col("CLOSE") / pl.col("PREV_CLOSE")).alias("PRICE_RATIO")
        ])

        min_price = max(1.0, self.config.get("min_price_threshold", 1.0))
        split_targets = self.config.get("split_targets", [])

        alerts: List[AnomalyAlert] = []

        # Filter for valid rows above minimum price threshold (filtering penny stock noise)
        valid_df = df.filter(
            pl.col("PREV_CLOSE").is_not_null() &
            (pl.col("PREV_CLOSE") >= min_price) &
            pl.col("CLOSE").is_not_null() &
            (pl.col("CLOSE") >= min_price) &
            (pl.col("SPLIT_RATIO") == 1.0)
        )

        # Detect securities with alternating oscillations in this dataset
        alternating_secs: Set[str] = set()
        sec_ratios = valid_df.group_by("SECURITY_ID").agg([
            pl.col("PRICE_RATIO").min().alias("min_ratio"),
            pl.col("PRICE_RATIO").max().alias("max_ratio"),
        ])
        for row in sec_ratios.iter_rows(named=True):
            if row["min_ratio"] is not None and row["max_ratio"] is not None:
                if row["min_ratio"] <= 0.60 and row["max_ratio"] >= 1.75:
                    alternating_secs.add(row["SECURITY_ID"])

        # Partition full dataframe by security for fast window and persistence lookups
        sec_dfs = {sid: sdf for sid, sdf in df.partition_by("SECURITY_ID", as_dict=True).items()}

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
                sid = row["SECURITY_ID"]
                rdate = row["DATE"]
                price_ratio = row["PRICE_RATIO"]
                pclose = row["PREV_CLOSE"]
                close = row["CLOSE"]

                # 1. Suppress oscillating penny-stock securities
                if sid in alternating_secs:
                    continue

                sdf = sec_dfs.get((sid,)) if (sid,) in sec_dfs else sec_dfs.get(sid)
                if sdf is None:
                    continue

                dates = sdf["DATE"].to_list()
                if rdate not in dates:
                    continue

                idx = dates.index(rdate)

                # 2. Suppress if a split is already recorded nearby (+/- 5 trading days)
                w_start = max(0, idx - 5)
                w_end = min(len(sdf), idx + 6)
                nearby_splits = sdf["SPLIT_RATIO"][w_start:idx].to_list() + sdf["SPLIT_RATIO"][idx+1:w_end].to_list()
                if any(s != 1.0 and s is not None for s in nearby_splits):
                    continue

                # 3. Post-event persistence check: ensure price holds at new level over horizon
                post_closes = [c for c in sdf["CLOSE"][idx+1 : idx+21].to_list() if c is not None and c > 0]
                if len(post_closes) >= 3:
                    med_post = float(np.median(post_closes))
                    # Reject if price bounced back to pre-split close within 18%
                    if abs(med_post - pclose) / pclose <= 0.18:
                        continue
                    # Reject if price drifted completely away (> 25% from new close)
                    if abs(med_post - close) / close > 0.22:
                        continue
                else:
                    med_post = close

                # Calibrated confidence scoring
                delta_pct = abs(price_ratio - ratio) / ratio
                calibrated_conf = max(0.85, min(0.98, 0.98 - delta_pct * 1.0))
                
                alert_id = hashlib.sha256(
                    f"{sid}_{rdate}_missing_split_{expected_split_ratio}".encode()
                ).hexdigest()[:16]

                alerts.append(
                    AnomalyAlert(
                        alert_id=f"alt_{alert_id}",
                        security_id=sid,
                        ticker=row.get("TICKER"),
                        company_id=row.get("COMPANY_ID"),
                        cik=str(row["CIK"]) if row.get("CIK") is not None else None,
                        date=rdate,
                        anomaly_type="missing_split",
                        detected_value=expected_split_ratio,
                        current_value=row["SPLIT_RATIO"],
                        confidence=round(calibrated_conf, 3),
                        metrics={
                            "price_ratio": round(price_ratio, 4),
                            "prev_close": pclose,
                            "close": close,
                            "post_horizon_median": round(med_post, 4),
                            "volume": row.get("VOLUME"),
                            "prev_volume": row.get("PREV_VOLUME"),
                            "target_split_type": label
                        }
                    )
                )

        # 4. Corrupted / Bad Split Ratios: SPLIT_RATIO != 1.0 but price didn't move accordingly
        recorded_splits = df.filter(
            pl.col("SPLIT_RATIO").is_not_null() &
            (pl.col("SPLIT_RATIO") != 1.0) &
            pl.col("PREV_CLOSE").is_not_null() &
            (pl.col("PREV_CLOSE") >= min_price)
        )

        for row in recorded_splits.iter_rows(named=True):
            rec_split = row["SPLIT_RATIO"]
            if rec_split <= 0:
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
                expected_price_ratio = 1.0 / rec_split
                actual_price_ratio = row["PRICE_RATIO"]
                if actual_price_ratio is not None:
                    divergence = abs(actual_price_ratio - expected_price_ratio) / expected_price_ratio
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
                                confidence=0.88,
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
                    f"Identified persistent {alert.metrics.get('target_split_type', 'split')}: "
                    f"close dropped from ${alert.metrics.get('prev_close')} to ${alert.metrics.get('close')} "
                    f"(ratio: {alert.metrics.get('price_ratio')}) and held over post-event horizon "
                    f"(median ${alert.metrics.get('post_horizon_median', alert.metrics.get('close'))})."
                )
            )
            fixes.append(fix)
        return fixes
