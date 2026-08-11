"""sec_filing_finder.py — Resolve company + filing type → exhibit-direct document URL(s) + metadata.

class: read  (writes NOTHING — returns URLs and metadata only)

US arm (SEC EDGAR):
  1. Resolve ticker → CIK via https://www.sec.gov/files/company_tickers.json
  2. Fetch submissions JSON: https://data.sec.gov/submissions/CIK{cik:010d}.json
  3. Filter by --form, pick latest (or first N with --count).
  4. Build filing folder URL and resolve the exhibit-direct primary document URL.
     For 8-K forms: also expose the exhibit list so the caller can target EX-99.1
     directly instead of the filing-index wrapper.
  Returns URL + metadata; NEVER fetches the document body.

BR arm (CVM dados-abertos):
  1. Resolve company name/CNPJ/CVM-code → CD_CVM via the CVM open-data cadastro CSV:
     https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
     (semicolon-delimited; columns: CNPJ_CIA, DENOM_SOCIAL, DENOM_COMERC, CD_CVM, SIT)
  2. Download the current-year (and optionally prior-year) IPE/DFP/ITR ZIP CSV:
     https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{TYPE}/DADOS/{type}_cia_aberta_{year}.zip
  3. Filter rows by CD_CVM (and optionally Categoria/Tipo), sort by Data_Referencia desc,
     return the Link_Download URL of the latest matching document + metadata.
  The Link_Download URL is a direct document link embedded in CVM's dataset — it typically
  resolves to a PDF or HTML viewer on rad.cvm.gov.br or fnet.bmfbovespa.com.br.

User-Agent:
  SEC fair-access endpoints 403 non-contact UAs. Resolved from SEC_EDGAR_UA
  (OS env, then vault .user/config/env/.env — same convention as BRAPI_TOKEN
  in price_fetcher.py), falling back to a neutral placeholder that will get
  403'd by SEC — set the env var. Override either with --user-agent. CVM does
  not require a contact UA but uses the same header for consistency.

CLI:
    python investimentos/sec_filing_finder.py \\
        --ticker AMZN --form 10-K --latest [--market us|br] \\
        [--cvm-code 17329] [--cnpj "02.474.103/0001-19"] [--company "Engie"] \\
        [--form DFP|ITR|IPE] [--count N] [--json] [--user-agent UA]

Exit codes:
    0  Resolved at least one filing URL
    1  No filing found / resolution failed
    2  Usage error
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Contact User-Agent (SEC fair-access policy; same sent to CVM for consistency)
# Resolved from SEC_EDGAR_UA (OS env, then vault .env) — see _load_ua().
# Override with --user-agent on the CLI.
# ---------------------------------------------------------------------------
PLACEHOLDER_UA = "sb-os-user your-email@example.com"


def _load_ua() -> str:
    """Resolve SEC_EDGAR_UA: OS env first, then vault .user/config/env/.env.

    Mirrors price_fetcher.py's _load_brapi_token() convention. Falls back to
    a neutral placeholder — SEC will 403 requests sent with it.
    """
    ua = os.environ.get("SEC_EDGAR_UA")
    if ua and ua.strip():
        return ua.strip()

    for parent in Path(__file__).resolve().parents:
        if (parent / "CLAUDE.md").exists() and (parent / ".user").is_dir():
            env_path = parent / ".user" / "config" / "env" / ".env"
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("SEC_EDGAR_UA="):
                            value = line[len("SEC_EDGAR_UA="):].strip()
                            if value:
                                return value
            except OSError:
                pass
            break

    return PLACEHOLDER_UA


DEFAULT_UA = _load_ua()

# ---------------------------------------------------------------------------
# SEC EDGAR — base URLs
# ---------------------------------------------------------------------------
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_FILING_FOLDER_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/"
)
_FILING_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}/"
    "{accession_no_dashes}-index.htm"
)

# ---------------------------------------------------------------------------
# CVM dados-abertos — base URLs
# ---------------------------------------------------------------------------
_CVM_CAD_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
)
_CVM_DOC_URL = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{doc_type}/DADOS/"
    "{doc_type_lower}_cia_aberta_{year}.zip"
)
# CVM document types supported
_CVM_DOC_TYPES = ("IPE", "DFP", "ITR")
# IPE Categoria values that correspond to annual reports (DFP-equivalent via IPE)
_DFP_IPE_CATEGORIES = frozenset(
    {"Demonstrações Financeiras Anuais", "Demonstrações Financeiras Anuais/Parecer"}
)
_ITR_IPE_CATEGORIES = frozenset(
    {"Informações Trimestrais", "Informações Trimestrais/Parecer"}
)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get(url: str, *, user_agent: str = DEFAULT_UA, timeout: int = 30,
         binary: bool = False) -> bytes | str:
    """GET url, return body. Raises on HTTP error."""
    try:
        import requests  # type: ignore
    except ImportError:
        raise ImportError(
            "requests is required. Install: pip install requests"
        )
    resp = requests.get(
        url,
        headers={"User-Agent": user_agent},
        timeout=timeout,
        stream=binary,
    )
    resp.raise_for_status()
    if binary:
        return resp.content
    return resp.text


# ---------------------------------------------------------------------------
# SEC — ticker → CIK
# ---------------------------------------------------------------------------

def _load_ticker_map(user_agent: str) -> dict[str, int]:
    """Return {TICKER_UPPER: cik_int} from SEC company_tickers.json."""
    raw = _get(_TICKERS_URL, user_agent=user_agent)
    data = json.loads(raw)
    # Format: {"0": {"cik_str": N, "ticker": "...", "title": "..."}, ...}
    result: dict[str, int] = {}
    for entry in data.values():
        t = entry.get("ticker", "").upper()
        c = entry.get("cik_str")
        if t and c is not None:
            try:
                result[t] = int(c)
            except (ValueError, TypeError):
                pass
    return result


def _resolve_cik(ticker: str, user_agent: str) -> int:
    """Resolve ticker to CIK integer. Raises ValueError if not found."""
    ticker_map = _load_ticker_map(user_agent)
    cik = ticker_map.get(ticker.upper())
    if cik is None:
        raise ValueError(
            f"Ticker {ticker!r} not found in SEC company_tickers.json. "
            "Check the ticker symbol (case-insensitive)."
        )
    return cik


# ---------------------------------------------------------------------------
# SEC — submissions → filing list
# ---------------------------------------------------------------------------

def _fetch_submissions(cik: int, user_agent: str) -> dict:
    """Return the raw submissions JSON for a CIK."""
    url = _SUBMISSIONS_URL.format(cik=cik)
    raw = _get(url, user_agent=user_agent)
    return json.loads(raw)


def _iter_filings(submissions: dict, form_filter: Optional[str] = None):
    """Yield filing dicts from submissions['filings']['recent'] (newest first).

    Each yielded dict has keys: form, filingDate, accessionNumber,
    primaryDocument, (plus any others present in the parallel arrays).
    """
    recent = submissions.get("filings", {}).get("recent", {})
    if not recent:
        return

    # All fields are parallel arrays — zip them together by index.
    keys = list(recent.keys())
    arrays = [recent[k] for k in keys]
    n = min(len(a) for a in arrays)

    form_upper = form_filter.upper() if form_filter else None
    for i in range(n):
        row = {k: arrays[j][i] for j, k in enumerate(keys)}
        if form_upper is None or (row.get("form") or "").upper() == form_upper:
            yield row


# ---------------------------------------------------------------------------
# SEC — build exhibit-direct URL
# ---------------------------------------------------------------------------

def _accession_nodashes(accession_number: str) -> str:
    """'0001234567-24-000001' → '0001234567240000001'"""
    return accession_number.replace("-", "")


def _filing_folder_url(cik_int: int, accession_number: str) -> str:
    no_dashes = _accession_nodashes(accession_number)
    return _FILING_FOLDER_URL.format(
        cik_int=cik_int, accession_no_dashes=no_dashes
    )


def _resolve_exhibit_direct(
    cik_int: int,
    accession_number: str,
    primary_document: str,
    form: str,
    user_agent: str,
) -> dict:
    """Resolve the exhibit-direct URL for a filing.

    Returns a dict with:
      - primary_url: the direct URL to the primary document
      - exhibit_list: list of {doc, type, description, url} for 8-K forms (empty otherwise)
      - filing_folder_url: the folder-level URL
      - index_url: the index page URL
    """
    no_dashes = _accession_nodashes(accession_number)
    folder = _FILING_FOLDER_URL.format(
        cik_int=cik_int, accession_no_dashes=no_dashes
    )
    index_url = _FILING_INDEX_URL.format(
        cik_int=cik_int, accession_no_dashes=no_dashes
    )
    primary_url = folder + primary_document if primary_document else folder

    result = {
        "primary_url": primary_url,
        "exhibit_list": [],
        "filing_folder_url": folder,
        "index_url": index_url,
    }

    # For 8-K filings: parse the filing index to expose EX-99.1 and other exhibits
    # so the caller can target them directly (avoiding the multi-MB index wrapper).
    if "8-K" in form.upper():
        try:
            idx_html = _get(index_url, user_agent=user_agent)
            exhibits = _parse_8k_exhibits(idx_html, folder)
            result["exhibit_list"] = exhibits
        except Exception:
            # Non-fatal: primary_url is still valid
            pass

    return result


def _parse_8k_exhibits(index_html: str, folder_url: str) -> list[dict]:
    """Extract exhibit table from an EDGAR 8-K index page.

    Returns list of {doc, type, description, url}.
    """
    exhibits = []
    # Match table rows in the document table on the EDGAR index page.
    # The table has columns: Seq | Description | Document | Type | Size
    row_re = re.compile(
        r"<tr[^>]*>.*?</tr>", re.DOTALL | re.IGNORECASE
    )
    cell_re = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE)
    href_re = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    tag_re = re.compile(r"<[^>]+>")

    for row_m in row_re.finditer(index_html):
        cells = cell_re.findall(row_m.group(0))
        if len(cells) < 4:
            continue
        texts = [tag_re.sub("", c).strip() for c in cells]
        # Skip header rows
        if texts[0].lower() in ("seq", "description", "#"):
            continue
        if not any(t for t in texts):
            continue
        # Find the href in the Document cell (cells[2])
        href_m = href_re.search(cells[2])
        if not href_m:
            continue
        href = href_m.group(1)
        # Make absolute if relative
        if href.startswith("/"):
            href = "https://www.sec.gov" + href
        elif not href.startswith("http"):
            href = folder_url + href

        doc_text = tag_re.sub("", cells[2]).strip()
        type_text = texts[3] if len(texts) > 3 else ""
        desc_text = texts[1] if len(texts) > 1 else ""

        exhibits.append({
            "doc": doc_text,
            "type": type_text,
            "description": desc_text,
            "url": href,
        })

    return exhibits


# ---------------------------------------------------------------------------
# SEC — main resolver
# ---------------------------------------------------------------------------

def resolve_sec(
    *,
    ticker: str,
    form: str,
    latest_only: bool = True,
    count: int = 1,
    user_agent: str = DEFAULT_UA,
) -> list[dict]:
    """Resolve SEC filing(s) for a ticker + form.

    Returns a list of filing metadata dicts (length 1 when --latest).
    Each dict:
      ticker, cik, form, filing_date, accession_number,
      primary_document, primary_url, exhibit_list,
      filing_folder_url, index_url, company_name, market
    """
    if user_agent == PLACEHOLDER_UA:
        raise ValueError(
            "No contact User-Agent set — SEC EDGAR will 403 this request. "
            "Set SEC_EDGAR_UA (env var or .user/config/env/.env) or pass "
            "--user-agent 'Your Name your-email@example.com'."
        )

    cik = _resolve_cik(ticker, user_agent)
    submissions = _fetch_submissions(cik, user_agent)
    company_name = submissions.get("name", ticker)

    results = []
    limit = 1 if latest_only else max(1, count)
    for filing in _iter_filings(submissions, form_filter=form):
        acc_no = filing.get("accessionNumber", "")
        primary_doc = filing.get("primaryDocument", "")
        filing_form = filing.get("form", form)
        filing_date = filing.get("filingDate", "")

        exhibit_data = _resolve_exhibit_direct(
            cik_int=cik,
            accession_number=acc_no,
            primary_document=primary_doc,
            form=filing_form,
            user_agent=user_agent,
        )

        results.append({
            "market": "us",
            "ticker": ticker.upper(),
            "company_name": company_name,
            "cik": cik,
            "form": filing_form,
            "filing_date": filing_date,
            "accession_number": acc_no,
            "primary_document": primary_doc,
            "primary_url": exhibit_data["primary_url"],
            "exhibit_list": exhibit_data["exhibit_list"],
            "filing_folder_url": exhibit_data["filing_folder_url"],
            "index_url": exhibit_data["index_url"],
        })
        if len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# CVM — company cadastro lookup
# ---------------------------------------------------------------------------

def _load_cvm_cadastro(user_agent: str) -> list[dict]:
    """Download and parse the CVM open-data company register CSV.

    Returns list of dicts with keys: CNPJ_CIA, DENOM_SOCIAL, DENOM_COMERC,
    CD_CVM, SIT, (and all other columns).
    """
    raw = _get(_CVM_CAD_URL, user_agent=user_agent)
    # The file is semicolon-delimited, Latin-1 / cp1252 encoded (Brazilian CSV convention).
    # requests returns text decoded as reported by Content-Type; try UTF-8 then Latin-1.
    try:
        reader = csv.DictReader(io.StringIO(raw), delimiter=";")
        rows = list(reader)
    except Exception:
        # Fallback: re-fetch as bytes and decode Latin-1
        raw_bytes = _get(_CVM_CAD_URL, user_agent=user_agent, binary=True)
        decoded = raw_bytes.decode("latin-1", errors="replace")
        reader = csv.DictReader(io.StringIO(decoded), delimiter=";")
        rows = list(reader)
    return rows


def _resolve_cvm_code(
    *,
    cvm_code: Optional[str] = None,
    cnpj: Optional[str] = None,
    company: Optional[str] = None,
    user_agent: str = DEFAULT_UA,
) -> tuple[str, str]:
    """Resolve a CVM code from cvm_code / cnpj / company name.

    Returns (cd_cvm, company_name). Raises ValueError if not found.
    """
    if cvm_code:
        # Accept either with or without leading zeros; normalize to string
        return str(int(cvm_code)), f"CVM:{cvm_code}"

    cadastro = _load_cvm_cadastro(user_agent)
    if not cadastro:
        raise ValueError("CVM cadastro CSV returned no rows.")

    cnpj_clean = re.sub(r"[^0-9]", "", cnpj or "")
    company_upper = company.upper().strip() if company else ""

    for row in cadastro:
        row_cnpj = re.sub(r"[^0-9]", "", row.get("CNPJ_CIA", ""))
        row_cd = row.get("CD_CVM", "").strip()
        row_name = (row.get("DENOM_SOCIAL") or row.get("DENOM_COMERC") or "").strip()
        row_name_upper = row_name.upper()

        if cnpj_clean and row_cnpj == cnpj_clean:
            return row_cd, row_name

        if company_upper and company_upper in row_name_upper:
            return row_cd, row_name

    # Build a helpful suggestion
    hint = cnpj or company or "unknown"
    raise ValueError(
        f"Company {hint!r} not found in CVM cadastro. "
        "Try --cvm-code (numeric, from the CVM register) or "
        "--cnpj (digits, Brazilian format accepted)."
    )


# ---------------------------------------------------------------------------
# CVM — IPE/DFP/ITR index lookup
# ---------------------------------------------------------------------------

def _load_cvm_doc_index(
    doc_type: str,
    year: int,
    user_agent: str,
) -> list[dict]:
    """Download and parse the CVM document index CSV for a year.

    doc_type: 'IPE' | 'DFP' | 'ITR'
    Returns list of dicts with CSV columns.
    """
    doc_type_upper = doc_type.upper()
    url = _CVM_DOC_URL.format(
        doc_type=doc_type_upper,
        doc_type_lower=doc_type_upper.lower(),
        year=year,
    )
    raw_bytes = _get(url, user_agent=user_agent, binary=True)

    # The ZIP may contain multiple CSVs (DFP/ITR have per-statement CSVs).
    # The "base" index CSV is named exactly {type_lower}_cia_aberta_{year}.csv —
    # it has the document-level metadata (one row per filing, with LINK_DOC).
    # The per-statement CSVs (BPA_con, DRE_ind, etc.) contain financial data,
    # not document URLs. We always want the base index file.
    zf = zipfile.ZipFile(io.BytesIO(raw_bytes))
    target_base = f"{doc_type.lower()}_cia_aberta_{year}.csv"
    csv_name = None
    for name in zf.namelist():
        if name.lower() == target_base:
            csv_name = name
            break
    # Fallback: first plain CSV (for IPE which has only one)
    if csv_name is None:
        for name in zf.namelist():
            if name.lower().endswith(".csv"):
                csv_name = name
                break
    if csv_name is None:
        raise ValueError(f"No CSV found in CVM {doc_type} {year} ZIP.")

    raw_csv = zf.read(csv_name)
    # CVM CSVs are typically ISO-8859-1 / Latin-1, semicolon-separated
    try:
        decoded = raw_csv.decode("latin-1")
    except Exception:
        decoded = raw_csv.decode("utf-8", errors="replace")

    reader = csv.DictReader(io.StringIO(decoded), delimiter=";")
    return list(reader)


def _parse_cvm_date(date_str: str) -> Optional[date]:
    """Parse 'YYYY-MM-DD' CVM date → date object, or None on failure."""
    if not date_str or not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _cvm_row_get(row: dict, *keys: str) -> str:
    """Get first non-empty value from row trying multiple column-name candidates."""
    for k in keys:
        v = (row.get(k) or "").strip()
        if v:
            return v
    return ""


def _cvm_match_code(row_cd: str, cd_cvm: str) -> bool:
    """Match CVM code tolerantly: '17329' == '017329' (zero-padding varies)."""
    # Strip leading zeros from both for comparison
    try:
        return int(row_cd) == int(cd_cvm)
    except (ValueError, TypeError):
        return row_cd.strip() == cd_cvm.strip()


def _filter_cvm_rows(
    rows: list[dict],
    cd_cvm: str,
    doc_type: str,
    form_hint: Optional[str] = None,
) -> list[dict]:
    """Filter CVM index rows by company code and optionally document type hint.

    Handles both DFP/ITR column schema (CD_CVM, LINK_DOC, DT_REFER, DT_RECEB)
    and IPE column schema (Codigo_CVM, Link_Download, Data_Referencia, Data_Entrega).

    For IPE: form_hint 'DFP' targets annual-report categories; 'ITR' targets
    quarterly categories; None returns all rows.
    For DFP/ITR: all rows for this company are returned (the doc_type already
    narrows to the right filing class).
    """
    matched = []

    for row in rows:
        # Both schemas: CVM code field
        row_cd = _cvm_row_get(row, "Codigo_CVM", "CD_CVM")
        if not _cvm_match_code(row_cd, cd_cvm):
            continue

        if doc_type == "IPE" and form_hint:
            categoria = _cvm_row_get(row, "Categoria", "CATEG_DOC")
            if form_hint.upper() == "DFP":
                if not any(k in categoria for k in ("Demonstrações Financeiras", "Financeiras Anuais", "DFP")):
                    continue
            elif form_hint.upper() == "ITR":
                if not any(k in categoria for k in ("Informações Trimestrais", "ITR")):
                    continue

        matched.append(row)

    # Sort by reference date descending (newest first)
    # Try both column name variants
    matched.sort(
        key=lambda r: (
            _parse_cvm_date(_cvm_row_get(r, "Data_Referencia", "DT_REFER")) or date.min
        ),
        reverse=True,
    )
    return matched


# ---------------------------------------------------------------------------
# CVM — main resolver
# ---------------------------------------------------------------------------

def resolve_cvm(
    *,
    cvm_code: Optional[str] = None,
    cnpj: Optional[str] = None,
    company: Optional[str] = None,
    form: str = "DFP",
    latest_only: bool = True,
    count: int = 1,
    user_agent: str = DEFAULT_UA,
) -> list[dict]:
    """Resolve CVM filing(s) for a company + form.

    form: 'DFP' | 'ITR' | 'IPE' (or 'DFP'/'ITR' via IPE index when the
          company is listed in the IPE dataset).

    Returns list of filing metadata dicts. Each dict:
      market, company_name, cd_cvm, form, filing_date, reference_date,
      protocol, version, primary_url, categoria, tipo, link_download.
    """
    cd_cvm, company_name = _resolve_cvm_code(
        cvm_code=cvm_code,
        cnpj=cnpj,
        company=company,
        user_agent=user_agent,
    )

    form_upper = form.upper()
    current_year = date.today().year

    # Strategy: try dedicated DFP/ITR dataset first; fall back to IPE for the
    # year range. The dedicated datasets are more structured (one row = one filing),
    # while IPE is the catch-all for all periodic and eventual submissions.
    years_to_try = [current_year, current_year - 1]
    doc_type = form_upper if form_upper in ("DFP", "ITR") else "IPE"
    form_hint_for_ipe = form_upper if form_upper in ("DFP", "ITR") else None

    all_rows: list[dict] = []
    errors: list[str] = []

    for year in years_to_try:
        try:
            rows = _load_cvm_doc_index(doc_type, year, user_agent)
            filtered = _filter_cvm_rows(rows, cd_cvm, doc_type, form_hint_for_ipe)
            all_rows.extend(filtered)
            if all_rows:
                break  # Found in this year; no need to go to prior year
        except Exception as exc:
            errors.append(f"CVM {doc_type} {year}: {exc}")
            # Try IPE as fallback when DFP/ITR index fails or is empty
            if doc_type != "IPE":
                try:
                    ipe_rows = _load_cvm_doc_index("IPE", year, user_agent)
                    filtered = _filter_cvm_rows(
                        ipe_rows, cd_cvm, "IPE", form_hint_for_ipe
                    )
                    all_rows.extend(filtered)
                    if all_rows:
                        doc_type = "IPE"  # record which source we used
                        break
                except Exception as ipe_exc:
                    errors.append(f"CVM IPE {year} fallback: {ipe_exc}")

    if not all_rows and errors:
        raise ValueError(
            f"Could not load CVM filings for company {cd_cvm} ({company_name}). "
            + " | ".join(errors)
        )

    limit = 1 if latest_only else max(1, count)
    results = []
    for row in all_rows[:limit]:
        # Both schemas: LINK_DOC (DFP/ITR) and Link_Download (IPE)
        link = _cvm_row_get(row, "Link_Download", "LINK_DOC")
        # company name: Nome_Companhia (IPE) or DENOM_CIA (DFP/ITR)
        row_company = _cvm_row_get(row, "Nome_Companhia", "DENOM_CIA") or company_name
        results.append({
            "market": "br",
            "company_name": row_company,
            "cd_cvm": cd_cvm,
            "form": form_upper,
            "doc_type_used": doc_type,
            # IPE: Data_Entrega; DFP/ITR: DT_RECEB
            "filing_date": _cvm_row_get(row, "Data_Entrega", "DT_RECEB"),
            # IPE: Data_Referencia; DFP/ITR: DT_REFER
            "reference_date": _cvm_row_get(row, "Data_Referencia", "DT_REFER"),
            # IPE only: Protocolo_Entrega
            "protocol": _cvm_row_get(row, "Protocolo_Entrega", "ID_DOC"),
            "version": _cvm_row_get(row, "Versao", "VERSAO"),
            # IPE: Categoria; DFP/ITR: CATEG_DOC
            "categoria": _cvm_row_get(row, "Categoria", "CATEG_DOC"),
            # IPE only: Tipo
            "tipo": _cvm_row_get(row, "Tipo"),
            # IPE only: Assunto
            "assunto": _cvm_row_get(row, "Assunto"),
            "primary_url": link,
            "link_download": link,
        })

    return results


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _print_table(filings: list[dict]) -> None:
    """Print a human-readable metadata table of resolved filings."""
    if not filings:
        print("No filings found.", file=sys.stderr)
        return

    for i, f in enumerate(filings, 1):
        print(f"\n{'=' * 60}")
        print(f"  Filing #{i}")
        print(f"{'=' * 60}")
        market = f.get("market", "?")
        if market == "us":
            print(f"  Market:           US (SEC EDGAR)")
            print(f"  Company:          {f.get('company_name', '')}")
            print(f"  Ticker:           {f.get('ticker', '')}")
            print(f"  CIK:              {f.get('cik', '')}")
            print(f"  Form:             {f.get('form', '')}")
            print(f"  Filing date:      {f.get('filing_date', '')}")
            print(f"  Accession #:      {f.get('accession_number', '')}")
            print(f"  Primary document: {f.get('primary_document', '')}")
            print(f"  Primary URL:      {f.get('primary_url', '')}")
            print(f"  Folder URL:       {f.get('filing_folder_url', '')}")
            print(f"  Index URL:        {f.get('index_url', '')}")
            exhibits = f.get("exhibit_list", [])
            if exhibits:
                print(f"  Exhibits ({len(exhibits)}):")
                for ex in exhibits:
                    print(
                        f"    [{ex.get('type', '?')}] {ex.get('description', '')} "
                        f"→ {ex.get('url', '')}"
                    )
        else:
            print(f"  Market:           BR (CVM)")
            print(f"  Company:          {f.get('company_name', '')}")
            print(f"  CVM code:         {f.get('cd_cvm', '')}")
            print(f"  Form:             {f.get('form', '')} (via {f.get('doc_type_used', '')})")
            print(f"  Categoria:        {f.get('categoria', '')}")
            print(f"  Tipo:             {f.get('tipo', '')}")
            print(f"  Reference date:   {f.get('reference_date', '')}")
            print(f"  Filing date:      {f.get('filing_date', '')}")
            print(f"  Protocol:         {f.get('protocol', '')}")
            print(f"  Version:          {f.get('version', '')}")
            print(f"  Primary URL:      {f.get('primary_url', '')}")
            if f.get("assunto"):
                print(f"  Assunto:          {f.get('assunto', '')}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Resolve company + filing type → exhibit-direct document URL(s) + metadata. "
            "Returns URLs only — does NOT fetch or write the document body."
        )
    )
    # Market selection
    p.add_argument(
        "--market",
        choices=["us", "br"],
        default=None,
        help="Market: 'us' (SEC EDGAR) or 'br' (CVM). "
             "Inferred from --ticker (US) or --cvm-code/--cnpj/--company (BR) when omitted.",
    )
    # US arm
    p.add_argument("--ticker", default=None, help="US ticker symbol (e.g. AMZN, MSFT)")
    p.add_argument("--cik", default=None, help="SEC CIK (override ticker lookup)")
    # BR arm
    p.add_argument("--cvm-code", default=None, help="CVM company code (CD_CVM, numeric)")
    p.add_argument("--cnpj", default=None, help="Company CNPJ (Brazilian tax ID)")
    p.add_argument("--company", default=None, help="Company name fragment (case-insensitive partial match)")
    # Shared
    p.add_argument(
        "--form",
        default=None,
        help=(
            "Filing form type. US: 10-K, 10-Q, 8-K, 6-K, etc. "
            "BR: DFP (annual), ITR (quarterly), IPE (periodic/eventual)."
        ),
    )
    p.add_argument(
        "--latest",
        action="store_true",
        default=True,
        help="Return only the most recent filing (default: on).",
    )
    p.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of filings to return (default 1; overridden to 1 when --latest).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of a table.",
    )
    p.add_argument(
        "--user-agent",
        default=DEFAULT_UA,
        help=(
            "User-Agent header for API requests. "
            "SEC fair-access endpoints require a contact-bearing UA. "
            f"Default: {DEFAULT_UA!r}"
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # Infer market
    market = args.market
    if market is None:
        if args.ticker or args.cik:
            market = "us"
        elif args.cvm_code or args.cnpj or args.company:
            market = "br"
        else:
            print(
                "ERROR: specify --market us|br, or provide --ticker (US) "
                "or --cvm-code/--cnpj/--company (BR).",
                file=sys.stderr,
            )
            return 2

    # Validate required args per market
    if market == "us" and not args.ticker and not args.cik:
        print("ERROR: --market us requires --ticker or --cik.", file=sys.stderr)
        return 2
    if market == "br" and not args.cvm_code and not args.cnpj and not args.company:
        print(
            "ERROR: --market br requires at least one of --cvm-code, --cnpj, --company.",
            file=sys.stderr,
        )
        return 2

    if args.form is None:
        args.form = "10-K" if market == "us" else "DFP"

    try:
        if market == "us":
            filings = resolve_sec(
                ticker=args.ticker or f"CIK:{args.cik}",
                form=args.form,
                latest_only=args.latest,
                count=args.count,
                user_agent=args.user_agent,
            )
        else:
            filings = resolve_cvm(
                cvm_code=args.cvm_code,
                cnpj=args.cnpj,
                company=args.company,
                form=args.form,
                latest_only=args.latest,
                count=args.count,
                user_agent=args.user_agent,
            )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not filings:
        print(
            f"No {args.form} filings found for the requested company.",
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(json.dumps(filings, indent=2, default=str))
    else:
        _print_table(filings)

    return 0


if __name__ == "__main__":
    sys.exit(main())
