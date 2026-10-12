"""
Pydantic data models for anomalies and structured proposed fixes.
Ensures consistency and machine-readability across all pipeline stages.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal
from datetime import datetime


class AnomalyAlert(BaseModel):
    """Represents an anomaly flagged by detection algorithms before external research."""
    alert_id: str = Field(..., description="Unique hash or ID for the alert")
    security_id: str
    ticker: Optional[str] = None
    company_id: Optional[str] = None
    cik: Optional[str] = None
    date: str
    anomaly_type: Literal[
        "missing_split",
        "bad_split_ratio",
        "missing_dividend",
        "anomalous_dividend",
        "missing_company",
        "wrong_company",
        "merger_metadata",
        "conversion_discrepancy"
    ]
    detected_value: Optional[float] = None
    current_value: Optional[float] = None
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic metrics like price_ratio, prev_close, close")
    confidence: float = Field(..., ge=0.0, le=1.0)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ProposedFix(BaseModel):
    """
    Standard structured proposed fix format adhering to project requirements:
    Be machine readable, consistent, and self-contained for automatic patch or human review.
    """
    fix_id: str = Field(..., description="Unique ID for this proposed fix")
    ticker: Optional[str] = None
    security_id: str
    company_id: Optional[str] = None
    cik: Optional[str] = None
    date: str
    type: Literal["split", "dividend", "company_association", "merger_acquisition", "conversion"]
    field: str = Field(..., description="Target database/CSV column, e.g. SPLIT_RATIO, COMPANY_ID, EX_DIVIDEND")
    current_value: Optional[Any] = None
    value: Any = Field(..., description="The proposed corrected value")
    action: Literal["create", "update", "delete"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: Literal["sec", "intrinio", "finra", "algorithmic_anomaly", "heuristic"]
    source_id: Optional[str] = Field(None, description="SEC accession number or filing ID")
    source_url: Optional[str] = Field(None, description="Link to authoritative filing or documentation")
    supporting_evidence: Optional[str] = Field(None, description="Excerpt or explanation supporting the correction")
    conflicting_evidence: Optional[str] = Field(None, description="Any counter-indications or ambiguities")
    status: Literal["pending_review", "approved", "rejected", "auto_applied"] = "pending_review"
    reviewed_by: Optional[str] = None
    review_notes: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
