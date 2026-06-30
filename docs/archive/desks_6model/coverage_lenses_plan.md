# Plan · Coverage Analyst — real lenses A & B

> Planning notes for replacing the lens A/B stubs (`src/features/coverage/lenses.py`)
> with real implementations. Companion to `coverage_analyst.md` §6/§7.
> This is a PLAN, not yet a literal work order. Two decisions (below) gate the final specs.
> Status: lenses A & B are interface stubs today; lens C (pillars) is native and built.

---

## 1 · Licence clearance (DONE — both permissive, vendoring allowed)

| Source | Repo | Licence | Verified | Duty when we vendor |
|---|---|---|---|---|
| Lens A — fundamentals | TauricResearch/TradingAgents | **Apache-2.0** | ✅ raw LICENSE checked | Keep a licence copy + attribution; note any changes to vendored logic |
| Lens B — valuation | virattt/ai-hedge-fund | **MIT** © 2024 Virat Singh | ✅ raw LICENSE checked | Keep the MIT copyright + permission notice |

**Attribution mechanics (do once):** create `NOTICE.md` at repo root listing both sources, their licences, and what we cribbed. Add a one-line attribution comment at the top of any module that vendors their logic. Per AGENTS.md rule 6, we **reimplement the logic as a module speaking our canonical objects** — we do NOT pip-install or run their frameworks live.

**Key finding:** Lens B's source is **already in our repo** at `src/agents/aswath_damodaran.py` (this repo is a fork of virattt/ai-hedge-fund). We adapt it in place; no external copying needed for B.

---

## 2 · What each lens actually is (so we reimplement the right thing)

**Lens A — TradingAgents fundamentals analyst.** The logic is in a **PROMPT**, not code. It feeds financial statements (income, balance sheet, cashflow, fundamentals) to an LLM and asks for a comprehensive fundamental read + a BUY/HOLD/SELL. For us: crib the prompt pattern, feed it our `Evidence.fundamentals`, call our LLM adapter, and translate the answer into a `LensView` (per-driver `holding/strained/invalidated` + summary). Maps cleanly to our objects.

**Lens B — Damodaran valuation agent.** The logic is in **CODE**: FCFF DCF → intrinsic value, margin of safety (`(intrinsic − market_cap)/market_cap`), relative valuation, risk profile. Already in `src/agents/aswath_damodaran.py`. For us: extract the math functions, feed them `Evidence.fundamentals`, output **cheap / fair / expensive + implied return** as a `LensView`. An LLM call for the prose summary is optional (the verdict itself is deterministic math).

---

## 3 · The dependency chain (why lenses can't be built in isolation)

Per the inward-dependency rule, a lens (a desk feature) must NOT import a data SDK or the DeepSeek client directly. Both lenses need (a) fundamentals data and (b) — for A — an LLM call. Neither exists behind an adapter yet. So the prerequisite infrastructure must come first:

```
PREREQ 1 · FundamentalsAdapter   (src/adapters/fundamentals.py)
            → returns a plain dict of financial metrics for a ticker
PREREQ 2 · LLMAdapter            (src/adapters/llm.py)
            → wraps src.tools.llm.call_deepseek behind the adapter interface
PREREQ 3 · EvidenceService       (src/services/evidence.py)
            → assembles an Evidence object (fundamentals via PREREQ 1, etc.)
THEN     · Lens B real           (math from src/agents/aswath_damodaran.py → LensView)
THEN     · Lens A real           (vendored prompt + LLMAdapter → LensView)
```

Each is one task, each follows the existing adapter pattern (Tasks 2–4 in WORK_ORDER.md), each declares `on_failure`. No live code (`scheduler.py`, `telegram_bot.py`) is touched.

---

## 4 · DECISIONS NEEDED FROM LOUIS (these gate the final specs)

**Decision 1 — fundamentals data source.** The Damodaran math needs financial metrics (FCFF, shares, market cap, growth, margins). Two options:
- **(a) yfinance** — already a dependency, no new API key. `yf.Ticker(t).info` + `.cashflow`/`.balance_sheet`/`.financials` give most of what's needed. Coverage is decent for US large caps, patchier for ADRs/HK. ← **recommended default** (no new key, already in the stack).
- **(b) financialdatasets.ai** — richer, structured line items (the original agent used this via `src/tools/api.py`), but needs `FINANCIAL_DATASETS_API_KEY` which `.env.example` marks "legacy/not used". Do you have/want this key?

**Decision 2 — does lens A (and B's prose) call the LLM now, or stay math-only first?**
- **(a) Build the LLMAdapter now** and wire lens A to it (full A/B/C as designed). More moving parts, real DeepSeek cost per coverage run. ← **recommended** if you want the real fundamental read.
- **(b) Defer the LLM** — ship lens B as pure math (cheap/fair/expensive, no prose) and keep lens A a stub a while longer. Cheaper, simpler, but A stays unbuilt.

**Decision 3 (from coverage_analyst.md §13, still provisional).** Confirm or change: read `is_core` from the Driver / push only on →broken / no sizing. Current default stands unless you say otherwise.

---

## 5 · Proposed task sequence (becomes a literal WORK_ORDER once decisions land)

1. `NOTICE.md` + attribution comments (licence duty).
2. **FundamentalsAdapter** (`src/adapters/fundamentals.py`) — per Decision 1 source. `on_failure` = return `{}`.
3. **LLMAdapter** (`src/adapters/llm.py`) — wraps `call_deepseek`. `on_failure` = return `""`. (Only if Decision 2 = a.)
4. **EvidenceService** (`src/services/evidence.py`) — `assemble(name) -> Evidence` using the adapters.
5. **Lens B real** — extract DCF + margin-of-safety from `src/agents/aswath_damodaran.py` into `lens_valuation`, reading `Evidence.fundamentals`, returning a `LensView` (cheap/fair/expensive + implied return).
6. **Lens A real** — vendor the TradingAgents fundamentals prompt, feed `Evidence.fundamentals` via LLMAdapter, return a `LensView` with per-driver status.
7. Re-run the Task 8/9 verifications + a new end-to-end on one real held name (e.g. MU) — confirm A/B/C all populate and synthesize produces a verdict.

Note: real **evidence-based** driver evaluation in lens C (vs today's read-saved-status) also belongs here — fold into step 6 or a follow-up.

---

## 6 · NOT in this plan (still needs explicit sign-off)
- Wiring Coverage Analyst triggers into the **live** `scheduler.py` (weekly sweep / earnings / 5% move). Separate task, touches the running bot, needs explicit go-ahead.
- Persisting updated `Thesis` verdicts back to Notion.
