"""
Streamlit Analyst Review Dashboard for Corporate Action Integrity and Repair.
Allows human analysts to:
1. Review flagged anomalies and structured proposed fixes.
2. Inspect price context and supporting evidence.
3. Approve, reject, or comment on proposed patches with complete audit logging.
4. Export approved patches for automated database ingestion.
"""

import os
import json
from pathlib import Path
import streamlit as st
import pandas as pd

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
FIXES_FILE = BASE_DIR / "data" / "output" / "proposed_fixes" / "proposed_fixes.json"
AUDIT_LOG_FILE = BASE_DIR / "data" / "output" / "review_audit_log.json"

st.set_page_config(
    page_title="Corporate Action Repair System",
    page_icon="⚖️",
    layout="wide",
)

st.title("⚖️ Corporate Action Integrity & Repair System")
st.markdown("Automated historical data cleanup and ongoing data-quality monitoring for US equities and OTC securities.")


def load_fixes():
    if not FIXES_FILE.exists():
        st.warning(f"No fixes file found at `{FIXES_FILE}`. Please run `python -m src.pipeline` first.")
        return []
    with open(FIXES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_fixes(fixes):
    with open(FIXES_FILE, "w", encoding="utf-8") as f:
        json.dump(fixes, f, indent=2)


def load_audit_log():
    if not AUDIT_LOG_FILE.exists():
        return []
    with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def append_audit_log(entry):
    logs = load_audit_log()
    logs.append(entry)
    with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)


fixes = load_fixes()

if not fixes:
    st.info("Run the detection pipeline to generate proposed fixes:\n\n```powershell\npython -m src.pipeline --limit-files 5\n```")
    st.stop()

df = pd.DataFrame(fixes)

# Top KPI metrics
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Proposed Fixes", f"{len(df):,}")
c2.metric("Split Fixes", f"{(df['type'] == 'split').sum():,}")
c3.metric("Dividend Fixes", f"{(df['type'] == 'dividend').sum():,}")
c4.metric("Company Links", f"{(df['type'] == 'company_association').sum():,}")
pending_count = (df['status'] == 'pending_review').sum()
c5.metric("Pending Review", f"{pending_count:,}")

# Sidebar Filters
st.sidebar.header("🔍 Filter Proposed Fixes")
type_filter = st.sidebar.multiselect("Event Type", options=df["type"].unique(), default=df["type"].unique())
status_filter = st.sidebar.multiselect("Review Status", options=df["status"].unique(), default=df["status"].unique())
min_conf = st.sidebar.slider("Minimum Confidence", 0.0, 1.0, 0.85, 0.05)
ticker_search = st.sidebar.text_input("Search Ticker", "").strip().upper()

# Apply filters
filtered_df = df[
    df["type"].isin(type_filter) &
    df["status"].isin(status_filter) &
    (df["confidence"] >= min_conf)
]
if ticker_search:
    filtered_df = filtered_df[filtered_df["ticker"].str.contains(ticker_search, na=False)]

st.markdown(f"**Showing {len(filtered_df):,} matching proposed fixes:**")

tab1, tab2, tab3 = st.tabs(["📋 Review Queue", "📊 Statistical Overview", "💾 Export Approved Patches"])

with tab1:
    display_cols = ["fix_id", "ticker", "date", "type", "field", "current_value", "value", "confidence", "status"]
    st.dataframe(filtered_df[display_cols], use_container_width=True, height=300)

    st.markdown("---")
    st.subheader("🧐 Inspect & Approve Proposed Fix")
    
    if not filtered_df.empty:
        selected_fix_id = st.selectbox(
            "Select Fix ID to Review:",
            options=filtered_df["fix_id"].tolist(),
            format_func=lambda x: f"{x} - {filtered_df.loc[filtered_df['fix_id'] == x, 'ticker'].values[0]} ({filtered_df.loc[filtered_df['fix_id'] == x, 'type'].values[0]}) on {filtered_df.loc[filtered_df['fix_id'] == x, 'date'].values[0]}"
        )

        selected_row = filtered_df[filtered_df["fix_id"] == selected_fix_id].iloc[0].to_dict()

        col_a, col_b = st.columns([1, 1])
        with col_a:
            st.json(selected_row)
        
        with col_b:
            st.markdown(f"### Proposed Correction Details")
            st.write(f"**Ticker:** `{selected_row.get('ticker')}` | **Security ID:** `{selected_row.get('security_id')}`")
            st.write(f"**Target Column:** `{selected_row.get('field')}`")
            st.write(f"**Current Value:** `{selected_row.get('current_value')}` ➡️ **Proposed Value:** `{selected_row.get('value')}`")
            st.write(f"**Confidence:** `{selected_row.get('confidence')}`")
            st.write(f"**Evidence:** {selected_row.get('supporting_evidence')}")

            cik = selected_row.get("cik")
            if cik:
                clean_cik = str(cik).lstrip("0")
                sec_url = f"https://www.sec.gov/edgar/browse/?CIK={clean_cik}"
                st.markdown(f"🔗 [Open SEC EDGAR Filings for CIK {clean_cik}]({sec_url})")

            reviewer_name = st.text_input("Reviewer Name", "Analyst_1")
            review_notes = st.text_area("Review Notes", "")

            btn_col1, btn_col2 = st.columns(2)
            if btn_col1.button("✅ Approve Fix", use_container_width=True):
                # Update in memory and persist
                for item in fixes:
                    if item["fix_id"] == selected_fix_id:
                        item["status"] = "approved"
                        item["reviewed_by"] = reviewer_name
                        item["review_notes"] = review_notes
                        break
                save_fixes(fixes)
                append_audit_log({
                    "fix_id": selected_fix_id,
                    "action": "approved",
                    "reviewer": reviewer_name,
                    "notes": review_notes
                })
                st.success(f"Fix {selected_fix_id} approved!")
                st.rerun()

            if btn_col2.button("❌ Reject Fix", use_container_width=True):
                for item in fixes:
                    if item["fix_id"] == selected_fix_id:
                        item["status"] = "rejected"
                        item["reviewed_by"] = reviewer_name
                        item["review_notes"] = review_notes
                        break
                save_fixes(fixes)
                append_audit_log({
                    "fix_id": selected_fix_id,
                    "action": "rejected",
                    "reviewer": reviewer_name,
                    "notes": review_notes
                })
                st.warning(f"Fix {selected_fix_id} rejected.")
                st.rerun()

with tab2:
    st.subheader("Distribution by Event Type")
    type_counts = df["type"].value_counts()
    st.bar_chart(type_counts)

    st.subheader("Confidence Scores Distribution")
    st.area_chart(df["confidence"].value_counts().sort_index())

with tab3:
    st.subheader("Export Verified Fixes")
    approved_df = df[df["status"] == "approved"]
    st.write(f"Total Approved Patches Ready for Ingestion: **{len(approved_df)}**")

    if not approved_df.empty:
        json_str = approved_df.to_json(orient="records", indent=2)
        st.download_button(
            label="📥 Download Approved Fixes (JSON)",
            data=json_str,
            file_name="approved_fixes.json",
            mime="application/json"
        )
        csv_str = approved_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Approved Fixes (CSV)",
            data=csv_str,
            file_name="approved_fixes.csv",
            mime="text/csv"
        )
    else:
        st.info("No fixes have been approved yet. Use the Review Queue to verify and approve fixes.")
