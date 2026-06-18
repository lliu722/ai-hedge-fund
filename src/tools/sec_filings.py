import requests
from datetime import datetime

HEADERS = {"User-Agent": "ai-investor-research louislhk0523@gmail.com"}
BASE_URL = "https://data.sec.gov"

def get_cik(ticker):
    url = "https://www.sec.gov/files/company_tickers.json"
    response = requests.get(url, headers=HEADERS)
    data = response.json()
    for entry in data.values():
        if entry["ticker"].upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    return None

def get_recent_filings(ticker, form_type="10-K", count=3):
    cik = get_cik(ticker)
    if not cik:
        print(f"Could not find CIK for {ticker}")
        return []

    url = f"{BASE_URL}/submissions/CIK{cik}.json"
    response = requests.get(url, headers=HEADERS)

    if response.status_code != 200:
        print(f"Error fetching filings for {ticker}: {response.status_code}")
        return []

    data = response.json()
    filings = data.get("filings", {}).get("recent", {})

    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    accessions = filings.get("accessionNumber", [])

    results = []
    for i, form in enumerate(forms):
        if form == form_type and len(results) < count:
            results.append({
                "ticker": ticker,
                "form": form,
                "date": dates[i],
                "accession": accessions[i],
                "filing_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}&dateb=&owner=include&count=10"
            })

    return results

def get_filing_summary(ticker):
    print(f"Fetching SEC filings for {ticker}...")
    annual = get_recent_filings(ticker, "10-K", 1)
    quarterly = get_recent_filings(ticker, "10-Q", 3)
    earnings = get_recent_filings(ticker, "8-K", 4)
    return {
        "ticker": ticker,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "10-K": annual,
        "10-Q": quarterly,
        "8-K": earnings,
    }

if __name__ == "__main__":
    print("Testing SEC EDGAR integration...\n")
    for ticker in ["NVDA", "TSM"]:
        summary = get_filing_summary(ticker)
        print(f"\n{ticker} recent filings:")
        print(f"  Latest 10-K: {summary['10-K'][0]['date'] if summary['10-K'] else 'None'}")
        print(f"  Recent 10-Qs: {[f['date'] for f in summary['10-Q']]}")
        print(f"  Recent 8-Ks: {[f['date'] for f in summary['8-K']]}")