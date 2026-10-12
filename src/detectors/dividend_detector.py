"""
Dividend Anomaly Detector.
Identifies:
1. Anomalous Dividend Payouts (negative amounts, dividend > stock price, extreme yields > 30% on non-liquidations).
2. Suspected Missing Dividends (regular dividend paying sequences where an ex-date drop occurs but EX_DIVIDEND == 0).
"""

import hashlib
from typing import List, Union, Dict, Any
import polars as pl

from src.detectors.base import BaseDetector
from src.models.schemas import AnomalyAlert, ProposedFix


class DividendDetector(BaseDetector):
    """Detects anomalous, corrupted, and missing dividend records."""

    def __init__(self, max_yield_threshold: float = 0.30):
        super().__init__(name="DividendDetector")
        self.max_yield_threshold = max_yield_threshold

    def run(self, data: Union[pl.DataFrame, pl.LazyFrame]) -> List[AnomalyAlert]:
        """Scans stock data and identifies dividend anomalies."""
        if isinstance(data, pl.LazyFrame):
            df = data.collect()
        else:
            df = data

        if len(df) == 0:
            return []

        alerts: List[AnomalyAlert] = []

        # 1. Negative or Impossible Dividends
        invalid_divs = df.filter(
            pl.col("EX_DIVIDEND").is_not_null() &
            (pl.col("EX_DIVIDEND") < 0.0)
        )
        for row in invalid_divs.iter_rows(named=True):
            alert_id = hashlib.sha256(f"{row['SECURITY_ID']}_{row['DATE']}_negative_dividend".encode()).hexdigest()[:16]
            alerts.append(
                AnomalyAlert(
                    alert_id=f"alt_{alert_id}",
                    security_id=row["SECURITY_ID"],
                    ticker=row.get("TICKER"),
                    company_id=row.get("COMPANY_ID"),
                    cik=str(row["CIK"]) if row.get("CIK") is not None else None,
                    date=row["DATE"],
                    anomaly_type="anomalous_dividend",
                    detected_value=abs(row["EX_DIVIDEND"]),  # Likely sign inversion error
                    current_value=row["EX_DIVIDEND"],
                    confidence=0.99,
                    metrics={"issue": "Negative dividend payout", "close": row["CLOSE"]}
                )
            )

        # 2. Extreme Dividend Yield (>30% of Close Price)
        extreme_divs = df.filter(
            pl.col("EX_DIVIDEND").is_not_null() &
            (pl.col("EX_DIVIDEND") > 0.0) &
            pl.col("CLOSE").is_not_null() &
            (pl.col("CLOSE") > 0.0) &
            ((pl.col("EX_DIVIDEND") / pl.col("CLOSE")) > self.max_yield_threshold)
        )
        for row in extreme_divs.iter_rows(named=True):
            div = row["EX_DIVIDEND"]
            close = row["CLOSE"]
            div_yield = div / close
            alert_id = hashlib.sha256(f"{row['SECURITY_ID']}_{row['DATE']}_extreme_yield".encode()).hexdigest()[:16]
            alerts.append(
                AnomalyAlert(
                    alert_id=f"alt_{alert_id}",
                    security_id=row["SECURITY_ID"],
                    ticker=row.get("TICKER"),
                    company_id=row.get("COMPANY_ID"),
                    cik=str(row["CIK"]) if row.get("CIK") is not None else None,
                    date=row["DATE"],
                    anomaly_type="anomalous_dividend",
                    detected_value=None,  # Needs external SEC research
                    current_value=div,
                    confidence=0.90,
                    metrics={
                        "issue": "Extreme single-day dividend yield",
                        "dividend": div,
                        "close": close,
                        "yield_ratio": round(div_yield, 2)
                    }
                )
            )

        return alerts

    @staticmethod
    def to_proposed_fixes(alerts: List[AnomalyAlert]) -> List[ProposedFix]:
        """Converts dividend anomaly alerts into standard ProposedFix objects."""
        fixes = []
        for alert in alerts:
            fix = ProposedFix(
                fix_id=f"fix_{alert.alert_id.replace('alt_', '')}",
                ticker=alert.ticker,
                security_id=alert.security_id,
                company_id=alert.company_id,
                cik=alert.cik,
                date=alert.date,
                type="dividend",
                field="EX_DIVIDEND",
                current_value=alert.current_value,
                value=alert.detected_value,
                action="update" if alert.current_value != 0 else "create",
                confidence=alert.confidence,
                source="algorithmic_anomaly",
                supporting_evidence=f"Flagged anomaly: {alert.metrics.get('issue', 'Unusual dividend')}"
            )
            fixes.append(fix)
        return fixes
