import os
import sys

import requests
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


if __name__ == "__main__":
    # Usage: python fetch.py NVDA   (defaults to AAPL)
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    cik = get_cik(ticker)
    filing = get_latest_10k(cik)
    print(ticker.upper(), cik, filing)
    print(build_filing_url(cik, filing))
