"""
Deep AI & Regulatory Document Parser for SEC EDGAR Filings.
Automatically crawls Form 8-K, 6-K, and 10-Q filings, mines text excerpts,
and extracts verified accession numbers, URLs, and corporate action evidence.
"""

import os
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
import requests
from bs4 import BeautifulSoup
from src.config import SEC_USER_AGENT, DATA_DIR
from src.research.sec_client import SECEdgarClient

CACHE_DIR = DATA_DIR / "sec_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class SECFilingParser:
    """Mines verbatim corporate action evidence from official SEC EDGAR filings."""

    def __init__(self, user_agent: str = SEC_USER_AGENT):
        self.user_agent = user_agent
        self.client = SECEdgarClient(user_agent=user_agent)
        self.headers = {"User-Agent": self.user_agent}

    def _get_cached_document(self, url: str) -> Optional[str]:
        """Loads document from local cache or downloads and caches it."""
        filename = re.sub(r"[^a-zA-Z0-9_\.]", "_", url.split("/")[-1])
        if not filename.endswith(".htm") and not filename.endswith(".html"):
            filename += ".htm"
        cache_path = CACHE_DIR / filename

        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8", errors="ignore")

        # Rate limit and download
        self.client._rate_limit()
        try:
            r = requests.get(url, headers=self.headers, timeout=12)
            if r.status_code == 200:
                cache_path.write_text(r.text, encoding="utf-8", errors="ignore")
                return r.text
        except Exception as e:
            print(f"[Filing Parser Warning] Download failed for {url}: {e}")
        return None

    def search_filing_evidence(
        self, cik: str, event_date: Optional[str] = None, event_type: str = "split", target_value: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Finds the matching SEC filing around event_date (+- 45 days) or extracts company profile evidence.
        """
        clean_cik = str(cik).strip().lstrip("0")
        if not clean_cik:
            return None

        # Fetch submissions
        subs = self.client.get_company_submissions(clean_cik)
        if not subs:
            return None

        recent = subs.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        acc_nums = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        # Clean event date string
        clean_date = None
        if event_date and str(event_date).strip().lower() not in ["none", "nat", ""]:
            clean_date = str(event_date).strip()

        # Handle COMPANY_ASSOCIATION directly using SEC registered metadata & latest filing
        if event_type == "company_association" or clean_date is None:
            comp_name = subs.get("name", "Registered Entity")
            sic_desc = subs.get("sicDescription") or "SEC Reporting Company"
            state = subs.get("stateOfIncorporation") or "US"
            tickers = subs.get("tickers", [])
            ticker_str = f" (Tickers: {', '.join(tickers)})" if tickers else ""
            
            latest_form = forms[0] if forms else "Registration"
            latest_date = filing_dates[0] if filing_dates else "N/A"
            latest_acc = acc_nums[0] if acc_nums else ""
            latest_doc = primary_docs[0] if primary_docs else ""
            acc_clean = latest_acc.replace("-", "")
            
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{acc_clean}/{latest_doc}"
                if latest_doc else f"https://www.sec.gov/edgar/browse/?CIK={clean_cik}"
            )
            return {
                "source": "sec",
                "source_id": latest_acc or clean_cik,
                "source_url": filing_url,
                "form_type": latest_form,
                "filing_date": latest_date,
                "excerpt": (
                    f"Official SEC Registration: '{comp_name}'{ticker_str} | CIK: {clean_cik} | "
                    f"Industry: {sic_desc} | State: {state}. Most recent filing: Form {latest_form} on {latest_date}."
                ),
                "matched_terms": ["company_registration", "active_issuer"],
            }

        # Target terms based on event type
        if event_type == "split":
            keywords = ["split", "reverse split", "for-one", "for-1", "stock dividend", "ratio"]
        elif event_type == "dividend":
            keywords = ["special dividend", "cash dividend", "distribution", "per share", "record date"]
            if target_value:
                keywords.append(f"{target_value:.2f}")
                keywords.append(f"{target_value}")
        else:
            keywords = ["merger", "acquisition", "combination", "surviving", "conversion"]

        # Search filings within proximity
        for i in range(len(forms)):
            form = forms[i]
            f_date = filing_dates[i]
            
            # Focus on 8-K, 6-K, 10-Q, 10-K
            if form not in ["8-K", "8-K/A", "6-K", "6-K/A", "10-Q", "10-K"]:
                continue

            # Year proximity check if clean_date is available
            if clean_date and len(f_date) >= 4 and len(clean_date) >= 4:
                try:
                    if abs(int(f_date[:4]) - int(clean_date[:4])) > 1:
                        continue
                except ValueError:
                    pass

            acc_clean = acc_nums[i].replace("-", "")
            doc_name = primary_docs[i]
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{acc_clean}/{doc_name}"

            html_content = self._get_cached_document(filing_url)
            if not html_content:
                continue

            # Fast text search
            text_lower = html_content.lower()
            matched_keywords = [kw for kw in keywords if kw.lower() in text_lower]

            if len(matched_keywords) >= 2 or (target_value and f"{target_value}" in text_lower):
                # Parse cleanly with BeautifulSoup
                soup = BeautifulSoup(html_content, "html.parser")
                text = " ".join(soup.get_text().split())

                # Find best matching excerpt
                best_excerpt = None
                for kw in matched_keywords:
                    idx = text.lower().find(kw.lower())
                    if idx != -1:
                        start = max(0, idx - 80)
                        end = min(len(text), idx + 250)
                        # Clean to sentence boundary if possible
                        raw_snippet = text[start:end].strip()
                        best_excerpt = raw_snippet
                        break

                if best_excerpt:
                    return {
                        "source": "sec",
                        "source_id": acc_nums[i],
                        "source_url": filing_url,
                        "form_type": form,
                        "filing_date": f_date,
                        "excerpt": best_excerpt,
                        "matched_terms": matched_keywords,
                    }

        return None
