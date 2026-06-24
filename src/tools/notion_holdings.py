"""
Notion Holdings Sync — pulls your live holdings from Notion
and makes them available as the dynamic watchlist.
Falls back to hardcoded list if Notion is unavailable.
Loaded once at module level and cached — shared across all importers.
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.getenv("NOTION_API_KEY")
HOLDINGS_DATABASE_ID = "9dd63515-c7ae-4f2c-bbc9-a73c6c65bbd1"

FALLBACK_WATCHLIST = {
    "NVDA": {"name": "Nvidia", "sector": "AI-Infra / Compute", "role": "Core / Anchor"},
    "TSM": {"name": "TSMC", "sector": "AI-Infra / Compute", "role": "Core / Anchor"},
    "AVGO": {"name": "Broadcom", "sector": "AI-Infra / Compute", "role": "Core / Anchor"},
    "AMD": {"name": "AMD", "sector": "AI-Infra / Compute", "role": "Satellite"},
    "ASML": {"name": "ASML", "sector": "AI-Infra / Compute", "role": "Satellite"},
    "ARM": {"name": "Arm Holdings", "sector": "AI-Infra / Compute", "role": "Satellite"},
    "ALAB": {"name": "Astera Labs", "sector": "AI-Infra / Compute", "role": "Satellite"},
    "PLTR": {"name": "Palantir", "sector": "AI-Apps", "role": "Satellite"},
    "APP": {"name": "Applovin", "sector": "AI-Apps", "role": "Satellite"},
    "CEG": {"name": "Constellation Energy", "sector": "AI-Energy", "role": "Satellite"},
}


def get_holdings_from_notion() -> dict:
    """
    Pull all holdings from Notion Holdings database.
    Returns dict of {ticker: {name, sector, role, rating, shares, avg_cost, thesis}}
    """
    if not NOTION_API_KEY:
        print("No NOTION_API_KEY found — using fallback watchlist.")
        return FALLBACK_WATCHLIST

    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    url = f"https://api.notion.com/v1/databases/{HOLDINGS_DATABASE_ID}/query"

    try:
        results = []
        cursor = None
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                print(f"Notion API error {response.status_code} — using fallback.")
                return FALLBACK_WATCHLIST
            body = response.json()
            results.extend(body.get("results", []))
            if not body.get("has_more"):
                break
            cursor = body.get("next_cursor")
        holdings = {}

        for page in results:
            props = page.get("properties", {})

            ticker_prop = props.get("Ticker", {})
            ticker = ""
            if ticker_prop.get("type") == "rich_text":
                rt = ticker_prop.get("rich_text", [])
                ticker = rt[0]["plain_text"].strip().upper() if rt else ""

            if not ticker:
                continue

            name_prop = props.get("Name", {})
            name = ""
            if name_prop.get("type") == "title":
                title = name_prop.get("title", [])
                name = title[0]["plain_text"].strip() if title else ticker

            sector = props.get("Sector", {}).get("select", {})
            sector = sector.get("name", "") if sector else ""

            role = props.get("Role", {}).get("select", {})
            role = role.get("name", "") if role else ""

            rating = props.get("Rating", {}).get("select", {})
            rating = rating.get("name", "") if rating else ""

            shares = props.get("Shares", {}).get("number") or 0
            avg_cost = props.get("Avg Cost", {}).get("number") or 0

            thesis_prop = props.get("Thesis (Durable)", {})
            thesis = ""
            if thesis_prop.get("type") == "rich_text":
                rt = thesis_prop.get("rich_text", [])
                thesis = rt[0]["plain_text"].strip() if rt else ""

            account_prop = props.get("Account", {})
            account = ""
            if account_prop.get("type") == "select":
                account = (account_prop.get("select") or {}).get("name", "")
            elif account_prop.get("type") == "rich_text":
                rt = account_prop.get("rich_text", [])
                account = rt[0]["plain_text"].strip() if rt else ""

            holdings[ticker] = {
                "name": name,
                "sector": sector,
                "role": role,
                "rating": rating,
                "shares": shares,
                "avg_cost": avg_cost,
                "thesis": thesis,
                "account": account,
            }

        print(f"Loaded {len(holdings)} holdings from Notion.")
        return holdings if holdings else FALLBACK_WATCHLIST

    except Exception as e:
        print(f"Notion sync error: {e} — using fallback.")
        return FALLBACK_WATCHLIST


# ── Module-level cache — loaded once, shared across all importers ─────────────
_holdings_cache = None
_active_account: str = ""  # "" = all accounts


def set_active_account(account: str) -> None:
    global _active_account
    _active_account = account.strip()


def get_active_account() -> str:
    return _active_account


def get_holdings_cached(account_filter: str = None) -> dict:
    """Return cached holdings, optionally filtered by account name."""
    global _holdings_cache
    if _holdings_cache is None:
        _holdings_cache = get_holdings_from_notion()
    filt = account_filter if account_filter is not None else _active_account
    if not filt:
        return _holdings_cache
    return {t: d for t, d in _holdings_cache.items() if d.get("account", "").lower() == filt.lower()}


def list_accounts() -> list[str]:
    """Return sorted list of unique account names in holdings."""
    global _holdings_cache
    if _holdings_cache is None:
        _holdings_cache = get_holdings_from_notion()
    accounts = sorted({d.get("account", "") for d in _holdings_cache.values() if d.get("account")})
    return accounts


def get_watchlist_tickers() -> list:
    return list(get_holdings_cached().keys())


def get_ticker_name_map() -> dict:
    holdings = get_holdings_cached()
    return {t: d["name"] for t, d in holdings.items()}


def reload_holdings() -> dict:
    """Clear the in-process cache and re-fetch from Notion."""
    global _holdings_cache
    _holdings_cache = None
    _holdings_cache = get_holdings_from_notion()
    return _holdings_cache


# ── Notion Write-Back ─────────────────────────────────────────────────────────

def _notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _find_page_id(ticker: str) -> str | None:
    """Find the Notion page ID for a given ticker."""
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{HOLDINGS_DATABASE_ID}/query",
            headers=_notion_headers(),
            json={"filter": {"property": "Ticker", "rich_text": {"equals": ticker.upper()}}},
        )
        results = r.json().get("results", [])
        return results[0]["id"] if results else None
    except Exception:
        return None


def add_to_watchlist(ticker: str, name: str = "") -> str:
    """Create a new watchlist row in Notion (shares=0)."""
    ticker = ticker.upper()
    if not NOTION_API_KEY:
        return "❌ NOTION_API_KEY not set."
    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=_notion_headers(),
            json={
                "parent": {"database_id": HOLDINGS_DATABASE_ID},
                "properties": {
                    "Name":   {"title":     [{"text": {"content": name or ticker}}]},
                    "Ticker": {"rich_text": [{"text": {"content": ticker}}]},
                    "Shares": {"number": 0},
                },
            },
        )
        if r.status_code == 200:
            reload_holdings()
            return f"✅ <b>{ticker}</b> added to watchlist."
        return f"❌ Notion error {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return f"❌ Error: {str(e)[:100]}"


def update_position(ticker: str, shares: float, avg_cost: float) -> str:
    """Update or create a position with new share count and average cost."""
    ticker = ticker.upper()
    if not NOTION_API_KEY:
        return "❌ NOTION_API_KEY not set."
    try:
        page_id = _find_page_id(ticker)
        props = {"Shares": {"number": shares}, "Avg Cost": {"number": avg_cost}}
        if page_id:
            r = requests.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=_notion_headers(),
                json={"properties": props},
            )
        else:
            # New ticker — create row
            props["Name"]   = {"title":     [{"text": {"content": ticker}}]}
            props["Ticker"] = {"rich_text": [{"text": {"content": ticker}}]}
            r = requests.post(
                "https://api.notion.com/v1/pages",
                headers=_notion_headers(),
                json={"parent": {"database_id": HOLDINGS_DATABASE_ID}, "properties": props},
            )
        if r.status_code == 200:
            reload_holdings()
            return f"✅ <b>{ticker}</b>: {shares:.0f} shares @ ${avg_cost:.2f} saved to Notion."
        return f"❌ Notion error {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return f"❌ Error: {str(e)[:100]}"


def update_rating(ticker: str, rating: str) -> str:
    """Update the Rating field for a ticker in the Holdings DB."""
    ticker = ticker.upper()
    # Normalise rating aliases
    _aliases = {
        "buy": "Buy", "strong buy": "Buy",
        "spec buy": "Spec. Buy", "spec. buy": "Spec. Buy", "speculative buy": "Spec. Buy", "spec": "Spec. Buy",
        "allocate": "Allocate",
        "hold": "Hold",
        "watchlist": "Watchlist", "watch": "Watchlist",
        "researching": "Researching", "research": "Researching",
        "tactical": "Tactical / To Review", "to review": "Tactical / To Review",
        "sell": "Sell",
    }
    normalised = _aliases.get(rating.lower().strip(), rating.strip().title())
    if not NOTION_API_KEY:
        return "❌ NOTION_API_KEY not set."
    try:
        page_id = _find_page_id(ticker)
        if not page_id:
            return f"❌ {ticker} not found in Notion."
        r = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=_notion_headers(),
            json={"properties": {"Rating": {"select": {"name": normalised}}}},
        )
        if r.status_code == 200:
            reload_holdings()
            return f"✅ <b>{ticker}</b> rated <b>{normalised}</b> in Notion."
        return f"❌ Notion error {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return f"❌ Error: {str(e)[:100]}"


def update_thesis(ticker: str, thesis: str) -> str:
    """Update the Thesis (Durable) field for a ticker in the Holdings DB."""
    ticker = ticker.upper()
    if not NOTION_API_KEY:
        return "❌ NOTION_API_KEY not set."
    if not thesis.strip():
        return "❌ Thesis text is empty."
    try:
        page_id = _find_page_id(ticker)
        if not page_id:
            return f"❌ {ticker} not found in Notion."
        r = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=_notion_headers(),
            json={"properties": {"Thesis (Durable)": {"rich_text": [{"text": {"content": thesis.strip()[:2000]}}]}}},
        )
        if r.status_code == 200:
            reload_holdings()
            return f"✅ <b>{ticker}</b> thesis updated in Notion."
        return f"❌ Notion error {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return f"❌ Error: {str(e)[:100]}"


def sell_position(ticker: str) -> str:
    """Set shares to 0 — moves ticker from portfolio to watchlist."""
    ticker = ticker.upper()
    if not NOTION_API_KEY:
        return "❌ NOTION_API_KEY not set."
    try:
        page_id = _find_page_id(ticker)
        if not page_id:
            return f"❌ {ticker} not found in Notion."
        r = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=_notion_headers(),
            json={"properties": {"Shares": {"number": 0}}},
        )
        if r.status_code == 200:
            reload_holdings()
            return f"✅ <b>{ticker}</b> sold — moved to watchlist (shares set to 0)."
        return f"❌ Notion error {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return f"❌ Error: {str(e)[:100]}"


# ── Trade Journal ─────────────────────────────────────────────────────────────

JOURNAL_DATABASE_ID = "57ec5347-fc06-490d-9a60-e99e65a3d9bc"


def log_trade_entry(ticker: str, action: str, shares: float, entry_price: float,
                    rationale: str = "", theme: str = "") -> str:
    """Create a new Trade Journal entry in Notion."""
    ticker = ticker.upper()
    if not theme:
        try:
            from src.tools.themes import THESIS_MAP
            theme = THESIS_MAP.get(ticker, "Other")
        except Exception:
            theme = "Other"

    date_str = datetime.now().strftime("%Y-%m-%d")
    name = f"{ticker} {action} · {datetime.now().strftime('%d %b %Y')}"

    if not rationale:
        holdings = get_holdings_cached()
        thesis = holdings.get(ticker, {}).get("thesis", "")
        rationale = thesis[:300] if thesis else f"{action} {ticker}"

    try:
        r = requests.post(
            "https://api.notion.com/v1/pages",
            headers=_notion_headers(),
            json={
                "parent": {"database_id": JOURNAL_DATABASE_ID},
                "properties": {
                    "Name":        {"title":     [{"text": {"content": name}}]},
                    "Ticker":      {"rich_text": [{"text": {"content": ticker}}]},
                    "Action":      {"select":    {"name": action}},
                    "Shares":      {"number": shares},
                    "Entry Price": {"number": entry_price},
                    "Entry Date":  {"date": {"start": date_str}},
                    "Rationale":   {"rich_text": [{"text": {"content": rationale[:2000]}}]},
                    "Theme":       {"select":    {"name": theme}},
                    "Status":      {"select":    {"name": "Open"}},
                },
            },
        )
        if r.status_code == 200:
            return f"📓 Logged: {name}"
        return f"⚠️ Journal log failed ({r.status_code})"
    except Exception as e:
        return f"⚠️ Journal error: {str(e)[:80]}"


def close_trade_entry(ticker: str, exit_price: float, exit_note: str = "") -> str:
    """Close the latest Open Trade Journal entry for a ticker with P&L calculation."""
    ticker = ticker.upper()
    date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        r = requests.post(
            f"https://api.notion.com/v1/databases/{JOURNAL_DATABASE_ID}/query",
            headers=_notion_headers(),
            json={
                "filter": {
                    "and": [
                        {"property": "Ticker", "rich_text": {"equals": ticker}},
                        {"property": "Status", "select": {"equals": "Open"}},
                    ]
                },
                "sorts": [{"timestamp": "created_time", "direction": "descending"}],
                "page_size": 1,
            },
        )
        results = r.json().get("results", [])
        if not results:
            return f"⚠️ No open journal entry found for {ticker}."

        page = results[0]
        page_id = page["id"]
        props = page.get("properties", {})
        entry_price = props.get("Entry Price", {}).get("number") or 0
        pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price else 0

        update_props = {
            "Exit Price":       {"number": exit_price},
            "Exit Date":        {"date": {"start": date_str}},
            "Realized PnL Pct": {"number": pnl_pct},
            "Status":           {"select": {"name": "Closed"}},
        }
        if exit_note:
            existing_rt = props.get("Rationale", {}).get("rich_text", [])
            existing_text = existing_rt[0]["plain_text"] if existing_rt else ""
            new_text = (existing_text + "\n\nEXIT: " + exit_note).strip()[:2000]
            update_props["Rationale"] = {"rich_text": [{"text": {"content": new_text}}]}

        rr = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=_notion_headers(),
            json={"properties": update_props},
        )
        if rr.status_code == 200:
            emoji = "🟢" if pnl_pct >= 0 else "🔴"
            return f"📓 Journal closed: {ticker} {emoji} {pnl_pct:+.1f}% (${entry_price:.2f} → ${exit_price:.2f})"
        return f"⚠️ Journal close failed ({rr.status_code})"
    except Exception as e:
        return f"⚠️ Journal close error: {str(e)[:80]}"


def get_journal_entries(status: str = None, limit: int = 15) -> list:
    """Fetch Trade Journal entries, optionally filtered by Open/Closed status."""
    try:
        payload: dict = {
            "sorts": [{"timestamp": "created_time", "direction": "descending"}],
            "page_size": limit,
        }
        if status:
            payload["filter"] = {"property": "Status", "select": {"equals": status}}
        r = requests.post(
            f"https://api.notion.com/v1/databases/{JOURNAL_DATABASE_ID}/query",
            headers=_notion_headers(),
            json=payload,
        )
        return r.json().get("results", [])
    except Exception:
        return []


if __name__ == "__main__":
    print("Testing Notion holdings sync...\n")
    holdings = get_holdings_from_notion()
    for ticker, data in holdings.items():
        print(f"{ticker} ({data.get('name', '')}) — {data.get('sector', '')} — {data.get('role', '')} — Rating: {data.get('rating', '')}")