"""
Authoritative SEC EDGAR Client for corporate action verification.
Complies with SEC fair-access policy:
- Enforces max 10 requests per second.
- Custom User-Agent header (format: Sample Company Name AdminContact@<sample company domain>.com).
- Caching layer to avoid duplicate downloads.
"""

import time
import requests
from typing import Dict, Any, Optional, List
from src.config import SEC_USER_AGENT


class SECEdgarClient:
    """Client for querying SEC EDGAR company directory and filing metadata."""

    BASE_URL = "https://data.sec.gov"
    DIRECTORY_URL = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self, user_agent: str = SEC_USER_AGENT):
        self.user_agent = user_agent
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov"
        }
        self.last_request_time = 0.0
        self._ticker_cik_cache: Optional[Dict[str, Dict[str, Any]]] = None

    def _rate_limit(self):
        """Enforce maximum 10 requests per second (0.1s minimum delay between requests)."""
        elapsed = time.time() - self.last_request_time
        if elapsed < 0.12:
            time.sleep(0.12 - elapsed)
        self.last_request_time = time.time()

    def get_company_tickers_directory(self) -> Dict[str, Dict[str, Any]]:
        """
        Retrieves the official SEC mapping of Ticker -> CIK, Title.
        Returns a dict keyed by uppercase ticker.
        """
        if self._ticker_cik_cache is not None:
            return self._ticker_cik_cache

        self._rate_limit()
        headers = dict(self.headers)
        headers["Host"] = "www.sec.gov"
        response = requests.get(self.DIRECTORY_URL, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        mapping = {}
        for entry in data.values():
            ticker = entry["ticker"].upper()
            mapping[ticker] = {
                "cik": str(entry["cik_str"]).zfill(10),
                "title": entry["title"],
                "ticker": ticker
            }
        self._ticker_cik_cache = mapping
        return mapping

    def get_company_submissions(self, cik: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves recent filing metadata for a given CIK from SEC EDGAR.
        """
        clean_cik = str(cik).strip().lstrip("0").zfill(10)
        url = f"{self.BASE_URL}/submissions/CIK{clean_cik}.json"
        self._rate_limit()
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"[SEC Client Warning] Failed to fetch submissions for CIK {clean_cik}: {e}")
            return None

    def find_filings_for_date_range(
        self, cik: str, start_date: str, end_date: str, form_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Finds filings (e.g. 8-K, 10-Q, 6-K) for a company between start_date and end_date.
        """
        sub = self.get_company_submissions(cik)
        if not sub or "filings" not in sub or "recent" not in sub["filings"]:
            return []

        recent = sub["filings"]["recent"]
        results = []
        n_filings = len(recent.get("accessionNumber", []))

        for i in range(n_filings):
            filing_date = recent["filingDate"][i]
            form = recent["form"][i]
            
            if start_date <= filing_date <= end_date:
                if form_types is None or form in form_types:
                    acc_num = recent["accessionNumber"][i].replace("-", "")
                    doc_name = recent["primaryDocument"][i]
                    cik_num = str(cik).lstrip("0")
                    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_num}/{doc_name}"
                    
                    results.append({
                        "form": form,
                        "filing_date": filing_date,
                        "report_date": recent["reportDate"][i],
                        "accession_number": recent["accessionNumber"][i],
                        "primary_doc": doc_name,
                        "url": filing_url,
                        "items": recent.get("items", [""])[i] if "items" in recent else ""
                    })

        return results
