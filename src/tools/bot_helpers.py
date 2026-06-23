"""
bot_helpers.py — Telegram sending, keyboard building, and utilities.
Imported by telegram_bot.py. No tool logic here.
"""
import os
import re
import json
import requests
from src.tools.notion_holdings import get_holdings_cached, FALLBACK_WATCHLIST

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# ── State ─────────────────────────────────────────────────────────────────────
_last_ticker:   dict = {}
_last_response: dict = {}

# ── Watchlist ─────────────────────────────────────────────────────────────────

def load_watchlist() -> dict:
    try:
        return get_holdings_cached()
    except Exception:
        return FALLBACK_WATCHLIST

WATCHLIST         = load_watchlist()
WATCHLIST_TICKERS = list(WATCHLIST.keys())
WATCHLIST_SET     = set(WATCHLIST_TICKERS)
PORTFOLIO         = {t: d for t, d in WATCHLIST.items() if (d.get("shares") or 0) > 0}
WATCHLIST_ONLY    = {t: d for t, d in WATCHLIST.items() if (d.get("shares") or 0) == 0}

def fmt(ticker: str) -> str:
    t    = ticker.upper()
    name = WATCHLIST.get(t, {}).get("name", "")
    return f"{t} ({name})" if name else t

# ── Keyboard ──────────────────────────────────────────────────────────────────

def build_keyboard(chat_id: str = None) -> dict:
    last           = _last_ticker.get(chat_id) if chat_id else None
    dd_text        = f"🔍 Deep Dive {last}" if last else "🔍 Deep Dive"
    dd_data        = f"deepdive:{last}"       if last else "deepdive"
    return {
        "inline_keyboard": [
            [{"text": "💼 Portfolio", "callback_data": "portfolio"},
             {"text": "🌅 Briefing",  "callback_data": "briefing"}],
            [{"text": "📅 Earnings",  "callback_data": "earnings"},
             {"text": dd_text,         "callback_data": dd_data}],
            [{"text": "🎓 Explain this", "callback_data": "explain"}],
        ]
    }

# ── Telegram helpers ──────────────────────────────────────────────────────────

def clean_for_telegram(text: str) -> str:
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.*?)\*',     r'<i>\1</i>', text)
    text = re.sub(r'#{1,6}\s+',    '',            text)
    text = re.sub(r'\|[^\n]+\|',   '',            text)
    text = re.sub(r'-{3,}',        '—',           text)
    text = re.sub(r'\n{3,}',       '\n\n',        text)
    return text.strip()

def send_message(text: str, chat_id: str = None, show_buttons: bool = True):
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    cleaned = clean_for_telegram(text)
    chunks  = [cleaned[i:i+4000] for i in range(0, len(cleaned), 4000)]
    for i, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id or TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}
        if show_buttons and i == len(chunks) - 1:
            payload["reply_markup"] = json.dumps(build_keyboard(chat_id or TELEGRAM_CHAT_ID))
        requests.post(url, json=payload)

def answer_callback(callback_query_id: str):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id}
    )

def get_updates(offset: int = 0) -> list:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    r   = requests.get(url, params={"offset": offset, "timeout": 30,
                                     "allowed_updates": ["message", "callback_query"]})
    return r.json().get("result", []) if r.status_code == 200 else []

def extract_ticker(text: str, chat_id: str = None) -> str | None:
    for m in re.findall(r'<b>([A-Z]{1,6})(?:\s|\(|<)', text):
        if m in WATCHLIST_SET:
            if chat_id: _last_ticker[chat_id] = m
            return m
    for w in re.findall(r'\b([A-Z]{2,6})\b', text):
        if w in WATCHLIST_SET:
            if chat_id: _last_ticker[chat_id] = w
            return w
    return None
