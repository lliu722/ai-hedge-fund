# Project State — 2026-06-26

---

## What Currently Works (Verified in Production)

| Feature | Status |
|---|---|
| Morning briefing (7am HKT) | ✅ Live |
| Sunday digest | ✅ Live |
| Breaking news alerts (every 2hrs) | ✅ Live |
| US / HK / EU market open alerts | ✅ Live |
| US / HK / EU market close alerts | ✅ Live |
| AI Shadow Portfolio post-close (buttons + drill-down) | ✅ Live |
| Deep dive (9-section, any ticker) | ✅ Live |
| Proactive analyst (auto mini-dives) | ✅ Live |
| Portfolio P&L table | ✅ Live |
| Watchlist view | ✅ Live |
| Entry Points button + tool | ✅ Live (added 2026-06-26) |
| Earnings calendar | ✅ Live |
| Earnings transcript analysis | ✅ Live |
| Notion write-back (buy, sell, rate, thesis) | ✅ Live |
| Trade journal | ✅ Live |
| Custom price alerts | ✅ Live |
| Watchlist price targets | ✅ Live |
| Risk engine (concentration, correlation, drawdown) | ✅ Live |
| Macro regime detector | ✅ Live |
| Theme health scores | ✅ Live |
| Theme radar (55-ETF Z-score) | ✅ Live |
| Monthly 复盘 | ✅ Live |
| Quant screen / signal / optimizer / backtest | ✅ Live |
| Quant paper trading | ✅ Live |
| 腾位置 portfolio advisor | ✅ Live |
| Geopolitical pulse | ✅ Live |
| Industry read-through map | ✅ Live |
| Research library (save/search notes + dives) | ✅ Live |
| AI stock picks (3 personas) | ✅ Live |

---

## What Is Partially Done

| Feature | Status | Gap |
|---|---|---|
| Macro regime → decisions | ⚠️ Partial | Regime detected (RISK-ON/OFF/etc.) but not fed into shadow portfolio or entry points recommendations |
| Shadow portfolio aggregation | ⚠️ Changed | 3-persona design replaced by single-verdict design. Old persona logic still in `recommendations.py` for AI Picks but no tiebreaker exists if personas disagree there |
| Research library cross-reference | ⚠️ Partial | Deep dives auto-saved; no cross-reference against current positions |

---

## What Is Broken / Unknown

| Item | Status |
|---|---|
| `MemorySaver` checkpointer resets on Railway restart | ⚠️ Known — conversation context lost on redeploy |
| `app/backend` + `app/frontend` | ❓ Not deployed, may be stale relative to active system |
| `v2/` pipeline | ❓ Experimental, not in production, maintenance status unknown |
| `src/agents/` legacy agents | ❓ Not called by the bot, may be out of date |
| SQLite persistence across Railway redeploys | ❓ Unverified — Railway persistent volume should retain `.db` files but not confirmed |

---

## What Needs Verification

- Does SQLite (research.db, alerts.db) actually persist across Railway redeploys?
- Are the legacy `src/agents/` still functional if called directly?
- Does the `app/backend` Alembic migration work if set up fresh?

---

## Current Blockers

None — the system is fully operational. The next build (Thesis Watchdog) has no blockers.

---

## Tool Count: 46

Last updated: 2026-06-26
