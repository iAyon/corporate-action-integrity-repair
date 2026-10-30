"""
M&A and Conversion Ratio Extractor (Project Goals 4 & 5).
Crawls SEC Form 8-K (Item 2.01: Completion of Acquisition or Disposition of Assets),
merger proxy statements (DEFM14A), and Form S-4 filings.
Mines:
- Acquirer entity name & ticker
- Cash consideration per share ($)
- Stock-for-stock exchange ratio
- Effective completion / delisting date
- Verbatim legal excerpt & SEC accession citations
"""

import re
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

from src.config import SEC_USER_AGENT
from src.research.sec_client import SECEdgarClient
from src.research.filing_parser import SECFilingParser


class MAMergerExtractor:
    """Mines and normalizes merger, acquisition, and conversion terms from SEC filings."""

    def __init__(self, user_agent: str = SEC_USER_AGENT):
        self.user_agent = user_agent
        self.client = SECEdgarClient(user_agent=user_agent)
        self.filing_parser = SECFilingParser(user_agent=user_agent)

    def extract_ma_terms_from_text(self, text: str) -> Dict[str, Any]:
        """
        Extracts cash per share, stock exchange ratio, and acquirer information
        from raw filing text using robust financial NLP regex patterns.
        """
        result = {
            "cash_per_share": 0.0,
            "stock_exchange_ratio": 0.0,
            "acquirer_name": None,
            "deal_type": "unknown",
            "extracted_sentences": []
        }

        # 1. Cash Consideration Pattern: e.g. "$95.00 in cash", "$12.50 per share in cash"
        cash_matches = re.findall(
            r"(?:receive|consideration of|payment of)?\s*[$]\s*([0-9]+(?:\.[0-9]{1,4})?)\s*(?:in cash|per share in cash|per share)",
            text, re.IGNORECASE
        )
        if cash_matches:
            # Filter out tiny par values (like $0.0001)
            valid_cash = [float(c) for c in cash_matches if float(c) >= 0.25]
            if valid_cash:
                result["cash_per_share"] = valid_cash[0]

        # 2. Stock Exchange Ratio Pattern: e.g. "0.5920 of a share of common stock", "exchange ratio of 0.25"
        ratio_matches = re.findall(
            r"(?:exchange ratio of|conversion ratio of|ratio of)?\s*([0-9]\.[0-9]{2,6})\s*(?:shares? of|of a share of)",
            text, re.IGNORECASE
        )
        if ratio_matches:
            result["stock_exchange_ratio"] = float(ratio_matches[0])

        # 3. Acquirer Entity Detection: e.g. "Merger Agreement with Microsoft Corporation", "merger with Chevron Corporation"
        acquirer_match = re.search(
            r"(?:merger(?: agreement)? with|transaction with|acquisition by|subsidiary of)\s+([A-Z][A-Za-z0-9&,\s\.]*?(?:Corporation|Corp\.?|Inc\.?|Company|Co\.?|LLC|Holdings|Limited|Ltd\.?))\b",
            text, re.IGNORECASE
        )
        if acquirer_match:
            result["acquirer_name"] = acquirer_match.group(1).strip(" ,")

        # Classify deal structure
        if result["cash_per_share"] > 0 and result["stock_exchange_ratio"] > 0:
            result["deal_type"] = "mixed_cash_and_stock"
        elif result["cash_per_share"] > 0:
            result["deal_type"] = "all_cash"
        elif result["stock_exchange_ratio"] > 0:
            result["deal_type"] = "all_stock"

        return result

    def search_merger_filing(self, cik: str, approx_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Searches SEC EDGAR for Form 8-K Item 2.01 filings or Form 25 (delisting)
        to identify M&A terms for the given target CIK.
        """
        clean_cik = str(cik).strip().lstrip("0")
        subs = self.client.get_company_submissions(clean_cik)
        if not subs:
            return None

        recent = subs.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        acc_nums = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        items_list = recent.get("items", [[] for _ in range(len(forms))])

        target_name = subs.get("name", "Target Entity")

        # Scan for Form 8-K filings (especially those with Item 2.01: Completion of Acquisition)
        for i in range(len(forms)):
            form = forms[i]
            f_date = filing_dates[i]
            items = items_list[i] if i < len(items_list) else []

            # Prioritize 8-K, 15-12G (termination), or 25 (delisting)
            if form not in ["8-K", "8-K/A", "25-NSE", "15-12G"]:
                continue

            # If approx_date is supplied, check year proximity
            if approx_date and len(approx_date) >= 4 and len(f_date) >= 4:
                try:
                    if abs(int(f_date[:4]) - int(approx_date[:4])) > 1:
                        continue
                except ValueError:
                    pass

            acc_clean = acc_nums[i].replace("-", "")
            doc_name = primary_docs[i]
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{acc_clean}/{doc_name}"

            html_content = self.filing_parser._get_cached_document(filing_url)
            if not html_content:
                continue

            text_lower = html_content.lower()
            if any(term in text_lower for term in ["merger consideration", "effective time", "merger agreement", "item 2.01", "consummated", "closing date"]):
                soup = BeautifulSoup(html_content, "html.parser")
                text = " ".join(soup.get_text().split())

                extracted = self.extract_ma_terms_from_text(text)
                
                # Find best summary sentence
                best_snippet = None
                for sentence in text.split(". "):
                    s_lower = sentence.lower()
                    if ("merger consideration" in s_lower or "converted into" in s_lower) and ("cash" in s_lower or "share" in s_lower):
                        best_snippet = sentence.strip() + "."
                        break
                
                if not best_snippet:
                    idx = text.lower().find("merger")
                    best_snippet = text[max(0, idx - 50):min(len(text), idx + 250)] if idx != -1 else text[:300]

                return {
                    "source": "sec",
                    "source_id": acc_nums[i],
                    "source_url": filing_url,
                    "form_type": form,
                    "filing_date": f_date,
                    "target_name": target_name,
                    "target_cik": clean_cik,
                    "acquirer_name": extracted["acquirer_name"],
                    "deal_type": extracted["deal_type"],
                    "cash_per_share": extracted["cash_per_share"],
                    "stock_exchange_ratio": extracted["stock_exchange_ratio"],
                    "excerpt": best_snippet,
                }

        return None
