# 图纸 · AI Investment System — Blueprint (Single Source of Truth)

> **Read this first.** This is the architecture — *what the system is and how it fits together.*
> Its companion, **`BUILD_LOG.md` (工作日志)**, is the status tracker — *what is built, what is not, and where each piece lives.* Keep the two in sync: when you change the system, update the log.
> Last updated: 2026-06-29

---

## 0 · Orientation (plain English)

A personal, multi-asset **investment office** that runs 24/7 as a Telegram bot. It watches markets, reads the news and research, does analysis, tracks a real portfolio, forms its own buy/sell views, flags risk, and reviews its own decisions monthly. It is **not** a stock-price bot — it is the back-end of an investment office, run by a small team of standing AI "desks."

The architecture has exactly three parts:

1. **The Spine** — the *work* (the investment process, as functions).
2. **The Desks** — the *operators* (standing AI mandates that run the spine, on their own or on request).
3. **Standards & Support** — the *foundations* (shared data objects, delivery, rules, infrastructure).

Stack: **Python · LangGraph (DeepSeek V4) · Telegram · Notion · Railway.**
Data: yfinance · FRED · CoinGecko · Tavily · SEC EDGAR · GitHub API · arXiv.

### Working rules (for any agent editing this project)
- **Surgical patches only.** One change at a time.
- **Commit after every successful change.**
- **Update `BUILD_LOG.md` before moving on** (mark status + location).
- **Log decisions** in the build log's decision log.
- **Never break the live bot.** Migrate strangler-style — keep it running.

### North star
- **Proactive beats reactive** — position *before* the catalyst.
- Every feature must help answer the **5 daily questions**:
  1. What changed today?
  2. Which names are affected?
  3. How important is it?
  4. What catalysts are coming next?
  5. Is the thesis still intact?

---

## 1 · THE SPINE — function layer (the work)

The work itself, organised by process stage. Each function names the **desk** that operates it. (Status lives in the build log.)

### Intelligence — what's happening
- **Macro & geo scan** — macro / rates / geopolitics → *Idea Scout, Morning-Briefing*
- **News filter** — rank headlines; breaking ≥8/10 → *Morning-Briefing, Breaking-News*
- **Sector / theme monitor** — AI-sector depth, theme radar, rotation → *Idea Scout*
- **FICC / commodities / crypto feeds** — yield curve, futures, spot → *Morning-Briefing*

### Research — understand a name / theme
- **Deep dive** (9-section) → *Coverage Analyst*
- **Valuation** — P/E, EV/EBITDA, peers; DCF = socket → *Coverage Analyst*
- **Thesis check** — test saved thesis vs new info → *Coverage Analyst*
- **Earnings transcript + reaction** → *Coverage Analyst*
- **SEC filings** → *Coverage Analyst*
- **Report ingestion** — read library, extract thesis/risks → *Research Librarian*

### Decision — what to do
- **Conviction + sizing** → *House View*
- **腾位置 / portfolio advisor** — make room to buy → *House View*
- **Entry points** (tiered) → *House View*
- **House-view formation** (multi-persona) → *House View*
- **Quant screen / optimise / backtest** → *Quant Engine*

### Monitoring — track the book
- **Portfolio + watchlist P&L** → read by all desks
- **Price / target alerts** → *Risk Watch, Coverage Analyst*
- **Catalyst calendar** → *Idea Scout*
- **Thesis-health watch** → *Coverage Analyst*  ← the missing exit/sell discipline

### Review — learn (复盘)
- **Monthly 复盘** → Review workflow
- **Decision journal** (auto on trades)
- **Recommendation accuracy tracking**

### Risk — CROSS-CUTTING (also a desk: Risk Watch)
- **Concentration / correlation / drawdown** → *Risk Watch*
- **Macro regime detector** → *Risk Watch*
- **VaR / macro stress test** → *Risk Watch*

---

## 2 · THE DESKS — operators (the priority)

A desk is a **standing mandate**: it runs functions from the Spine on a **trigger** and **pushes** output. Every desk is defined by the same field set. A central **dispatcher** matches triggers → the desks that declared them.

**Per-desk field set:** Responsibility · Triggers · Functions operated · Output (object + template) · Destination · on_failure / degrade_to · Guards (cooldown / dedup / max chain depth) · **Sources** (the analytical lenses, multi-source).

> **Multi-source policy (see §3.2):** opinion desks present **Source A says X / Source B says Y / Source C says Z**, then a synthesis. Each source is a *module in our code* cribbed from a named repo, sharing our canonical objects — **not** a separate live framework.

---

### Desk 1 · Research Librarian
- **Responsibility:** turn incoming research (reports, transcripts, filings) into structured takeaways tied to the book.
- **Triggers:** a `Report` lands (event); manual "summarise X".
- **Functions operated:** Report ingestion; (feeds Research).
- **Output:** `Report` (with extracted thesis/risks) + `Signal`s. Template: 1-line takeaway + drivers + risks + names-touched.
- **Destination:** Telegram + Notion (research library).
- **on_failure:** if extraction fails → store raw + flag for manual; never drop the file.
- **Guards:** dedup by report hash.
- **Sources:** *single best method* (not A/B/C — this is mechanical). LlamaIndex (RAG/chunking) · TradingAgents news-analyst (extraction prompt) · FinGPT (financial summarisation). Mode: **LlamaIndex = library; others = reference.**

### Desk 2 · Coverage Analyst  ← richest desk; biggest live gap (thesis-health watch)
- **Responsibility:** maintain a live valuation + thesis on every covered name; re-test on new information.
- **Triggers:** continuous (weekly sweep) + earnings / 5%+ move (event) + you ask (pull).
- **Functions operated:** Deep dive · Valuation · Thesis check · Transcript · Filings.
- **Output:** updated `Thesis` (verdict: intact / weakening / broken) + valuation. Template: drivers · risks · valuation vs peers · verdict.
- **Destination:** Telegram (verdict-first) + Notion (thesis field).
- **on_failure:** transcript/data adapter down → degrade to price+news verdict, flagged "data pending," retry later.
- **Guards:** one full re-dive per name per day max.
- **Sources (MULTI — A/B/C):**
  - **A — TradingAgents fundamentals analyst:** fundamental health read.
  - **B — virattt/ai-hedge-fund Damodaran agent:** intrinsic-value / valuation lens.
  - **C — your existing deep-dive logic:** the 9-section house method.
  - Output shows each lens, then a synthesised verdict. Mode: **A & B vendored (reimplemented as modules); C native.**

### Desk 3 · Idea Scout
- **Responsibility:** hunt *outside* the book — new names, forming themes, leading signals.
- **Triggers:** scheduled scan (daily/weekly) + signal events (theme radar, GitHub/arXiv spikes).
- **Functions operated:** Macro scan · Sector/theme monitor · Catalyst calendar.
- **Output:** `Candidate` names + `Signal`s. Template: name · why now · 1-line thesis · where it fits.
- **Destination:** Telegram (morning/Sunday) + Notion (watchlist candidates).
- **on_failure:** a source down → scan the rest, flag the gap.
- **Guards:** max 2 new proactive dives/day; 7-day cooldown per name (existing rule).
- **Sources:** OpenBB screeners (library) · TradingAgents news/sentiment analysts (reference) · your theme radar + momentum (native). Multi-source = multiple *signal feeds*, not multiple opinions.

### Desk 4 · House View (CIO)  ← strongest multi-source desk
- **Responsibility:** form the system's own buy / sell / hold view, as if it ran the book.
- **Triggers:** post-close (schedule) + you ask.
- **Functions operated:** Conviction+sizing · 腾位置 · Entry points · House-view formation.
- **Output:** `Recommendation` (action + size + rationale). Template: per-persona calls → debate → synthesis + size.
- **Destination:** Telegram (shadow portfolio) + Notion (decision journal on action).
- **on_failure:** a persona errors → run the rest, note the absence.
- **Guards:** one house view per name per session; flag when personas disagree (disagreement is signal).
- **Sources (MULTI — A/B/C, the core of this desk):**
  - **A — ai-hedge-fund persona panel:** investor personas (your Cathie / Druckenmiller / Damodaran / Li Wei).
  - **B — TradingAgents bull/bear researcher debate:** structured disagreement before a call.
  - **C — TradingAgents trader + PM:** position/size translation.
  - Output: A's persona calls, B's bull-vs-bear, C's sizing → one synthesised `Recommendation`. Mode: **A & B & C vendored as modules.**

### Desk 5 · Quant Engine
- **Responsibility:** systematic second opinion — factor ranks, optimisation, backtests.
- **Triggers:** scheduled + on demand.
- **Functions operated:** Quant screen · optimise · backtest.
- **Output:** factor ranks + optimiser weights → feed Decision. Template: rank · score · BUY/WATCH/AVOID.
- **Destination:** Telegram (quant screen) + feeds House View.
- **on_failure:** universe fetch fails → run on cached universe, flag staleness.
- **Guards:** cap universe to declared size (98 / 500).
- **Sources:** Microsoft Qlib (library — factor/backtest patterns) + your V3 Quant (native). Single shipped method, not A/B/C.

### Desk 6 · Risk Watch (always-on)
- **Responsibility:** watch exposure and thesis health continuously; flag before it hurts.
- **Triggers:** continuous + on every decision.
- **Functions operated:** Concentration / correlation / drawdown · Regime.
- **Output:** risk `Signal`s. Template: exposure map · cluster flags · regime label.
- **Destination:** Telegram (alerts + Sunday risk section).
- **on_failure:** historical-data gap → flag what couldn't be computed, don't suppress the rest.
- **Guards:** alert dedup; max one regime-change alert per change.
- **Sources:** TradingAgents risk-management team (reference) + ai-hedge-fund risk manager (reference) + your risk engine (native). Multi-source = compare risk-aggregation structures, ship the best.

---

## 3 · STANDARDS & SUPPORT (foundations — Claude owns, Louis reviews later)

### 3.1 · Canonical objects — the shared language (LOAD-BEARING)
Every function and desk reads/writes **these**, never ad-hoc shapes. They are what flows between the Spine and the Desks.

- **Name** — `{ ticker, exchange, asset_class, sector, theme[], currency }`
- **Position** — `{ name_ref, account, shares, avg_cost, current_price, pnl_abs, pnl_pct, weight }`
- **Thesis** — `{ name_ref, summary, drivers[], risks[], verdict(intact|weakening|broken), conviction, last_reviewed, source }`
- **Signal** — `{ type, subject_ref, severity(1-10), summary, created_at, source_desk }`
- **Recommendation** — `{ name_ref, action(buy|add|hold|trim|sell), size, rationale, persona, conviction, price_context, created_at }`
- **Report** — `{ source, title, asset_class, date, extracted_thesis, extracted_risks, names_mentioned[] }`
- **Event** — `{ type(earnings|fomc|conference|threshold), subject_ref, date, details }`

### 3.2 · Multi-source policy (Louis's decision, with one guardrail)
Three integration tiers:
- **Library** — pip-installable, imported in one place behind our interface (OpenBB, Qlib, LlamaIndex).
- **Vendored** — code copied into our repo (license permitting) and **reimplemented as a module that speaks our canonical objects** (TradingAgents agents, ai-hedge-fund personas).
- **Reference** — read-only; we reimplement the good parts ourselves (FinRobot/FinGPT, the TS repos).

**The A/B/C pattern:** opinion desks (House View, Coverage Analyst) surface each source's view **explicitly and labelled** — "Source A says… / Source B says… / Source C says…" — then a synthesis. **Never silently average.** Disagreement between sources is itself a signal.

**Guardrail:** each source is a *module in our code sharing our objects* — we do **not** run multiple external frameworks as separate live processes. Same A/B/C output; one engine, one state model, one bill.

For mechanical desks (Librarian, Quant, Risk aggregation) "multi-source" means *evaluate several implementations and ship the best one*, not present three.

### 3.3 · Sources registry

| Source | Role | Stack | License | Mode | Desks |
|---|---|---|---|---|---|
| **TradingAgents** (TauricResearch) | multi-agent firm: analysts→debate→trader→risk→PM | Python · LangGraph · DeepSeek | Apache-2.0 | **vendored** | Coverage, House View, Risk |
| **ai-hedge-fund** (virattt) | investor-persona agents | Python | check (MIT) | **vendored** | House View, Coverage |
| **OpenBB** | data layer (Bloomberg-lite) | Python | check | **library** | data adapters (Coverage/Idea/Quant) |
| **Qlib** (Microsoft) | factor research + backtest | Python | MIT | **library** | Quant Engine |
| **LlamaIndex** | RAG over reports/transcripts | Python | MIT | **library** | Research Librarian |
| **FinRobot / FinGPT** (AI4Finance) | finance agent + prompt patterns | Python | check | **reference** | Librarian, Coverage |
| HKUDS AI-Trader / Vibe-Trading | agent-native / personal-agent UX | TypeScript | check | **reference only** | future dashboard UX |

> Verify each license before copying code. Apache-2.0 / MIT allow reuse with attribution.

### 3.4 · Communication & Delivery
- Channels: Telegram (primary) · Notion (record) · Dashboard (future).
- Timing: 7am briefing · Sunday digest · market open/close · monthly 复盘.
- Format: verdict-first · plain vs HTML · alert thresholds.

### 3.5 · Systematic Standards (output templates)
- Morning briefing = 5 sections. Deep dive = 9 sections. Every desk output has a fixed template (see each desk).
- Quality bars: cite the object, state a verdict, show the disagreement.

### 3.6 · Knowledge
- Static: persona frameworks, sector playbooks (semis, AI infra, banks, energy), valuation models, regime logic.
- Dynamic: decision-journal learnings, thesis track record, model accuracy (grows over time).

### 3.7 · Operating Discipline (the rules)
- **Dependency direction:** volatile → stable, never reverse. The Spine never imports `yfinance`; it asks through an interface.
- **Failure:** `on_failure` per adapter, `degrade_to` per desk. Declared, not discovered.
- **Extensibility:** every addition = 1 declaration or 1 adapter.
- **Appropriateness:** no microservices, no queue; defer Postgres until SQLite + Notion actually hurt.

### 3.8 · Infrastructure
- Adapters (volatile edge): yfinance, FRED, CoinGecko, Tavily, SEC EDGAR, GitHub, arXiv, DeepSeek — each behind an interface with an `on_failure`.
- Storage: Notion DB · SQLite (research / journal / memory) · Railway volume.
- Runtime: LangGraph ReAct agent on Railway.
- Registry + dispatcher: mandate registry (desks as declarations) + trigger dispatcher.
- Code mapping: `handlers/` (triggers) · `features/` (spine + desks) · `services/` (capabilities) · `adapters/` (edge) · `delivery/` (templates) · `core/` (objects, config, registry, memory).

### 3.9 · Coverage tag (asset class — a label, not a structure)
Equities (deep) · FICC (shallow — learn first) · Commodities (futures) · Crypto (prices only).

---

## 4 · Not in this doc
Build sequencing and per-branch status live in **`BUILD_LOG.md`**. This blueprint says *what the system is*; the log says *where it is*.
