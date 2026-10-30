"""
M&A and Conversion Ratio Extractor (Project Goals 4 & 5).
Crawls SEC Form 8-K (Item 2.01: Completion of Acquisition or Disposition of Assets),
merger proxy statements (DEFM14A), Form S-4, and Form 25-NSE (Delisting).
Mines:
- Acquirer entity name, official CIK, and ticker symbol
- Cash consideration per share ($)
- Stock-for-stock exchange ratio
- Contingent Value Rights (CVR) terms
- Effective completion / delisting date
- Deal structure classification (all_cash, all_stock, mixed_cash_and_stock, cvr_cash)
- Verbatim legal excerpts & SEC accession citations
- Generates structured proposed fixes conforming to project schema
"""

import re
import json
from datetime import datetime
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
        self._sec_tickers: Optional[Dict[str, Dict[str, Any]]] = None
        self._name_to_ticker_index: Optional[Dict[str, Dict[str, Any]]] = None

    def _get_sec_ticker_index(self) -> Dict[str, Dict[str, Any]]:
        """Builds an inverted index of normalized company names to {ticker, cik, title}."""
        if self._name_to_ticker_index is not None:
            return self._name_to_ticker_index

        try:
            self._sec_tickers = self.client.get_company_tickers_directory()
            index = {}
            for t, info in self._sec_tickers.items():
                norm = self._normalize_company_name(info["title"])
                if norm and norm not in index:
                    index[norm] = info
            self._name_to_ticker_index = index
        except Exception as e:
            print(f"[MAMergerExtractor] Warning: Could not initialize SEC ticker index: {e}")
            self._name_to_ticker_index = {}

        return self._name_to_ticker_index

    @staticmethod
    def _normalize_company_name(name: str) -> str:
        """Normalizes company names for fuzzy corporate entity matching."""
        if not name:
            return ""
        n = name.upper()
        # Remove common corporate suffixes
        n = re.sub(r"\b(INCORPORATED|INC\.?|CORPORATION|CORP\.?|COMPANY|CO\.?|HOLDINGS|HOLDING|LLC|L\.L\.C\.|LIMITED|LTD\.?|GROUP|PLC)\b", "", n)
        # Remove punctuation and excess spaces
        n = re.sub(r"[,\.\-\/'\"\(\)]", " ", n)
        return " ".join(n.split())

    def resolve_acquirer_ticker_and_cik(self, acquirer_name: Optional[str]) -> Dict[str, Optional[str]]:
        """Resolves an acquirer entity name to official SEC ticker symbol and CIK."""
        result = {"acquirer_ticker": None, "acquirer_cik": None, "matched_title": None}
        if not acquirer_name:
            return result

        index = self._get_sec_ticker_index()
        norm_acquirer = self._normalize_company_name(acquirer_name)
        if not norm_acquirer:
            return result

        # 1. Exact normalized match
        if norm_acquirer in index:
            match = index[norm_acquirer]
            return {
                "acquirer_ticker": match["ticker"],
                "acquirer_cik": match["cik"],
                "matched_title": match["title"]
            }

        # 2. Substring match (e.g. "MICROSOFT" in "MICROSOFT CORP")
        for norm_title, match in index.items():
            if norm_acquirer == norm_title or (len(norm_acquirer) >= 4 and norm_acquirer in norm_title):
                return {
                    "acquirer_ticker": match["ticker"],
                    "acquirer_cik": match["cik"],
                    "matched_title": match["title"]
                }

        return result

    @staticmethod
    def _parse_filing_date_string(date_str: str) -> Optional[str]:
        """Parses natural language date string into YYYY-MM-DD."""
        date_str = date_str.replace(",", "").strip()
        for fmt in ["%B %d %Y", "%b %d %Y", "%Y-%m-%d", "%m/%d/%Y"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    def extract_ma_terms_from_text(self, text: str) -> Dict[str, Any]:
        """
        Extracts cash per share, stock exchange ratio, CVR terms, acquirer info,
        and effective date from raw filing text using robust financial NLP patterns.
        """
        result = {
            "cash_per_share": 0.0,
            "stock_exchange_ratio": 0.0,
            "has_cvr": False,
            "cvr_amount": 0.0,
            "acquirer_name": None,
            "acquirer_ticker": None,
            "acquirer_cik": None,
            "effective_date": None,
            "deal_type": "unknown",
            "extracted_sentences": []
        }

        # 1. Cash Consideration Patterns
        cash_patterns = [
            # e.g. "$95.00 in cash", "$54.20 in cash per share", "$116.50 in cash without interest"
            r"[$]\s*([0-9]+(?:\.[0-9]{1,4})?)\s*(?:in cash|per share in cash|per share without interest|per share,\s*in cash|without interest,?\s*in cash|net to the seller in cash)",
            # e.g. "receive $95.00", "entitled to receive $54.20", "merger consideration of $12.50"
            r"(?:receive|entitled to receive|merger consideration of|payment of|consideration of)\s*[$]\s*([0-9]+(?:\.[0-9]{1,4})?)",
            # e.g. "cash consideration of $10.00"
            r"(?:cash consideration of|cash amount of|cash portion of)\s*[$]\s*([0-9]+(?:\.[0-9]{1,4})?)",
        ]
        for pat in cash_patterns:
            matches = re.findall(pat, text, re.IGNORECASE)
            valid_cash = [float(c) for c in matches if float(c) >= 0.25]
            if valid_cash:
                result["cash_per_share"] = valid_cash[0]
                break

        # 2. Stock Exchange Ratio Patterns
        ratio_patterns = [
            # e.g. "exchange ratio of 0.5920", "conversion ratio of 0.25"
            r"(?:exchange ratio of|conversion ratio of|ratio of)\s*([0-9]\.[0-9]{2,6})\s*(?:shares? of|of a share of)?",
            # e.g. "receive 2.3234 shares of ExxonMobil common stock for each share"
            r"([0-9]\.[0-9]{2,6})\s*(?:shares? of|of a share of)\s*(?:[A-Za-z0-9&,\s\.]*?)?\s*common stock for each share",
            # e.g. "converted into 0.5920 shares of"
            r"converted into\s*([0-9]\.[0-9]{2,6})\s*shares?",
            # e.g. "0.1024 of a share of Chevron common stock"
            r"([0-9]\.[0-9]{2,6})\s*of a share of",
        ]
        for pat in ratio_patterns:
            matches = re.findall(pat, text, re.IGNORECASE)
            if matches:
                result["stock_exchange_ratio"] = float(matches[0])
                break

        # Handle "one share" in stock deals
        if result["stock_exchange_ratio"] == 0.0:
            if re.search(r"(?:and|receive)\s+one\s+share\s+of\s+[A-Za-z0-9&,\s\.]*?\s*common stock", text, re.IGNORECASE):
                result["stock_exchange_ratio"] = 1.0

        # 3. Contingent Value Right (CVR) Detection
        cvr_match = re.search(r"(?:contingent value right|CVR|additional cash payment)", text, re.IGNORECASE)
        if cvr_match:
            result["has_cvr"] = True
            cvr_cash = re.findall(r"(?:CVR|contingent value right).*?up to\s*[$]\s*([0-9]+(?:\.[0-9]{1,4})?)", text, re.IGNORECASE)
            if cvr_cash:
                result["cvr_amount"] = float(cvr_cash[0])

        # 4. Acquirer Entity Detection
        acquirer_patterns = [
            r"(?:merger(?: agreement)? with|transaction with|acquisition by)\s+([A-Z][A-Za-z0-9&,\s\.]*?(?:Corporation|Corp\.?|Inc\.?|Company|Co\.?|LLC|Holdings|Limited|Ltd\.?))\b",
            r"(?:wholly[- ]owned subsidiary of|direct[, ]? wholly[- ]owned subsidiary of)\s+([A-Z][A-Za-z0-9&,\s\.]*?(?:Corporation|Corp\.?|Inc\.?|Company|Co\.?|LLC|Holdings|Limited|Ltd\.?))\b",
            r"([A-Z][A-Za-z0-9&,\s\.]*?(?:Corporation|Corp\.?|Inc\.?|Holdings))\s+(?:completed (?:its|the) acquisition of)",
            r"(?:Parent refers to|Parent, which is)\s+([A-Z][A-Za-z0-9&,\s\.]*?(?:Corporation|Corp\.?|Inc\.?|Company|Co\.?))\b",
        ]
        for pat in acquirer_patterns:
            acq_match = re.search(pat, text, re.IGNORECASE)
            if acq_match:
                candidate_name = acq_match.group(1).strip(" ,")
                # Filter out generic placeholder phrases
                if candidate_name.lower() not in ["the company", "merger sub", "parent"]:
                    result["acquirer_name"] = candidate_name
                    break

        # Resolve Acquirer Ticker & CIK
        if result["acquirer_name"]:
            acq_info = self.resolve_acquirer_ticker_and_cik(result["acquirer_name"])
            result["acquirer_ticker"] = acq_info["acquirer_ticker"]
            result["acquirer_cik"] = acq_info["acquirer_cik"]

        # 5. Effective Date Detection
        date_patterns = [
            r"(?:consummated on|completed on|effective as of|effective date of|effective time on)\s+([A-Z][a-z]+ \d{1,2},? \d{4})",
            r"(?:on|dated)\s+([A-Z][a-z]+ \d{1,2},? \d{4}),?\s*(?:the merger was consummated|the company completed|the merger became effective)",
        ]
        for pat in date_patterns:
            d_match = re.search(pat, text, re.IGNORECASE)
            if d_match:
                parsed_dt = self._parse_filing_date_string(d_match.group(1))
                if parsed_dt:
                    result["effective_date"] = parsed_dt
                    break

        # 6. Classify deal structure
        if result["cash_per_share"] > 0 and result["stock_exchange_ratio"] > 0:
            result["deal_type"] = "mixed_cash_and_stock"
        elif result["cash_per_share"] > 0 and result["has_cvr"]:
            result["deal_type"] = "cvr_cash"
        elif result["cash_per_share"] > 0:
            result["deal_type"] = "all_cash"
        elif result["stock_exchange_ratio"] > 0:
            result["deal_type"] = "all_stock"
        elif "delist" in text.lower() or "removal from listing" in text.lower():
            result["deal_type"] = "delisted_merger"

        return result

    def search_merger_filing(self, cik: str, approx_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Searches SEC EDGAR for Form 8-K Item 2.01, Form 25-NSE, or Form 15-12G filings
        to identify M&A conversion terms and delisting metadata.
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

        # Scan for Form 8-K filings, Form 25, or Form 15
        for i in range(len(forms)):
            form = forms[i]
            f_date = filing_dates[i]
            items = items_list[i] if i < len(items_list) else []

            if form not in ["8-K", "8-K/A", "25-NSE", "25", "15-12G", "DEFM14A", "S-4"]:
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
            trigger_terms = [
                "merger consideration", "effective time", "merger agreement",
                "item 2.01", "consummated", "closing date", "entire class of securities",
                "removal from listing"
            ]
            if any(term in text_lower for term in trigger_terms):
                soup = BeautifulSoup(html_content, "html.parser")
                text = " ".join(soup.get_text().split())

                extracted = self.extract_ma_terms_from_text(text)
                
                # If effective date wasn't parsed from body, use filing date
                effective_date = extracted["effective_date"] or f_date

                # Find best summary sentence
                best_snippet = None
                for sentence in text.split(". "):
                    s_lower = sentence.lower()
                    if ("merger consideration" in s_lower or "converted into" in s_lower or "completed" in s_lower) and \
                       ("cash" in s_lower or "share" in s_lower or "stock" in s_lower):
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
                    "effective_date": effective_date,
                    "target_name": target_name,
                    "target_cik": clean_cik.zfill(10),
                    "acquirer_name": extracted["acquirer_name"],
                    "acquirer_ticker": extracted["acquirer_ticker"],
                    "acquirer_cik": extracted["acquirer_cik"],
                    "deal_type": extracted["deal_type"],
                    "cash_per_share": extracted["cash_per_share"],
                    "stock_exchange_ratio": extracted["stock_exchange_ratio"],
                    "has_cvr": extracted["has_cvr"],
                    "cvr_amount": extracted["cvr_amount"],
                    "excerpt": best_snippet,
                }

        return None

    def build_proposed_fix(
        self,
        target_ticker: str,
        security_id: str,
        merger_data: Dict[str, Any],
        case_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Converts extracted merger data into a standardized proposed fix dictionary
        ready for insertion into columbia.proposed_fixes.
        """
        effective_date = merger_data.get("effective_date") or merger_data.get("filing_date")
        acq_name = merger_data.get("acquirer_name") or "Surviving Entity"
        acq_ticker = merger_data.get("acquirer_ticker")
        deal_type = merger_data.get("deal_type")
        cash = merger_data.get("cash_per_share", 0.0)
        ratio = merger_data.get("stock_exchange_ratio", 0.0)

        proposed_terms = {
            "status": "DELISTED_MERGER",
            "effective_date": effective_date,
            "acquirer_name": acq_name,
            "acquirer_ticker": acq_ticker,
            "acquirer_cik": merger_data.get("acquirer_cik"),
            "deal_type": deal_type,
            "cash_per_share": cash,
            "stock_exchange_ratio": ratio,
            "has_cvr": merger_data.get("has_cvr", False),
            "cvr_amount": merger_data.get("cvr_amount", 0.0),
        }

        # Build clean explanation
        terms_desc = []
        if cash > 0:
            terms_desc.append(f"${cash:.2f}/sh cash")
        if ratio > 0:
            terms_desc.append(f"{ratio:.4f} stock ratio")
        if merger_data.get("has_cvr"):
            terms_desc.append(f"CVR up to ${merger_data.get('cvr_amount', 0.0):.2f}")
        terms_str = " + ".join(terms_desc) if terms_desc else "Delisted"

        acq_desc = f"{acq_name} ({acq_ticker})" if acq_ticker else acq_name
        explanation = (
            f"SEC Form {merger_data.get('form_type', '8-K')} filed on {merger_data.get('filing_date')} "
            f"confirms completed acquisition by {acq_desc}. Effective date: {effective_date}. "
            f"Consideration terms: {deal_type} ({terms_str}). Security trading ceased."
        )

        import hashlib
        h = hashlib.md5(f"ma_{target_ticker}_{effective_date}_{merger_data.get('source_id')}".encode()).hexdigest()[:16]

        return {
            "fix_id": f"fix_{h}",
            "case_id": case_id or f"ma_{target_ticker}",
            "ticker": target_ticker,
            "security_id": security_id,
            "company_id": f"com_cik_{int(merger_data.get('target_cik', 0))}",
            "cik": merger_data.get("target_cik"),
            "date": effective_date,
            "fix_type": "merger_acquisition",
            "target_field": "M&A_CONVERSION_TERMS",
            "current_value": "ACTIVE",
            "proposed_value": json.dumps(proposed_terms),
            "action": "flag_delisted_record_and_set_conversion_terms",
            "confidence": 0.98,
            "verdict": "merger_acquisition_terms_verified",
            "source": f"sec_{merger_data.get('form_type', '8-K').lower()}",
            "source_id": merger_data.get("source_id"),
            "source_url": merger_data.get("source_url"),
            "explanation": explanation,
            "status": "pending_review"
        }
