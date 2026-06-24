"""
Catalyst Calendar — forward event database with portfolio read-through.
Covers: FOMC dates, major tech conferences, earnings for held positions.
"""
from datetime import datetime, date, timedelta
from src.tools.earnings_calendar import get_earnings_dates


# ── Hard-coded known events 2026 ──────────────────────────────────────────────
KNOWN_EVENTS = [
    # FOMC meetings 2026 (approximate — check fed.gov for exact dates)
    {"date": "2026-01-28", "event": "FOMC Rate Decision", "type": "MACRO", "tickers": ["ALL"], "note": "Fed policy — affects all rate-sensitive positions"},
    {"date": "2026-03-18", "event": "FOMC Rate Decision", "type": "MACRO", "tickers": ["ALL"], "note": "Watch for dot plot update"},
    {"date": "2026-05-06", "event": "FOMC Rate Decision", "type": "MACRO", "tickers": ["ALL"], "note": "Mid-year policy check"},
    {"date": "2026-06-17", "event": "FOMC Rate Decision", "type": "MACRO", "tickers": ["ALL"], "note": "SEP and dot plot — big one"},
    {"date": "2026-07-29", "event": "FOMC Rate Decision", "type": "MACRO", "tickers": ["ALL"], "note": "Summer meeting"},
    {"date": "2026-09-16", "event": "FOMC Rate Decision", "type": "MACRO", "tickers": ["ALL"], "note": "SEP update — market-moving"},
    {"date": "2026-11-04", "event": "FOMC Rate Decision", "type": "MACRO", "tickers": ["ALL"], "note": "Post-election meeting"},
    {"date": "2026-12-16", "event": "FOMC Rate Decision", "type": "MACRO", "tickers": ["ALL"], "note": "Year-end SEP and dot plot"},

    # Tech conferences
    {"date": "2026-03-20", "event": "NVIDIA GTC Conference", "type": "CONFERENCE", "tickers": ["NVDA", "ALAB", "CRDO", "TSM", "AMD"], "note": "Jensen Huang keynote — AI infrastructure thesis reset. Watch for Blackwell Ultra, NVLink 5, roadmap updates."},
    {"date": "2026-08-25", "event": "Hot Chips (CPU/GPU Architecture)", "type": "CONFERENCE", "tickers": ["NVDA", "AMD", "INTC", "ARM"], "note": "Next-gen chip architecture previews — 12-18 month forward signal"},
    {"date": "2026-06-02", "event": "Computex (Taiwan)", "type": "CONFERENCE", "tickers": ["TSM", "NVDA", "AMD", "ASML", "ALAB"], "note": "PC/AI hardware roadmaps, TSMC process updates"},
    {"date": "2026-11-30", "event": "AWS re:Invent", "type": "CONFERENCE", "tickers": ["AMZN", "NVDA", "ALAB", "CRDO"], "note": "AI cloud infrastructure — watch for custom silicon announcements"},
    {"date": "2026-05-19", "event": "Microsoft Build", "type": "CONFERENCE", "tickers": ["MSFT", "NVDA", "AMD", "PLTR"], "note": "AI developer platform — Copilot and Azure AI roadmap"},

    # Geopolitical / macro
    {"date": "2026-07-01", "event": "US Chip Export Control Review", "type": "GEOPOLITICAL", "tickers": ["NVDA", "AMD", "ALAB", "MU", "ASML"], "note": "BIS reviews export rules quarterly — affects China revenue for all semis"},
    {"date": "2026-10-01", "event": "US Chip Export Control Review", "type": "GEOPOLITICAL", "tickers": ["NVDA", "AMD", "ALAB", "MU", "ASML"], "note": "Q4 review — watch ahead of US election cycle"},
]

TYPE_EMOJI = {
    "MACRO":       "🏦",
    "CONFERENCE":  "🎯",
    "EARNINGS":    "📋",
    "GEOPOLITICAL":"⚠️",
}


def get_catalyst_calendar(held_tickers: list, days_ahead: int = 60) -> str:
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)

    events = []

    # ── Hard-coded events ─────────────────────────────────────────────────────
    for e in KNOWN_EVENTS:
        try:
            ev_date = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if today <= ev_date <= cutoff:
            days_until = (ev_date - today).days
            relevant = (
                "ALL" in e.get("tickers", []) or
                any(t in held_tickers for t in e.get("tickers", []))
            )
            if relevant:
                events.append({
                    "date": ev_date,
                    "days": days_until,
                    "type": e["type"],
                    "event": e["event"],
                    "tickers": [t for t in e.get("tickers", []) if t in held_tickers or t == "ALL"],
                    "note": e.get("note", ""),
                })

    # ── Earnings for held positions ───────────────────────────────────────────
    try:
        earnings = get_earnings_dates(held_tickers)
        for ticker, data in earnings.items():
            days_until = data.get("days_until")
            if days_until is None or days_until < 0 or days_until > days_ahead:
                continue
            try:
                ev_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except Exception:
                continue
            events.append({
                "date": ev_date,
                "days": days_until,
                "type": "EARNINGS",
                "event": f"{ticker} Earnings",
                "tickers": [ticker],
                "note": data.get("date", ""),
            })
    except Exception:
        pass

    events.sort(key=lambda x: x["date"])

    if not events:
        return f"📅 <b>Catalyst Calendar — Next {days_ahead} Days</b>\n\nNo major catalysts found in this window."

    msg = f"📅 <b>Catalyst Calendar — Next {days_ahead} Days</b>\n"
    msg += f"<i>{today.strftime('%d %b %Y')} · {len(events)} events</i>\n\n"

    current_month = None
    for e in events:
        month = e["date"].strftime("%B %Y")
        if month != current_month:
            msg += f"\n<b>{month}</b>\n"
            current_month = month

        emoji = TYPE_EMOJI.get(e["type"], "•")
        days_str = f"in {e['days']}d" if e['days'] > 0 else "TODAY"
        tickers_str = " · ".join(e["tickers"]) if e["tickers"] and e["tickers"] != ["ALL"] else ""
        ticker_tag = f" <i>[{tickers_str}]</i>" if tickers_str else ""

        msg += f"{emoji} <b>{e['date'].strftime('%d %b')}</b> ({days_str}) — {e['event']}{ticker_tag}\n"
        if e["note"] and e["type"] != "EARNINGS":
            msg += f"   <i>{e['note'][:120]}</i>\n"

    return msg
