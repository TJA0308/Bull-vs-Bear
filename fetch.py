import os
import re
import sys

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

HEADERS = {"User-Agent": os.getenv("SEC_USER_AGENT")}


def get_cik(ticker):
    """Turn a ticker (e.g. 'AAPL') into a 10-digit, zero-padded CIK string."""
    url = "https://www.sec.gov/files/company_tickers.json"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()  # stop with a clear error on 403/404/etc.
    data = response.json()

    for company in data.values():
        if company["ticker"].upper() == ticker.upper():
            return str(company["cik_str"]).zfill(10)

    raise ValueError(f"Ticker {ticker} not found")


def get_latest_10k(cik):
    """Find the newest 10-K for a CIK. Returns accession, document and date."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    recent = response.json()["filings"]["recent"]

    # recent holds parallel lists: index i across all of them is one filing.
    # Lists are newest first, so the first 10-K we hit is the latest.
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            return {
                "accession": recent["accessionNumber"][i],
                "document": recent["primaryDocument"][i],
                "date": recent["filingDate"][i],
            }

    raise ValueError(f"No 10-K found for CIK {cik}")


def build_filing_url(cik, filing):
    """Build the web address of the 10-K document on sec.gov."""
    cik_no_zeros = int(cik)
    accession_no_dashes = filing["accession"].replace("-", "")
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_no_zeros}/{accession_no_dashes}/{filing['document']}"
    )


RAW_DIR = os.path.join("data", "raw")


def get_filing_html(ticker, cik, filing):
    """Download the 10-K HTML, or read it from the local cache if we have it."""
    os.makedirs(RAW_DIR, exist_ok=True)
    cache_name = f"{ticker.upper()}_{filing['accession']}.html"
    cache_path = os.path.join(RAW_DIR, cache_name)

    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return f.read()

    response = requests.get(build_filing_url(cik, filing), headers=HEADERS)
    response.raise_for_status()
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(response.text)
    return response.text


def html_to_text(html):
    """Strip the HTML tags and collapse messy whitespace into single spaces."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ")
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text)


def loose(word):
    """Match a word even if stray spaces were inserted between its letters.

    Some filings split a word across HTML tags, so get_text() turns
    'RISK FACTORS' into 'RIS K FACTORS'. 'risk' -> r'r\\s*i\\s*s\\s*k'.
    """
    return r"\s*".join(word)


# \s* = optional whitespace, "." in management.s matches ' or the curly ’
ITEM_1A_START = rf"item\s*1a\.?\s*{loose('risk')}\s*{loose('factors')}"
ITEM_1A_END = rf"item\s*1b\.?\s*{loose('unresolved')}"
ITEM_7_START = rf"item\s*7\.?\s*{loose('management')}.s\s*{loose('discussion')}"
ITEM_7_END = rf"item\s*7a\.?\s*{loose('quantitative')}"


def extract_section(text, start_pattern, end_pattern):
    """Return the real section between the start and end headings.

    Headings also appear in the table of contents and inside sentences
    ("see Item 1A. Risk Factors"), so each start is paired with the first
    end heading after it. Several starts can share one end (cross-references
    before the real heading), so for each end we keep the LATEST start.
    The real section is then the longest remaining span.
    """
    start_for_end = {}  # end position -> latest start position
    for match in re.finditer(start_pattern, text, re.IGNORECASE):
        end_match = re.search(end_pattern, text[match.end():], re.IGNORECASE)
        if end_match is None:
            continue
        end = match.end() + end_match.start()
        start_for_end[end] = max(start_for_end.get(end, 0), match.start())

    if not start_for_end:
        raise ValueError("Section not found")

    end, start = max(start_for_end.items(), key=lambda pair: pair[0] - pair[1])
    return text[start:end].strip()


MIN_WORDS = 500  # a real section is thousands of words; less means a bad match


def checked_section(name, text, start_pattern, end_pattern):
    section = extract_section(text, start_pattern, end_pattern)
    words = len(section.split())
    if words < MIN_WORDS:
        raise ValueError(
            f"{name} is only {words} words. The filing may incorporate it by "
            "reference from another document (common for banks)."
        )
    return section


def get_sections(ticker):
    """Full pipeline: ticker -> filing -> {'risk_factors': ..., 'mdna': ...}."""
    cik = get_cik(ticker)
    filing = get_latest_10k(cik)
    text = html_to_text(get_filing_html(ticker, cik, filing))
    return {
        "ticker": ticker.upper(),
        "filing": filing,
        "risk_factors": checked_section("Risk Factors", text, ITEM_1A_START, ITEM_1A_END),
        "mdna": checked_section("MD&A", text, ITEM_7_START, ITEM_7_END),
    }


if __name__ == "__main__":
    # Usage: python fetch.py NVDA   (defaults to AAPL)
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    result = get_sections(ticker)

    for key, filename in [("risk_factors", "risk_factors"), ("mdna", "mdna")]:
        path = os.path.join("data", f"{result['ticker']}_{filename}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(result[key])
        print(f"{key}: {len(result[key].split()):,} words -> {path}")
