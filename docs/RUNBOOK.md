# Runbook — Operations & Debugging

---

## Setup from Fresh Clone

```bash
git clone https://github.com/lliu722/ai-hedge-fund.git
cd ai-hedge-fund

# Install Poetry if not present
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Copy and fill environment variables
cp .env.example .env
# Edit .env with real keys (see .env.example for all required variables)

# Run the bot
poetry run python -m src.tools.telegram_bot
```

---

## Common Commands

| Task | Command |
|---|---|
| Run bot locally | `poetry run python -m src.tools.telegram_bot` |
| Run tests | `poetry run pytest tests/ -x -q` |
| Format check | `poetry run black --check src/tools/` |
| Lint | `poetry run flake8 src/tools/ --max-line-length=420` |
| Deploy | `git push origin main` (Railway auto-deploys) |
| Add dependency | `poetry add <package>` then push |

---

## Deploy to Railway

Railway deploys automatically on every push to `main`. No manual step needed.

```bash
git add src/tools/telegram_bot.py [other files]
git commit -m "description"
git push origin main
# Wait ~2 minutes, then test in Telegram
```

If Railway fails to deploy:
- Check Railway dashboard logs for the error
- Common cause: syntax error in `telegram_bot.py` — run `poetry run python -c "import src.tools.telegram_bot"` locally first
- Common cause: missing environment variable — check Railway environment settings

---

## Debugging: Bot Not Responding

**Symptom:** Message sent, "Working on it..." appears but no response.

Causes and fixes:

1. **Railway still restarting** — wait 2 min after a push, try again
2. **LangGraph checkpointer corruption** — previous crashed call left broken state. The bot auto-retries with a `_fresh` thread ID. If it still fails, the error message will show up in Telegram.
3. **DeepSeek timeout** — DeepSeek calls have a 60s default timeout. Complex queries can time out. Retry.
4. **Tool import error** — check Railway logs. Often caused by a new tool that imports a missing module.

Local debugging:
```bash
poetry run python -c "
from src.tools.telegram_bot import agent, SYSTEM_PROMPT
from langchain_core.messages import HumanMessage, SystemMessage
result = agent.invoke(
    {'messages': [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content='show portfolio')]},
    config={'configurable': {'thread_id': 'debug_test'}}
)
print(result['messages'][-1].content[:500])
"
```

---

## Debugging: Wrong Market Alert (e.g. HK open showing US stocks)

The market open/close filters are in `scheduler.py` in `_MARKET_CFG`:
- `open_filter` — lambda that returns True for tickers belonging to this market
- HK filter: `lambda t: t.endswith(".HK") or t.endswith(".SS") or t.endswith(".SZ")`
- US filter: `lambda t: not any(t.endswith(s) for s in [".HK", ".SS", ".SZ", ".TW"])`

If a US ticker appears in a HK alert, check that the HK open section uses `cfg["open_filter"]` and has no fallback to all tickers.

---

## Debugging: Telegram Message Cut Off

Telegram has a 4096 character limit. `notify.py → send_telegram()` auto-splits on newline boundaries. If a message is still cut off, the issue is likely in a tool that bypasses `send_telegram()` and calls the API directly.

---

## Debugging: Notion Read Failing

`notion_holdings.py` reads from Notion Holdings DB (`9dd63515-c7ae-4f2c-bbc9-a73c6c65bbd1`).

Common failures:
- `NOTION_API_KEY` not set or expired → check Railway env vars
- Notion API rate limit → automatic retry is not implemented; wait 30s and retry
- Field name mismatch → Notion property names are case-sensitive; check `notion_holdings.py` field mapping

---

## Debugging: Scheduler Not Firing

The scheduler runs in a background thread started by `telegram_bot.py`. Scheduled jobs use the `schedule` library with times in HKT or ET.

Check:
- Railway server timezone — Railway runs UTC. All times in `scheduler.py` use `pytz` or explicit UTC offsets.
- If a job runs but produces no output, check the function for a silent `except: pass` swallowing errors.

---

## SQLite Databases

Two SQLite databases are used locally (not committed to git):

| File | Contents | Managed by |
|---|---|---|
| `research.db` | Deep dives, earnings transcripts, manual notes, earnings surprise log | `research_library.py` |
| `alerts.db` (name may vary) | Custom price alerts, watchlist targets, alerted_today dedup | `alert_config.py` |
| `quant_paper.db` (name may vary) | Paper trade positions | `quant/paper_trade.py` |

These are auto-created on first run. To reset: delete the `.db` file and restart the bot.

---

## Testing the Shadow Portfolio Manually

```bash
poetry run python -c "
from src.tools.notion_holdings import get_holdings_cached
from src.tools.scheduler import _shadow_portfolio_message
held = {t: d for t, d in get_holdings_cached().items() if d.get('shares', 0) > 0}
summary_lines = ['NVDA +2.1%', 'TSM -0.8%', 'MU +3.2%']
_shadow_portfolio_message(summary_lines, held, 'US')
print('Check Telegram')
"
```

---

## Testing the Entry Points Tool

```bash
poetry run python -c "
from src.tools.telegram_bot import get_entry_points
print(get_entry_points.invoke({}))
"
```

---

## Smoke Test

Verify the bot loads without errors:
```bash
poetry run python -c "
from src.tools.telegram_bot import tools, agent
print(f'OK — {len(tools)} tools loaded')
"
```

Expected output: `OK — 46 tools loaded`

---

## Recovery: Bot Crashes on Startup

Most startup crashes are import errors in `telegram_bot.py`. Run:
```bash
poetry run python -c "import src.tools.telegram_bot" 2>&1
```

Fix the reported error, then push.

---

## Adding a New Dependency

```bash
poetry add <package-name>
git add pyproject.toml poetry.lock
git commit -m "deps: add <package-name>"
git push origin main
```

**Never** create a `requirements.txt` — Railway uses `pyproject.toml` via Poetry.
