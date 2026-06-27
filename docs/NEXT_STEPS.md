# Next Steps — Priority Backlog

Updated: 2026-06-26

---

## 🔴 High Priority

### 1. Thesis Watchdog

**Objective:** Proactively alert when a held position's original thesis is breaking down.
The bot currently never tells you to sell. This is the single biggest missing layer.

**How it works:**
- Runs weekly per held position (or after major earnings/news)
- Fetches current signals: recent news, earnings trend, revenue guidance, sector move
- Compares against saved Notion `Thesis` field for that ticker
- Fires Telegram alert when thesis is weakening: "⚠️ INTC — original thesis was AI PC refresh. Intel lost major customer to AMD, no AI ramp in 2 calls. Verdict: review position."

**Relevant files:**
- `src/tools/notion_holdings.py` — reads `Thesis` field from Notion
- `src/tools/scheduler.py` — add weekly job here
- `src/tools/llm.py` — `call_deepseek()` for thesis comparison
- `src/tools/news_fetcher.py` — fetch recent news per ticker

**Acceptance criteria:**
- Runs every Sunday (or configurable)
- Compares saved thesis vs current signals for every held position
- Fires alert only when DeepSeek confidence in thesis breakage is high (≥7/10)
- Does not fire on normal price pullbacks — only fundamental thesis changes

**Risk:** False positives will erode trust. Tune the threshold carefully.

---

### 2. Macro Regime → Decisions

**Objective:** The macro regime (`RISK-ON` / `RISK-OFF` / `STAGFLATION` / `EASING` / `LATE CYCLE`) is detected correctly via FRED but currently only displayed as a label. It should change what the system recommends.

**How it works:**
- In `RISK-OFF`: shadow portfolio should be more cautious (fewer BUY NOW, more WAIT)
- In `STAGFLATION`: energy overweight should increase; growth names flagged
- In `EASING`: rate-sensitive names (real estate, utilities) move to BUY tier
- Inject regime into `_shadow_portfolio_message()` and `get_entry_points()` prompts

**Relevant files:**
- `src/tools/ficc.py` — `get_macro_regime()` returns regime label
- `src/tools/scheduler.py` — `_shadow_portfolio_message()`
- `src/tools/telegram_bot.py` — `get_entry_points()`

**Acceptance criteria:**
- Regime label passed as context into shadow portfolio and entry points prompts
- DeepSeek instructed to adjust conviction based on regime
- Visible difference in output between RISK-ON and RISK-OFF regimes

---

## 🟡 Medium Priority

### 3. Recommendation Accuracy Tracking

**Objective:** Track whether the bot's buy/sell calls turned out to be right.
Currently the system recommends daily but never looks back.

**How it works:**
- When shadow portfolio fires, log each BUY NOW / SET LIMIT / SKIP call with: ticker, price, date, recommendation
- 4 weeks later, auto-check outcome: did BUY NOW names go up? Did SKIP names underperform?
- Monthly 复盘 includes accuracy statistics

**Relevant files:**
- `src/tools/research_library.py` — extend SQLite schema to add `recommendations` table
- `src/tools/scheduler.py` — log recommendations at close, evaluate 4 weeks later
- `src/tools/telegram_bot.py` — `get_monthly_review()` to include accuracy stats

**Acceptance criteria:**
- Each recommendation logged with ticker, price, date, verdict (BUY/WAIT/SKIP), rationale
- 4-week outcome evaluation runs automatically
- Monthly 复盘 includes: hit rate % by verdict type, best and worst calls

---

### 4. Macro Scenario Stress Test

**Objective:** "What if AI names fall 30%?" — simulate portfolio P&L under named scenarios.

**Relevant files:**
- `src/tools/risk.py` — extend with scenario simulation
- `src/tools/notion_holdings.py` — read positions and weights

**Acceptance criteria:**
- `get_stress_test(scenario)` tool that takes a scenario string and returns portfolio impact
- Scenarios: "AI falls 30%", "rates spike 100bp", "China tariffs escalate", "recession"
- Output: estimated P&L per position, total portfolio impact, which positions are most exposed

---

### 5. PDF Ingestion (Broker Research)

**Objective:** Bring in external broker research (Goldman, Morgan Stanley) and cross-reference against your positions.

**Relevant files:**
- New file: `src/tools/pdf_reader.py`
- `src/tools/research_library.py` — save parsed content

**Acceptance criteria:**
- Bot accepts a PDF file via Telegram
- Extracts key conclusions: rating, price target, key risks, catalysts
- Cross-references against held positions and watchlist
- Saves to research library

---

## ⚪ Low Priority / Parked

### 6. Live Quant Execution
Connect quant signals to a real broker API (Interactive Brokers / Alpaca).
Currently parked — the paper trade system needs more validation first.

### 7. VaR / Tail Risk (Risk Phase 2)
Value-at-risk calculation per position and portfolio level.
Needs: `scipy.stats` already in dependencies. Straightforward to implement.

### 8. Dynamic Rolling Correlation
60-day rolling correlation matrix vs static snapshot.
Low impact — current static correlation is sufficient.

### 9. Longitudinal Bias Tracking
Pattern analysis across 3+ months of 复盘 data.
Not buildable yet — needs data to accumulate first.
