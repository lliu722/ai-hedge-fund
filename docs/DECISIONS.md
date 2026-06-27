# Technical Decisions

Major decisions already made or implied by the codebase, with reasons and tradeoffs.

---

## Architecture

### Single-file tool registry (`telegram_bot.py`)
**Decision:** All 46 `@tool` functions live in one file.
**Why:** LangGraph `create_react_agent` requires all tools in one list at agent creation time. Keeping them co-located with the agent avoids circular import issues and makes it easy to see the full tool surface at a glance.
**Tradeoff:** File is large (~2,000 lines). Offset by keeping business logic in separate modules (`deep_dive.py`, `scheduler.py`, etc.) — the tool functions themselves are thin wrappers.

### LangGraph ReAct agent (not custom graph)
**Decision:** `create_react_agent` with `MemorySaver` checkpointer.
**Why:** Simple, proven, handles tool-calling loop automatically. No need for custom graph when the pattern is always: user message → pick tool → call tool → synthesise → respond.
**Tradeoff:** Less control over the reasoning loop. Occasionally produces shallow responses. Mitigated by detailed SYSTEM_PROMPT instructions.

### DeepSeek V4 (`deepseek-chat`)
**Decision:** DeepSeek for all LLM calls, not GPT-4 or Claude.
**Why:** Cost. DeepSeek is dramatically cheaper for high-frequency tool calls (market open/close, morning briefing, breaking news every 2hrs). Quality is sufficient for investment analysis.
**Tradeoff:** Slower than GPT-4 Turbo on complex multi-step reasoning. Context window is smaller. Shadow portfolio and deep dives sometimes need retries.

---

## Data

### Notion as portfolio database (not SQL)
**Decision:** Holdings, watchlist, trade journal all in Notion.
**Why:** User already manages the portfolio in Notion. Sync would be error-prone. Direct read/write keeps Notion as the single source of truth.
**Tradeoff:** Notion API is slow (100-200ms per request, paginated). `get_holdings_cached()` caches on startup; `reload_holdings()` busts the cache manually.

### SQLite for transient data
**Decision:** Research library, custom alerts, earnings history, paper trades all in local SQLite.
**Why:** These are high-frequency reads/writes that don't belong in Notion. SQLite is zero-infra.
**Tradeoff:** Data is local to the Railway instance. If Railway redeploys, SQLite data persists on the volume (Railway persistent storage) but this should be verified.

### yfinance for prices (not a paid API)
**Decision:** yfinance for all equity prices.
**Why:** Free, supports US/HK/A-share/ADR tickers, good enough for EOD and ~15min delayed prices.
**Tradeoff:** Unofficial API, occasionally breaks. Falls back to CoinGecko for crypto. `prices.py` has a thread-safe cache to reduce yfinance calls.

### Tavily for news (not Bloomberg/Refinitiv)
**Decision:** Tavily web search for all news.
**Why:** Cost. Bloomberg Terminal API is prohibitively expensive for a personal system.
**Tradeoff:** News quality varies. `clean_news()` and `fmt_snippet()` in `llm.py` filter junk. Still misses paywalled articles (FT, WSJ).

---

## Telegram Bot Design

### Polling mode (not webhooks)
**Decision:** `bot.get_updates()` polling loop, not webhook.
**Why:** Simpler Railway deployment — no public URL required, no webhook registration.
**Tradeoff:** ~1s latency vs webhook's near-instant. Acceptable for an investment bot.

### HTML parse mode (not Markdown)
**Decision:** All messages use Telegram HTML (`<b>`, `<i>`).
**Why:** Telegram's Markdown mode has unpredictable escaping behaviour with financial symbols (`*`, `_`, `.`). HTML is predictable.
**Tradeoff:** Slightly more verbose message templates.

### Inline keyboard buttons (not reply keyboard)
**Decision:** `inline_keyboard` attached to messages, not a persistent reply keyboard.
**Why:** Inline buttons can be context-specific (e.g. per-ticker shadow portfolio detail). Reply keyboards are static and clutter the input area.

---

## Deployment

### Railway (not AWS/GCP/Render)
**Decision:** Railway for hosting.
**Why:** Zero-config deploy from git push, persistent volume for SQLite, reasonable cost for a single worker process.
**Tradeoff:** Railway has occasional cold-start latency. The `MemorySaver` checkpointer is in-process (not SQLite-backed) — conversation memory resets on restart.

### Poetry (not pip + requirements.txt)
**Decision:** Poetry for all dependency management.
**Why:** Lock file guarantees reproducible builds across local and Railway.
**Tradeoff:** Slightly slower install than pip. Must never create `requirements.txt` — it would shadow the Poetry lock.

### No Docker in production
**Decision:** Railway uses the `Procfile` directly, not the `docker/` folder.
**Why:** Railway's native Python buildpack is faster and simpler than building a Docker image on every push.
**Tradeoff:** `docker/` folder exists but is only for local dev reference.

---

## Scheduler Design

### `_MARKET_CFG` config-driven framework
**Decision:** Market open/close alerts are driven by a single dict (`_MARKET_CFG` in `scheduler.py`) with one entry per market.
**Why:** Adding EU or Japan open/close was previously copy-paste. The config dict means a new market is one dict entry with no new code paths.
**Tradeoff:** The lambda filters in the dict are non-obvious. Documented in `ARCHITECTURE.md`.

### Shadow portfolio: single DeepSeek call (not 3 parallel persona calls)
**Decision:** Shadow portfolio uses one structured DeepSeek call producing BUY/WAIT/SKIP + per-ticker details, with inline buttons for drill-down.
**Why:** User feedback — 3 verbose persona speeches were too much to read. A structured verdict + expandable details matches how investment decisions are actually made.
**Previous design:** 3 parallel calls to Cathie Wood / Druckenmiller / Damodaran personas. Still available in `recommendations.py` for the AI Picks feature.
