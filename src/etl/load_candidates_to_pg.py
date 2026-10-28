"""
Loader script to upload Matt's flagged candidate records (14,187 cases)
from Excel directly into the Intrinio AWS RDS PostgreSQL database (schema: columbia).
"""

import os
from pathlib import Path
import pandas as pd
import numpy as np
from psycopg2.extras import execute_values
from src.etl.db import get_db_connection, PG_SCHEMA
from src.config import DATA_DIR

EXCEL_PATH = DATA_DIR / "Intrinio_flagged_records_2026-10-27.xlsx"


def create_tables(conn):
    """Creates flagged_candidates and proposed_fixes tables in PostgreSQL."""
    cur = conn.cursor()
    
    # 1. Flagged Candidates table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.flagged_candidates (
            case_id VARCHAR(64) PRIMARY KEY,
            rule_id VARCHAR(64),
            check_type VARCHAR(64),
            ticker VARCHAR(32),
            security_id VARCHAR(32),
            company_id VARCHAR(32),
            company_name TEXT,
            record_date DATE,
            previous_record_date DATE,
            previous_close NUMERIC,
            close_price NUMERIC,
            dividend NUMERIC,
            split_ratio NUMERIC,
            field_to_check VARCHAR(64),
            recorded_value NUMERIC,
            cik VARCHAR(32),
            volume NUMERIC,
            open_price NUMERIC,
            high_price NUMERIC,
            low_price NUMERIC,
            source_file VARCHAR(128),
            source_data_record BIGINT,
            why_flagged TEXT,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_fc_ticker ON {PG_SCHEMA}.flagged_candidates (ticker);
        CREATE INDEX IF NOT EXISTS idx_fc_security ON {PG_SCHEMA}.flagged_candidates (security_id);
        CREATE INDEX IF NOT EXISTS idx_fc_check ON {PG_SCHEMA}.flagged_candidates (check_type);
        CREATE INDEX IF NOT EXISTS idx_fc_date ON {PG_SCHEMA}.flagged_candidates (record_date);
    """)

    # 2. Proposed Fixes table
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.proposed_fixes (
            fix_id VARCHAR(64) PRIMARY KEY,
            case_id VARCHAR(64) REFERENCES {PG_SCHEMA}.flagged_candidates(case_id),
            ticker VARCHAR(32),
            security_id VARCHAR(32),
            company_id VARCHAR(32),
            cik VARCHAR(32),
            date DATE,
            fix_type VARCHAR(32),
            target_field VARCHAR(32),
            current_value TEXT,
            proposed_value TEXT,
            action VARCHAR(16),
            confidence NUMERIC(5, 4),
            verdict VARCHAR(64),
            explanation TEXT,
            source VARCHAR(64),
            source_url TEXT,
            status VARCHAR(32) DEFAULT 'pending_review',
            reviewed_by VARCHAR(64),
            review_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_pf_case ON {PG_SCHEMA}.proposed_fixes (case_id);
        CREATE INDEX IF NOT EXISTS idx_pf_status ON {PG_SCHEMA}.proposed_fixes (status);
        CREATE INDEX IF NOT EXISTS idx_pf_ticker ON {PG_SCHEMA}.proposed_fixes (ticker);
    """)

    conn.commit()
    cur.close()
    print(f"[OK] Verified/created {PG_SCHEMA}.flagged_candidates and {PG_SCHEMA}.proposed_fixes")


def load_candidates():
    """Reads Excel and bulk inserts into PostgreSQL."""
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(f"Excel file not found at {EXCEL_PATH}")

    print(f"Reading {EXCEL_PATH.name} (Candidates sheet)...")
    # Header is at row index 5
    df = pd.read_excel(EXCEL_PATH, sheet_name="Candidates", header=5)
    print(f"Read {len(df):,} candidate rows.")

    # Clean and rename columns to match DB schema
    column_mapping = {
        "Case ID": "case_id",
        "Rule ID": "rule_id",
        "Check": "check_type",
        "Ticker": "ticker",
        "Security ID": "security_id",
        "Company ID": "company_id",
        "Company / security name": "company_name",
        "Record date": "record_date",
        "Previous record date": "previous_record_date",
        "Previous close": "previous_close",
        "Close": "close_price",
        "Dividend": "dividend",
        "Split ratio": "split_ratio",
        "Field to check": "field_to_check",
        "Recorded value": "recorded_value",
        "CIK": "cik",
        "Volume": "volume",
        "Open": "open_price",
        "High": "high_price",
        "Low": "low_price",
        "Source file": "source_file",
        "Source data record": "source_data_record",
        "Why flagged": "why_flagged",
        "Comment (optional)": "comment",
    }
    df = df.rename(columns=column_mapping)

    # Standardize data types
    def clean_date(val):
        if pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nat":
            return None
        return pd.to_datetime(val).strftime("%Y-%m-%d")

    df["record_date"] = df["record_date"].apply(clean_date)
    df["previous_record_date"] = df["previous_record_date"].apply(clean_date)
    
    # CIK to string without decimal
    def clean_cik(val):
        if pd.isna(val):
            return None
        try:
            return str(int(float(val))).zfill(10)
        except Exception:
            return str(val)

    df["cik"] = df["cik"].apply(clean_cik)

    # Replace NaNs with None for SQL NULLs
    df = df.replace({np.nan: None})

    # Prepare rows for insertion
    cols = [
        "case_id", "rule_id", "check_type", "ticker", "security_id",
        "company_id", "company_name", "record_date", "previous_record_date",
        "previous_close", "close_price", "dividend", "split_ratio",
        "field_to_check", "recorded_value", "cik", "volume",
        "open_price", "high_price", "low_price", "source_file",
        "source_data_record", "why_flagged", "comment"
    ]
    rows = df[cols].values.tolist()

    conn = get_db_connection()
    try:
        create_tables(conn)
        cur = conn.cursor()

        print(f"Upserting {len(rows):,} rows into {PG_SCHEMA}.flagged_candidates...")
        insert_sql = f"""
            INSERT INTO {PG_SCHEMA}.flagged_candidates ({', '.join(cols)})
            VALUES %s
            ON CONFLICT (case_id) DO UPDATE SET
                rule_id = EXCLUDED.rule_id,
                check_type = EXCLUDED.check_type,
                ticker = EXCLUDED.ticker,
                company_id = EXCLUDED.company_id,
                company_name = EXCLUDED.company_name,
                why_flagged = EXCLUDED.why_flagged,
                comment = EXCLUDED.comment;
        """
        execute_values(cur, insert_sql, rows, page_size=2000)
        conn.commit()

        # Query stats back from DB
        cur.execute(f"SELECT check_type, COUNT(*) FROM {PG_SCHEMA}.flagged_candidates GROUP BY check_type;")
        stats = cur.fetchall()
        print("\n[SUCCESS] Loaded into AWS RDS PostgreSQL:")
        for check, cnt in stats:
            print(f"  - {check}: {cnt:,} cases")

        cur.close()
    finally:
        conn.close()


if __name__ == "__main__":
    load_candidates()
