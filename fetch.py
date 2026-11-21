import os
import requests
from dotenv import load_dotenv

load_dotenv()

HEADERS = {"User-Agent": os.getenv("SEC_USER_AGENT")}


def get_cik(ticker):
    url = "https://www.sec.gov/files/company_tickers.json"
    response = requests.get(url, headers=HEADERS)
    data = response.json()

    for company in data.values():
        if company["ticker"].upper() == ticker.upper():
            return str(company["cik_str"]).zfill(10)

    raise ValueError(f"Ticker {ticker} not found")


if __name__ == "__main__":
    print(get_cik("AAPL"))