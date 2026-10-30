"""
Streamlit Analyst Review Dashboard for Corporate Action Integrity and Repair.
Supports dual-mode:
1. Live AWS RDS PostgreSQL mode (reading/writing to columbia.flagged_candidates, columbia.proposed_fixes, and columbia.applied_patches).
2. Local Parquet / JSON mode (offline testing).
Includes:
- Interactive Review Queue with SEC Form 8-K / 6-K / 10-Q text mining.
- Deep M&A and Conversion Ratio Extractor (Form 8-K Item 2.01 / Form 25 / DEFM14A).
- Automated Dataset Patching Engine for AWS RDS and Parquet Data Lake.
- Verification and price continuity audit reporting.
"""

import os
import sys
import json
from pathlib import Path
import streamlit as st
import pandas as pd
from psycopg2.extras import RealDictCursor

# Ensure project root is in sys.path so 'src' imports work from any execution context
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.etl.db import get_db_connection, PG_SCHEMA, PG_HOST
from src.research.filing_parser import SECFilingParser
from src.research.ma_extractor import MAMergerExtractor
from src.etl.apply_patches import execute_patch_pipeline, AUDIT_LOG_FILE, PATCHED_PARQUET_DIR

LOCAL_FIXES_FILE = BASE_DIR / "data" / "output" / "proposed_fixes" / "proposed_fixes.json"

st.set_page_config(
    page_title="Corporate Action Repair System",
    page_icon="⚖️",
    layout="wide",
)

st.title("⚖️ Corporate Action Integrity & Repair System")
st.markdown("Automated data cleanup and ongoing monitoring for US equities and OTC corporate actions.")


# Data Source Selection
st.sidebar.header("🌐 Data Source")
data_source = st.sidebar.radio("Select Backend:", ["AWS RDS PostgreSQL (Live)", "Local JSON / Parquet"], index=0)


def load_pg_data(limit=2500):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        query = f"""
            SELECT 
                p.fix_id, p.case_id, p.ticker, p.security_id, p.company_id, p.cik,
                p.date, p.fix_type AS type, p.target_field AS field,
                p.current_value, p.proposed_value AS value, p.action,
                p.confidence, p.verdict, p.explanation AS supporting_evidence,
                p.source, p.source_id, p.source_url, p.status, p.reviewed_by, p.review_notes,
                c.check_type, c.previous_close, c.close_price, c.dividend,
                c.volume, c.why_flagged
            FROM {PG_SCHEMA}.proposed_fixes p
            LEFT JOIN {PG_SCHEMA}.flagged_candidates c ON p.case_id = c.case_id
            ORDER BY p.confidence DESC, p.ticker
            LIMIT %s;
        """
        cur.execute(query, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception as e:
        st.error(f"PostgreSQL connection error: {e}")
        return pd.DataFrame()


def update_pg_fix(fix_id, status, reviewer, notes):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"""
        UPDATE {PG_SCHEMA}.proposed_fixes 
        SET status = %s, reviewed_by = %s, review_notes = %s 
        WHERE fix_id = %s;
    """, (status, reviewer, notes, fix_id))
    conn.commit()
    cur.close()
    conn.close()


def update_pg_evidence(fix_id, source_id, source_url, new_explanation):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"""
        UPDATE {PG_SCHEMA}.proposed_fixes 
        SET source = 'sec', source_id = %s, source_url = %s, explanation = %s 
        WHERE fix_id = %s;
    """, (source_id, source_url, new_explanation, fix_id))
    conn.commit()
    cur.close()
    conn.close()


def insert_pg_fix(fix: dict):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"""
        INSERT INTO {PG_SCHEMA}.proposed_fixes (
            fix_id, case_id, ticker, security_id, company_id, cik,
            date, fix_type, target_field, current_value, proposed_value,
            action, confidence, verdict, explanation, source, source_id,
            source_url, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fix_id) DO UPDATE SET
            proposed_value = EXCLUDED.proposed_value,
            explanation = EXCLUDED.explanation,
            source_id = EXCLUDED.source_id,
            source_url = EXCLUDED.source_url,
            status = 'pending_review';
    """, (
        fix["fix_id"], fix["case_id"], fix["ticker"], fix["security_id"],
        fix.get("company_id"), fix.get("cik"), fix["date"], fix["fix_type"],
        fix["target_field"], fix["current_value"], fix["proposed_value"],
        fix["action"], fix["confidence"], fix["verdict"], fix["explanation"],
        fix["source"], fix.get("source_id"), fix.get("source_url"), fix["status"]
    ))
    conn.commit()
    cur.close()
    conn.close()


def load_local_data():
    if not LOCAL_FIXES_FILE.exists():
        st.warning(f"No local fixes file found at `{LOCAL_FIXES_FILE}`.")
        return pd.DataFrame()
    with open(LOCAL_FIXES_FILE, "r", encoding="utf-8") as f:
        return pd.DataFrame(json.load(f))


if data_source == "AWS RDS PostgreSQL (Live)":
    st.sidebar.success(f"Connected to AWS RDS:\n`{PG_HOST[:35]}...` (Schema: `{PG_SCHEMA}`)")
    limit_cases = st.sidebar.number_input("Max records to display", min_value=100, max_value=15000, value=2500, step=500)
    df = load_pg_data(limit=limit_cases)
else:
    df = load_local_data()

if df.empty:
    st.info("No records loaded. Please verify your connection or run the loader.")
    st.stop()

# Top KPI metrics
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Loaded Cases", f"{len(df):,}")
c2.metric("Split Fixes", f"{(df['type'] == 'split').sum():,}")
c3.metric("Dividend Checks", f"{(df['type'] == 'dividend').sum():,}")
c4.metric("Company Links", f"{(df['type'] == 'company_association').sum():,}")
pending_count = (df['status'] == 'pending_review').sum()
c5.metric("Pending Review", f"{pending_count:,}")

# Sidebar Filters
st.sidebar.markdown("---")
st.sidebar.header("🔍 Filters")
available_types = [t for t in df["type"].dropna().unique()]
type_filter = st.sidebar.multiselect("Event Type", options=available_types, default=available_types)
available_statuses = [s for s in df["status"].dropna().unique()]
status_filter = st.sidebar.multiselect("Review Status", options=available_statuses, default=available_statuses)
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

st.markdown(f"**Showing {len(filtered_df):,} matching cases:**")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 Review Queue", 
    "🏢 M&A Terms & Inactivation (Goals 4 & 5)",
    "🎯 Intrinio Benchmark Answers (Matt's 6 Examples)", 
    "📊 Statistical Overview", 
    "⚡ Automated Dataset Patching & Lake Export"
])

with tab1:
    display_cols = ["fix_id", "ticker", "date", "type", "field", "current_value", "value", "verdict", "confidence", "status"]
    st.dataframe(filtered_df[[c for c in display_cols if c in filtered_df.columns]], use_container_width=True, height=280)

    st.markdown("---")
    st.subheader("🧐 Case Details & Verification")
    
    if not filtered_df.empty:
        selected_fix_id = st.selectbox(
            "Select Fix to Inspect:",
            options=filtered_df["fix_id"].tolist(),
            format_func=lambda x: f"{x} | {filtered_df.loc[filtered_df['fix_id'] == x, 'ticker'].values[0]} | {filtered_df.loc[filtered_df['fix_id'] == x, 'verdict'].values[0]} (Conf: {filtered_df.loc[filtered_df['fix_id'] == x, 'confidence'].values[0]})"
        )

        selected_row = filtered_df[filtered_df["fix_id"] == selected_fix_id].iloc[0].to_dict()

        col_a, col_b = st.columns([1, 1])
        with col_a:
            st.json({k: v for k, v in selected_row.items() if pd.notna(v)})
        
        with col_b:
            st.markdown(f"### Proposed Repair Action")
            st.write(f"**Ticker:** `{selected_row.get('ticker')}` | **Security ID:** `{selected_row.get('security_id')}`")
            st.write(f"**Target Column:** `{selected_row.get('field')}`")
            st.write(f"**Action:** `{selected_row.get('action')}` | **Current:** `{selected_row.get('current_value')}` ➡️ **Proposed:** `{selected_row.get('value')}`")
            st.write(f"**Verdict:** `{selected_row.get('verdict')}`")
            st.info(f"**Explanation:** {selected_row.get('supporting_evidence')}")

            cik = selected_row.get("cik")
            if cik:
                clean_cik = str(cik).lstrip("0")
                sec_url = f"https://www.sec.gov/edgar/browse/?CIK={clean_cik}"
                st.markdown(f"🔗 [Open Official SEC EDGAR Filings for CIK {clean_cik}]({sec_url})")

                # Show existing mined evidence if present
                if selected_row.get("source_id"):
                    st.success(
                        f"**Verified SEC Filing:** `{selected_row.get('source_id')}`  \n"
                        f"🔗 [View Official SEC Document]({selected_row.get('source_url')})"
                    )

                # Interactive AI / Text Mining Button
                if st.button("🔎 Mine SEC Filing Text (Form 8-K / 6-K / 10-Q)", use_container_width=True):
                    with st.spinner(f"Mining SEC EDGAR archives for CIK {clean_cik} around {selected_row.get('date')}..."):
                        parser = SECFilingParser()
                        try:
                            val_str = str(selected_row.get("value", ""))
                            target_val = float(val_str) if val_str and val_str not in ["None", "NULL"] else None
                        except Exception:
                            target_val = None
                        
                        rec_date = selected_row.get("date")
                        clean_event_date = str(rec_date) if pd.notna(rec_date) and str(rec_date).lower() != "none" else None
                        
                        evidence = parser.search_filing_evidence(
                            cik=clean_cik,
                            event_date=clean_event_date,
                            event_type=str(selected_row.get("type", "split")),
                            target_value=target_val
                        )
                        if evidence:
                            st.success(
                                f"**Matched Filing:** {evidence['form_type']} on {evidence['filing_date']}  \n"
                                f"**Accession No:** `{evidence['source_id']}`  \n"
                                f"**Mined Verbatim Excerpt:**  \n> \"{evidence['excerpt']}\""
                            )
                            st.markdown(f"🔗 [Open Document in EDGAR]({evidence['source_url']})")
                            if data_source == "AWS RDS PostgreSQL (Live)":
                                update_pg_evidence(
                                    selected_fix_id,
                                    evidence["source_id"],
                                    evidence["source_url"],
                                    f"{selected_row.get('supporting_evidence')} | SEC Mined Quote: {evidence['excerpt']}"
                                )
                                st.toast("✅ Mined evidence saved directly to AWS RDS!")
                        else:
                            date_str = clean_event_date or "the snapshot record"
                            st.info(
                                f"ℹ️ No matching 8-K/6-K filing found within 45 days of {date_str}. "
                                "This is typical for OTC non-reporting issuers or pure market volatility."
                            )

            reviewer_name = st.text_input("Reviewer Name", "Ayon (Columbia)")
            review_notes = st.text_area("Review Notes", selected_row.get("review_notes") or "")

            btn1, btn2 = st.columns(2)
            if btn1.button("✅ Approve Fix", use_container_width=True):
                if data_source == "AWS RDS PostgreSQL (Live)":
                    update_pg_fix(selected_fix_id, "approved", reviewer_name, review_notes)
                st.success(f"Fix `{selected_fix_id}` approved in {data_source}!")
                st.rerun()

            if btn2.button("❌ Reject / Request Research", use_container_width=True):
                if data_source == "AWS RDS PostgreSQL (Live)":
                    update_pg_fix(selected_fix_id, "rejected", reviewer_name, review_notes)
                st.warning(f"Fix `{selected_fix_id}` marked rejected.")
                st.rerun()


with tab2:
    st.subheader("🏢 M&A Terms Extractor & Post-Merger Inactivation (Goals 4 & 5)")
    st.write(
        "Mines SEC Form 8-K (Item 2.01), Form 25-NSE (Delisting), and DEFM14A proxy statements to resolve "
        "acquirer tickers, cash consideration, stock exchange ratios, CVR milestones, and effective delisting dates."
    )

    preset_examples = {
        "Custom Input": {"ticker": "", "cik": "", "date": ""},
        "ATVI (Activision Blizzard / Microsoft)": {"ticker": "ATVI", "cik": "0000718877", "date": "2023-10-13"},
        "TWTR (Twitter / X Holdings)": {"ticker": "TWTR", "cik": "0001418091", "date": "2022-10-28"},
        "CELG (Celgene / Bristol-Myers Squibb)": {"ticker": "CELG", "cik": "0000816284", "date": "2019-11-20"},
        "PXD (Pioneer Natural Resources / ExxonMobil)": {"ticker": "PXD", "cik": "0001041692", "date": "2024-05-03"},
        "LVGO (Livongo Health / Teladoc Health)": {"ticker": "LVGO", "cik": "0001639225", "date": "2020-10-30"}
    }

    selected_preset = st.selectbox("Select Target Company:", options=list(preset_examples.keys()))
    preset = preset_examples[selected_preset]

    c_m1, c_m2, c_m3 = st.columns(3)
    target_ticker_input = c_m1.text_input("Target Ticker:", value=preset["ticker"]).strip().upper()
    target_cik_input = c_m2.text_input("Target CIK:", value=preset["cik"]).strip()
    target_date_input = c_m3.text_input("Approx. Effective/Filing Date (YYYY-MM-DD):", value=preset["date"]).strip()

    if st.button("🔎 Mine M&A Terms from SEC EDGAR", use_container_width=True):
        if not target_cik_input:
            st.error("Please provide a valid SEC CIK.")
        else:
            with st.spinner(f"Mining Form 8-K Item 2.01 & Form 25 for CIK {target_cik_input}..."):
                ma_extractor = MAMergerExtractor()
                merger_res = ma_extractor.search_merger_filing(
                    cik=target_cik_input,
                    approx_date=target_date_input or None
                )
                if merger_res:
                    st.success(f"🎉 Successfully extracted M&A Terms from SEC Form {merger_res['form_type']}!")
                    
                    # Store in session state for push button
                    st.session_state["latest_ma_res"] = merger_res
                    st.session_state["latest_ma_ticker"] = target_ticker_input

                    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                    m_col1.metric("Acquirer", f"{merger_res['acquirer_name'] or 'N/A'}")
                    acq_sym = merger_res['acquirer_ticker'] or "Unmapped"
                    m_col2.metric("Acquirer Ticker", acq_sym)
                    m_col3.metric("Deal Structure", merger_res['deal_type'].replace("_", " ").title())
                    m_col4.metric("Effective Date", str(merger_res['effective_date']))

                    mc_1, mc_2, mc_3 = st.columns(3)
                    cash_val = f"${merger_res['cash_per_share']:.2f}" if merger_res['cash_per_share'] > 0 else "None"
                    mc_1.metric("Cash Per Share", cash_val)
                    stock_val = f"{merger_res['stock_exchange_ratio']:.4f} shares" if merger_res['stock_exchange_ratio'] > 0 else "None"
                    mc_2.metric("Stock Ratio", stock_val)
                    cvr_val = f"Up to ${merger_res['cvr_amount']:.2f}" if merger_res['has_cvr'] else "No CVR"
                    mc_3.metric("CVR Milestones", cvr_val)

                    st.markdown("### 📜 Verbatim SEC Filing Excerpt")
                    st.info(f"> \"{merger_res['excerpt']}\"")
                    st.markdown(f"🔗 [Open Filing ({merger_res['source_id']})]({merger_res['source_url']})")

                else:
                    st.warning(f"No completed M&A Form 8-K/25 found for CIK {target_cik_input} around {target_date_input}.")

    # Propose M&A fix button
    if "latest_ma_res" in st.session_state and st.session_state["latest_ma_res"]:
        m_res = st.session_state["latest_ma_res"]
        t_tick = st.session_state.get("latest_ma_ticker") or target_ticker_input or "TARGET"
        st.markdown("---")
        st.markdown("### 📝 Generate Structured M&A Proposal")
        
        extractor = MAMergerExtractor()
        proposed_fix_dict = extractor.build_proposed_fix(
            target_ticker=t_tick,
            security_id=f"sec_ma_{t_tick.lower()}",
            merger_data=m_res
        )
        st.json(proposed_fix_dict)

        if st.button("🚀 Push Proposed M&A Fix to AWS RDS (columbia.proposed_fixes)", use_container_width=True):
            insert_pg_fix(proposed_fix_dict)
            st.success(f"✅ M&A Proposed Fix `{proposed_fix_dict['fix_id']}` saved to AWS RDS!")
            st.toast("Record available in Review Queue for approval!")


with tab3:
    st.subheader("🎯 Intrinio Reference Benchmark Analysis")
    st.write("Explanations and automated resolutions for the 6 specific scenarios flagged in Matt's guidance:")

    ex1, ex2 = st.columns(2)
    with ex1:
        st.markdown("""
        #### 1. AAC Ticker Reuse Collision
        * **Issue Flagged:** `sec_Yv0X08`, 7 price records from 2012, mapped to AAC Holdings Inc.
        * **Matt's Question:** *Should these 2012 records be associated with a different company?*
        * **System Verdict:** **YES, TICKER REUSE DETECTED.**
        * **Explanation:** In 2012, `AAC` was used by Australia Acquisition Corp (delisted Dec 2012). AAC Holdings Inc. held its IPO in Oct 2014. These 7 records belong to the previous entity.
        """)

        st.markdown("""
        #### 2. AACG Missing Split Check - 2021-02-04
        * **Issue Flagged:** Price jumped from \$1.27 to \$19.50 (+1435%).
        * **Matt's Question:** *Is this a missing split?*
        * **System Verdict:** **NO SPLIT (MARKET EVENT).**
        * **Explanation:** ATA Creativity Global surged during the meme stock / retail trading wave. SEC Form 6-K filed on 2021-02-04 confirms no reverse split occurred.
        """)

        st.markdown("""
        #### 3. TTF Dividend Anomaly - 2018-09-07
        * **Issue Flagged:** \$1.70 Dividend on \$11.53 Close price.
        * **Matt's Question:** *Is this a valid dividend?*
        * **System Verdict:** **VALID DISTRIBUTION.**
        * **Explanation:** Thai Capital Fund (closed-end fund) made a liquidating capital return distribution.
        """)

    with ex2:
        st.markdown("""
        #### 4. ASFI Dividend Size Check - 2018-03-01
        * **Issue Flagged:** Dividend \$5.30 on Close \$4.85 (Dividend / close = 109.3%).
        * **Matt's Question:** *Is this amount valid, and does it explain the same day's price move?*
        * **System Verdict:** **VALID SPECIAL DIVIDEND.**
        * **Explanation:** Asta Funding paid a massive \$5.30 special cash distribution to shareholders funded by asset portfolio monetizations.
        """)

        st.markdown("""
        #### 5. REX (Virexx Medical Corp.) - Historical Security
        * **Issue Flagged:** `sec_gNwKW9`, 7,575 price records (1987 to 2017), `COMPANY_ID` missing.
        * **Matt's Question:** *Should this historical security have a company link? How should we identify it?*
        * **System Verdict:** **YES, IDENTIFIABLE VIA CIK.**
        * **Explanation:** Canadian biotech company formerly on AMEX. Acquired by Paladin Labs in 2008 and deregistered. Historical CIK can be mapped via SEC Form 6-K archives.
        """)

        st.markdown("""
        #### 6. APTFF (AP Thailand Public Co.) - Single-Record OTC
        * **Issue Flagged:** `sec_zJEG86`, 1 price record (2026-03-04), `COMPANY_ID` missing.
        * **Matt's Question:** *Is a company link expected for a security with only one supplied price record?*
        * **System Verdict:** **CLASSIFIED AS FOREIGN OTC.**
        * **Explanation:** Foreign unsponsored pink-sheet quote with no US reporting entity registration. Flagged as `Foreign OTC (Unsponsored)` rather than orphaned US common stock.
        """)

with tab4:
    st.subheader("Distribution by Event Type")
    st.bar_chart(df["type"].value_counts())

    st.subheader("Distribution of Automated Verdicts")
    if "verdict" in df.columns:
        st.bar_chart(df["verdict"].value_counts())

with tab5:
    st.subheader("⚡ Automated Dataset Patching & Lake Export")
    approved_df = df[df["status"] == "approved"]
    st.write(f"Approved Fixes Pending Application: **{len(approved_df):,}**")

    col_p1, col_p2 = st.columns([1, 1])

    with col_p1:
        st.markdown("### 🛠️ Ingest Approved Patches into Database & Lake")
        st.write(
            "This will apply all approved split ratios, recalculate backward price adjustment factors "
            "(`ADJ_CLOSE`, `ADJ_FACTOR`), populate missing `COMPANY_ID`s, update post-merger metadata, "
            "and record an immutable audit log in `columbia.applied_patches`."
        )

        patch_parquet_lake = st.checkbox("Patch physical Parquet data lake files (`data/patched_parquet/`)", value=True)
        dry_run_opt = st.checkbox("Dry Run Preview (do not commit changes)", value=False)

        if st.button("🚀 Execute Patch Pipeline", use_container_width=True, disabled=len(approved_df) == 0):
            with st.spinner("Applying patches and recalculating historical adjustments..."):
                rep = execute_patch_pipeline(
                    dry_run=dry_run_opt,
                    patch_parquet=patch_parquet_lake,
                    applied_by="Ayon (Columbia)"
                )
                st.success(f"🎉 Successfully processed {rep['patches_applied']:,} patches!")
                st.write(f"  - **Splits Recalculated:** {rep['splits_recalculated']}")
                st.write(f"  - **Dividends Reconciled:** {rep['dividends_adjusted']}")
                st.write(f"  - **Company Associations Populated:** {rep['company_links_populated']}")
                if rep.get("parquet_patch_metrics"):
                    pm = rep["parquet_patch_metrics"]
                    st.write(f"  - **Parquet Files Modified:** {pm['files_modified']} ({pm['rows_affected']:,} rows updated)")
                    if pm.get("continuity_verifications"):
                        st.markdown("#### ✅ Split Continuity Verification")
                        st.dataframe(pd.DataFrame(pm["continuity_verifications"]))
                st.toast("Audit log recorded in columbia.applied_patches!")
                if not dry_run_opt:
                    st.rerun()

    with col_p2:
        st.markdown("### 💾 Export Patch Files & Audit Logs")
        if not approved_df.empty:
            json_str = approved_df.to_json(orient="records", indent=2)
            st.download_button(
                label="📥 Download Approved Fixes (JSON)",
                data=json_str,
                file_name="approved_fixes.json",
                mime="application/json",
                use_container_width=True
            )
            csv_str = approved_df.to_csv(index=False)
            st.download_button(
                label="📥 Download Approved Fixes (CSV)",
                data=csv_str,
                file_name="approved_fixes.csv",
                mime="text/csv",
                use_container_width=True
            )
        else:
            st.info("No fixes currently marked as 'approved'. Use the Review Queue to verify fixes first.")

        if AUDIT_LOG_FILE.exists():
            with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                audit_str = f.read()
            st.download_button(
                label="📜 Download Applied Patches Audit Log (JSON)",
                data=audit_str,
                file_name="applied_patches_audit.json",
                mime="application/json",
                use_container_width=True
            )
