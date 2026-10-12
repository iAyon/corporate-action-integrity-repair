"""
Configuration module for the Corporate Action Integrity and Repair System.
Defines project paths, external API constants, and detection parameters.
"""

from pathlib import Path
import os

# Root Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Data Directories
DATA_DIR = BASE_DIR / "data"
RAW_ZIP_DIR = BASE_DIR  # The zip files are currently stored directly in workspace root
PARQUET_DIR = DATA_DIR / "parquet"
OUTPUT_DIR = DATA_DIR / "output"
PROPOSED_FIXES_DIR = OUTPUT_DIR / "proposed_fixes"
REPORTS_DIR = OUTPUT_DIR / "reports"

# Ensure runtime directories exist
PARQUET_DIR.mkdir(parents=True, exist_ok=True)
PROPOSED_FIXES_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Schema Specifications
CSV_SCHEMA_OVERRIDES = {
    "CIK": "String",
    "DATE": "String",
    "SPLIT_RATIO": "Float64",
    "EX_DIVIDEND": "Float64",
    "OPEN": "Float64",
    "HIGH": "Float64",
    "LOW": "Float64",
    "CLOSE": "Float64",
    "VOLUME": "Float64",
    "ADJ_OPEN": "Float64",
    "ADJ_HIGH": "Float64",
    "ADJ_LOW": "Float64",
    "ADJ_CLOSE": "Float64",
    "ADJ_VOLUME": "Float64",
    "ADJ_FACTOR": "Float64",
    "CHANGE": "Float64",
    "PERCENT_CHANGE": "Float64",
}

# Detection Parameters
SPLIT_DETECTION_CONFIG = {
    # Typical split price ratios (Target Price / Previous Price)
    # Ratio = 0.50 => 2-for-1 split (value = 2.0)
    # Ratio = 0.333 => 3-for-1 split (value = 3.0)
    # Ratio = 0.25 => 4-for-1 split (value = 4.0)
    # Ratio = 2.0 => 1-for-2 reverse split (value = 0.5)
    # Ratio = 5.0 => 1-for-5 reverse split (value = 0.2)
    # Ratio = 10.0 => 1-for-10 reverse split (value = 0.1)
    "min_price_threshold": 0.50,  # Minimum previous close to avoid micro-penny volatility false positives
    "split_targets": [
        {"ratio": 0.50, "split_ratio": 2.0, "tolerance": 0.05, "label": "2:1 forward split"},
        {"ratio": 0.3333, "split_ratio": 3.0, "tolerance": 0.04, "label": "3:1 forward split"},
        {"ratio": 0.25, "split_ratio": 4.0, "tolerance": 0.03, "label": "4:1 forward split"},
        {"ratio": 0.20, "split_ratio": 5.0, "tolerance": 0.025, "label": "5:1 forward split"},
        {"ratio": 0.10, "split_ratio": 10.0, "tolerance": 0.015, "label": "10:1 forward split"},
        {"ratio": 2.00, "split_ratio": 0.5, "tolerance": 0.10, "label": "1:2 reverse split"},
        {"ratio": 5.00, "split_ratio": 0.2, "tolerance": 0.20, "label": "1:5 reverse split"},
        {"ratio": 10.00, "split_ratio": 0.1, "tolerance": 0.40, "label": "1:10 reverse split"},
    ],
}

# SEC EDGAR Config
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "CapstoneProjectTeam/1.0 (academic_research@university.edu)")
INTRINIO_API_KEY = os.getenv("INTRINIO_API_KEY", "")
