# Corporate Action Integrity and Repair System

An automated historical data cleanup and ongoing data-quality monitoring engine for US equities and OTC corporate actions.

## 🚀 Key Features

1. **High-Speed Parquet Data Lake**: Direct streaming conversion from raw compressed CSV zips into snappy/zstd compressed Parquet tables via Polars, querying millions of rows in seconds.
2. **Multi-Tier Anomaly Detectors**:
   - **Goal 1 (Splits & Dividends)**: Mathematical price discontinuity ratio tests (identifies 2:1, 3:1, 4:1, and reverse splits where `SPLIT_RATIO == 1.0`), corrupted split ratios, and anomalous dividend yields.
   - **Goal 2 & 3 (Company Association)**: Detects missing company associations (`COMPANY_ID = NULL`) and entity collisions where a single security maps to multiple distinct CIKs.
3. **Structured Proposed Fix Output**: Machine-readable JSON records complete with diagnostic metrics, confidence scores, target field names, and supporting evidence.
4. **SEC EDGAR Authoritative Research Connector**: Fair-access compliant client (10 req/s, custom user agent) for pulling official Form 8-K, 10-Q, and 6-K filings.
5. **Interactive Analyst Review Dashboard**: Built in Streamlit with side-by-side diff inspection, one-click SEC filing lookup, approval/rejection audit logging, and patch export.

---

## 📁 Repository Structure

```text
Capstone Project/
├── .gitignore
├── requirements.txt
├── README.md
├── src/
│   ├── config.py                 # Paths, constants, and split detection parameters
│   ├── pipeline.py               # Full orchestration pipeline
│   ├── models/
│   │   └── schemas.py            # Pydantic schemas for AnomalyAlert & ProposedFix
│   ├── etl/
│   │   └── convert_to_parquet.py # Streaming CSV-to-Parquet conversion
│   ├── detectors/
│   │   ├── base.py               # Abstract BaseDetector interface
│   │   ├── split_detector.py     # Missing & bad split ratio detection
│   │   ├── dividend_detector.py  # Missing & extreme dividend detection
│   │   └── company_detector.py   # Missing & conflicting company links
│   └── research/
│       └── sec_client.py         # SEC EDGAR API connector
├── dashboard/
│   └── app.py                    # Streamlit human-in-the-loop review dashboard
├── tests/
│   └── test_split_detector.py    # Unit tests for split anomaly detection
└── data/
    ├── parquet/                  # Converted Parquet files (all 20 files indexed)
    └── output/                   # Generated proposed fixes & audit logs
```

---

## ⚡ Quickstart

### 1. Run Unit Tests
```powershell
python -m unittest tests/test_split_detector.py
```

### 2. Convert Raw CSV Zips to Parquet
All 20 raw zip files can be converted or refreshed with:
```powershell
python -m src.etl.convert_to_parquet
```

### 3. Run Detection & Generate Proposed Fixes
Run detection across Parquet files to produce machine-readable structured fixes:
```powershell
python -m src.pipeline --limit-files 5 --output proposed_fixes.json
```

### 4. Launch Analyst Review Dashboard
Launch the interactive Streamlit UI in your browser:
```powershell
streamlit run dashboard/app.py
```

---

## 📊 Sample Output Schema

Every proposed fix adheres to the standardized, machine-readable format:

```json
{
  "fix_id": "fix_9e8436ca210cc947",
  "ticker": "AVEO",
  "security_id": "sec_0XLjqy",
  "company_id": "com_z59amz",
  "cik": "0001325879",
  "date": "2013-05-02",
  "type": "split",
  "field": "SPLIT_RATIO",
  "current_value": 1.0,
  "value": 2.0,
  "action": "create",
  "confidence": 0.98,
  "source": "algorithmic_anomaly",
  "supporting_evidence": "Identified 2:1 forward split via overnight price movement: close dropped from $5.26 to $2.65 (ratio: 0.5038) while SPLIT_RATIO was 1.0.",
  "status": "pending_review"
}
```
