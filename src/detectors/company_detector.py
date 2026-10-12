"""
Company Association Integrity Detector.
Addresses:
- Goal 2: Securities associated with the wrong company (CIK collisions, ticker reassignment).
- Goal 3: Securities missing a company (COMPANY_ID or CIK is NULL/empty).
"""

import hashlib
from typing import List, Union
import polars as pl

from src.detectors.base import BaseDetector
from src.models.schemas import AnomalyAlert, ProposedFix


class CompanyDetector(BaseDetector):
    """Detects missing company links and conflicting entity mappings."""

    def __init__(self):
        super().__init__(name="CompanyDetector")

    def run(self, data: Union[pl.DataFrame, pl.LazyFrame]) -> List[AnomalyAlert]:
        """Scans stock data and identifies company association errors."""
        if isinstance(data, pl.LazyFrame):
            df = data.collect()
        else:
            df = data

        if len(df) == 0:
            return []

        alerts: List[AnomalyAlert] = []

        # 1. Missing Company Association (Goal 3)
        # Find distinct securities where COMPANY_ID is null or empty
        missing_company_df = df.filter(
            pl.col("COMPANY_ID").is_null() | (pl.col("COMPANY_ID") == "")
        ).select(["SECURITY_ID", "TICKER", "NAME", "CIK", "DATE"]).unique(subset=["SECURITY_ID"])

        for row in missing_company_df.iter_rows(named=True):
            alert_id = hashlib.sha256(f"{row['SECURITY_ID']}_missing_company".encode()).hexdigest()[:16]
            alerts.append(
                AnomalyAlert(
                    alert_id=f"alt_{alert_id}",
                    security_id=row["SECURITY_ID"],
                    ticker=row.get("TICKER"),
                    company_id=None,
                    cik=str(row["CIK"]) if row.get("CIK") is not None else None,
                    date=row["DATE"],
                    anomaly_type="missing_company",
                    detected_value=None,  # To be populated by SEC / Intrinio CIK resolver
                    current_value=None,
                    confidence=0.99,
                    metrics={
                        "issue": "Missing company association (COMPANY_ID is NULL)",
                        "security_name": row.get("NAME")
                    }
                )
            )

        # 2. Wrong Company Association: Single SECURITY_ID mapping to multiple distinct CIKs (Goal 2)
        sec_cik_counts = (
            df.filter(pl.col("CIK").is_not_null())
            .group_by("SECURITY_ID")
            .agg([
                pl.col("CIK").n_unique().alias("cik_count"),
                pl.col("CIK").unique().alias("ciks"),
                pl.col("TICKER").unique().alias("tickers"),
                pl.col("DATE").min().alias("min_date"),
                pl.col("DATE").max().alias("max_date"),
            ])
            .filter(pl.col("cik_count") > 1)
        )

        for row in sec_cik_counts.iter_rows(named=True):
            alert_id = hashlib.sha256(f"{row['SECURITY_ID']}_multicik".encode()).hexdigest()[:16]
            alerts.append(
                AnomalyAlert(
                    alert_id=f"alt_{alert_id}",
                    security_id=row["SECURITY_ID"],
                    ticker=row["tickers"][0] if row["tickers"] else None,
                    company_id=None,
                    cik=None,
                    date=row["min_date"],
                    anomaly_type="wrong_company",
                    detected_value=None,
                    current_value=None,
                    confidence=0.92,
                    metrics={
                        "issue": "Security mapped to multiple distinct CIKs",
                        "distinct_ciks": [str(c) for c in row["ciks"]],
                        "tickers": row["tickers"],
                        "date_span": f"{row['min_date']} to {row['max_date']}"
                    }
                )
            )

        return alerts

    @staticmethod
    def to_proposed_fixes(alerts: List[AnomalyAlert]) -> List[ProposedFix]:
        """Converts company association anomaly alerts into standard ProposedFix objects."""
        fixes = []
        for alert in alerts:
            fixes.append(
                ProposedFix(
                    fix_id=f"fix_{alert.alert_id.replace('alt_', '')}",
                    ticker=alert.ticker,
                    security_id=alert.security_id,
                    company_id=alert.company_id,
                    cik=alert.cik,
                    date=alert.date,
                    type="company_association",
                    field="COMPANY_ID",
                    current_value=None,
                    value=alert.detected_value,
                    action="create" if alert.anomaly_type == "missing_company" else "update",
                    confidence=alert.confidence,
                    source="algorithmic_anomaly",
                    supporting_evidence=alert.metrics.get("issue", "Company association issue")
                )
            )
        return fixes
