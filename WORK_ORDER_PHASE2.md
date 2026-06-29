# WORK_ORDER_PHASE2.md — Coverage Analyst real lenses (A + B)

> Executable work order for a literal coding agent. Same rules as `WORK_ORDER.md`.
> Phase 1 (Tasks 1–9 in WORK_ORDER.md) is complete. This phase replaces the lens
> A/B stubs with real implementations, plus the adapters/service they need.
> Plan + licence clearance: `docs/desks/coverage_lenses_plan.md`. Read it first.

---

## DECISIONS ALREADY MADE (do not change — Louis confirmed these)

- **Data source = yfinance** (no API key needed). The FundamentalsAdapter reads `yfinance` `.info`. financialdatasets.ai is a future drop-in upgrade and is OUT OF SCOPE here.
- **LLM is on** — build the LLMAdapter and wire lens A to it. DeepSeek cost per run is accepted.
- **§13 defaults stand** — read `is_core` from the `Driver`; push only on →broken; recommendation carries action+rationale, no sizing. Do not revisit.

---

## RULES (identical to WORK_ORDER.md Section 3 — re-read it if unsure)

Read all docs first (ONBOARDING → AGENTS → BLUEPRINT → BUILD_LOG → coverage_analyst.md → coverage_lenses_plan.md → this file). One task at a time. Commit after each with `type: description`. Update `docs/BUILD_LOG.md` (status + Decision Log line) in the SAME commit. Adapters declare `on_failure`; desk modules declare `degrade_to`. If anything is unclear or conflicts — STOP and write a BLOCKED entry (WORK_ORDER.md Section 6). Never touch `src/tools/scheduler.py`, `src/tools/telegram_bot.py`, `Procfile`, `pyproject.toml`. New code goes under `src/`; add `__init__.py` to new folders. Run each task's Verification before committing.

**Adapter note:** adapters ARE the volatile edge — they MAY import `yfinance` and the DeepSeek caller directly. The inward-dependency rule forbids that only in `src/features/**` (desks/spine). Lenses get data via the `Evidence` object and the LLM via the LLMAdapter — never by importing an SDK themselves.

---

## TASK P1 — Attribution (NOTICE.md)

**Preconditions:** none.

**Exact steps:**
1. Create `NOTICE.md` at the repo root with exactly these sections:
   - A line: `This project vendors and adapts logic from the following open-source projects:`
   - `TradingAgents (TauricResearch) — Apache License 2.0 — https://github.com/TauricResearch/TradingAgents — adapted: fundamentals-analyst prompt pattern, reimplemented in src/features/coverage/lenses.py (lens A).`
   - `ai-hedge-fund (virattt) — MIT License, Copyright (c) 2024 Virat Singh — this repo is a fork; the Aswath Damodaran valuation logic in src/agents/aswath_damodaran.py is adapted into src/features/coverage/lenses.py (lens B).`

**Output:** `NOTICE.md` exists.

**Verification:** `test -f NOTICE.md && echo "notice ok"` prints `notice ok`.

**Build Log update:** Decision Log line:
`2026-06-29 · Added NOTICE.md attributing TradingAgents (Apache-2.0) and ai-hedge-fund (MIT) per vendoring duty · NOTICE.md`

---

## TASK P2 — FundamentalsAdapter (yfinance)

**Preconditions:** Task P1 done. `src/adapters/base.py` exists (Phase 1).

**Exact steps:**
1. Create `src/adapters/fundamentals.py`.
2. Define `class FundamentalsAdapter(Adapter)`. In `__init__` set `self.on_failure = "return empty dict; valuation lens degrades to 'data partial'"`.
3. Implement `fetch(self, ticker: str) -> dict`:
   - Inside the method, `import yfinance as yf`. Wrap everything in `try/except`; on any exception return `{}`.
   - `info = yf.Ticker(ticker).info`.
   - Return a normalised dict with EXACTLY these keys, each via `info.get(...)` (value may be `None`):
     - `"free_cash_flow": info.get("freeCashflow")`
     - `"shares_outstanding": info.get("sharesOutstanding")`
     - `"market_cap": info.get("marketCap")`
     - `"beta": info.get("beta")`
     - `"revenue": info.get("totalRevenue")`
     - `"revenue_growth": info.get("revenueGrowth")`
     - `"trailing_pe": info.get("trailingPE")`
     - `"forward_pe": info.get("forwardPE")`
     - `"profit_margins": info.get("profitMargins")`
     - `"current_price": info.get("currentPrice")`
     - `"fifty_two_week_high": info.get("fiftyTwoWeekHigh")`

**Output:** `src/adapters/fundamentals.py` exists.

**Verification (needs network):**
```
poetry run python -c "from src.adapters.fundamentals import FundamentalsAdapter; d=FundamentalsAdapter().fetch('NVDA'); print(type(d), sorted(d.keys()) if d else 'empty')"
```
Must print `<class 'dict'>` and either the 11 keys or `empty` (empty is an acceptable degrade if the network/source is down — the adapter still ran).

**Build Log update:** Decision Log line:
`2026-06-29 · Added FundamentalsAdapter (yfinance .info → 11-key normalised dict); on_failure returns {} · src/adapters/fundamentals.py`

---

## TASK P3 — LLMAdapter (wraps DeepSeek)

**Preconditions:** Task P2 done.

**Exact steps:**
1. Create `src/adapters/llm.py`.
2. Define `class LLMAdapter(Adapter)`. In `__init__` set `self.on_failure = "return empty string; calling lens degrades to 'lens unavailable'"`.
3. Implement `fetch(self, prompt: str, system: str = "", max_tokens: int = 600, temperature: float = 0.3) -> str`:
   - Inside the method, `from src.tools.llm import call_deepseek`.
   - Call `call_deepseek(prompt, system=system, max_tokens=max_tokens, temperature=temperature)`.
   - `call_deepseek` returns a string that starts with `❌` on failure. If the result is falsy OR starts with `❌`, return `""` (declared `on_failure`). Otherwise return the result.

**Output:** `src/adapters/llm.py` exists.

**Verification (needs DEEPSEEK_API_KEY):**
```
poetry run python -c "from src.adapters.llm import LLMAdapter; r=LLMAdapter().fetch('Reply with the single word: ok'); print('nonempty' if r else 'empty')"
```
Must print `nonempty` (or `empty` if the key/network is unavailable — the adapter still ran without raising).

**Build Log update:** Decision Log line:
`2026-06-29 · Added LLMAdapter wrapping call_deepseek; on_failure (falsy or ❌) returns "" · src/adapters/llm.py`

---

## TASK P4 — EvidenceService (assembles Evidence)

**Preconditions:** Task P2 done. `src/features/coverage/types.py` exists (Phase 1).

**Exact steps:**
1. Create folder `src/services/` with empty `src/services/__init__.py`.
2. Create `src/services/evidence.py`.
3. Define `def assemble(name_ref: str) -> Evidence`:
   - Import `Evidence` from `src.features.coverage.types` and `FundamentalsAdapter` from `src.adapters.fundamentals`.
   - `fundamentals = FundamentalsAdapter().fetch(name_ref)`.
   - Return `Evidence(name_ref=name_ref, fundamentals=fundamentals)`. Leave `prices`, `news`, `transcript`, `filings` at their defaults (assembling those is a future task).
4. This service is allowed to import the adapter (it is a service, not a lens). It must NOT import yfinance directly.

**Output:** `src/services/__init__.py`, `src/services/evidence.py` exist.

**Verification:**
```
poetry run python -c "from src.services.evidence import assemble; e=assemble('NVDA'); print(e.name_ref, type(e.fundamentals))"
```
Must print `NVDA <class 'dict'>`.

**Build Log update:** Decision Log line:
`2026-06-29 · Added EvidenceService.assemble(name_ref) → Evidence with fundamentals via FundamentalsAdapter · src/services/evidence.py`

---

## TASK P5 — Lens B real (Damodaran valuation → cheap/fair/expensive)

**Preconditions:** Tasks P2 and P4 done. You have read `src/agents/aswath_damodaran.py` (the source being adapted) and `coverage_analyst.md` §6 (lens B) and §7.

**What lens B outputs:** a `LensView` whose `summary` states `cheap` / `fair` / `expensive` plus the implied margin of safety. Lens B does NOT set per-driver status (that is lens C's job); its `per_driver` stays empty. Its job is the action-nuance input described in §7.

**Exact steps:**
1. Open `src/features/coverage/lenses.py`. Replace the `lens_valuation` stub body (keep the same signature `lens_valuation(name, thesis, evidence) -> LensView`).
2. Add a one-line attribution comment above the function: `# Lens B: adapted from src/agents/aswath_damodaran.py (ai-hedge-fund, MIT). See NOTICE.md.`
3. Read fundamentals from `evidence.fundamentals` (a dict; values may be `None`). Pull: `fcff = f.get("free_cash_flow")`, `shares = f.get("shares_outstanding")`, `mcap = f.get("market_cap")`, `beta = f.get("beta")`, `growth = f.get("revenue_growth")`, `fwd_pe = f.get("forward_pe")`.
4. **Degrade path:** if `fcff` is falsy OR `shares` is falsy OR `mcap` is falsy: skip the DCF and use a P/E fallback — if `fwd_pe` is a number and `fwd_pe < 15` → verdict `"cheap"`; `fwd_pe > 30` → `"expensive"`; otherwise `"fair"`. If `fwd_pe` is also missing → verdict `"fair"`, summary `"valuation: data partial — no DCF, no P/E"`. Build the LensView and return (see step 7).
5. **DCF path (port of the source math):**
   - `cost_of_equity = 0.045 + (beta * 0.05)` if `beta` is a number, else `0.09`.
   - `base_growth = min(growth, 0.12)` if `growth` is a number and `growth > 0`, else `0.04`.
   - `terminal_growth = 0.025`; `years = 10`; `g = base_growth`; `g_step = (terminal_growth - base_growth) / (years - 1)`.
   - `pv_sum = 0.0`; loop `yr` from 1..years: `fcff_t = fcff * (1 + g)`; `pv = fcff_t / (1 + cost_of_equity) ** yr`; `pv_sum += pv`; `g += g_step`.
   - `tv = fcff * (1 + terminal_growth) / (cost_of_equity - terminal_growth) / (1 + cost_of_equity) ** years`.
   - `equity_value = pv_sum + tv`.
   - `margin_of_safety = (equity_value - mcap) / mcap`.
   - verdict: `>= 0.25` → `"cheap"`; `<= -0.25` → `"expensive"`; else `"fair"`.
6. Build `summary = f"valuation: {verdict} (margin of safety {round(margin_of_safety*100)}%)"` for the DCF path, or the P/E-fallback summary for the degrade path.
7. Return `LensView(source="valuation", per_driver={}, summary=summary, signal=None)`.

**Output:** `src/features/coverage/lenses.py` updated (lens_valuation real; lens_pillars and lens_fundamentals unchanged for now).

**Verification:**
```
poetry run python -c "
from src.core.objects import Name, Thesis
from src.features.coverage.lenses import lens_valuation
from src.features.coverage.types import Evidence
# DCF path with synthetic data
ev = Evidence(name_ref='X', fundamentals={'free_cash_flow':1e9,'shares_outstanding':1e8,'market_cap':5e9,'beta':1.1,'revenue_growth':0.2})
v = lens_valuation(Name(ticker='X'), Thesis(name_ref='X'), ev)
print(v.source, '|', v.summary)
"
```
Must print `valuation | valuation: <cheap|fair|expensive> (margin of safety <n>%)`.

**Build Log update:** In PART 2 desks table, Coverage Analyst "Sources vendored" → `🟡` (B done, A pending). Decision Log line:
`2026-06-29 · Lens B real: ported Damodaran FCFF DCF + margin-of-safety from src/agents/aswath_damodaran.py to read Evidence.fundamentals; cheap/fair/expensive with P/E degrade path · src/features/coverage/lenses.py`

---

## TASK P6 — Lens A real (TradingAgents fundamentals prompt → per-driver status)

**Preconditions:** Tasks P3, P4, P5 done. You have read `coverage_analyst.md` §6 (lens A) and the lens-A notes in `coverage_lenses_plan.md` §2.

**What lens A outputs:** a `LensView` with `per_driver` mapping each thesis driver id to a `DriverStatus` (HOLDING / STRAINED / INVALIDATED), judged from fundamentals, plus a one-line `summary`.

**Exact steps:**
1. Open `src/features/coverage/lenses.py`. Replace the `lens_fundamentals` stub body (keep signature `lens_fundamentals(name, thesis, evidence) -> LensView`).
2. Add attribution comment: `# Lens A: fundamentals-analyst prompt pattern adapted from TradingAgents (Apache-2.0). See NOTICE.md.`
3. Import `DriverStatus` from `src.core.objects`, `LensView` from `src.features.coverage.types`, `LLMAdapter` from `src.adapters.llm`, and `json`.
4. Build the prompt string:
   - List the thesis drivers as `f"{d.id}: {d.summary}"`, one per line.
   - Include `evidence.fundamentals` (the dict) rendered as text.
   - Instruction (crib of the TradingAgents pattern): `"You are a fundamentals analyst. Given the saved thesis drivers and the latest fundamentals, classify EACH driver as one of: holding, strained, invalidated — based only on what the fundamentals support. Reply ONLY with a JSON object mapping each driver id to its status, plus a key \"summary\" with one sentence. Example: {\"d1\": \"holding\", \"summary\": \"margins stable\"}."`
5. Call `raw = LLMAdapter().fetch(prompt, system="You output only valid JSON.")`.
6. **Degrade path:** if `raw` is empty (LLM adapter failed): return `LensView(source="fundamentals", per_driver={}, summary="fundamentals lens unavailable (LLM error)", signal=None)`.
7. Parse: `try: data = json.loads(raw)` — if it raises, return a LensView with empty `per_driver` and `summary="fundamentals lens: unparseable response"`.
8. Build `per_driver`: for each driver in `thesis.drivers`, if `data.get(driver.id)` is one of `"holding"/"strained"/"invalidated"`, map it to the matching `DriverStatus`; skip ids not present. `summary = data.get("summary", "")`.
9. Return `LensView(source="fundamentals", per_driver=per_driver, summary=summary, signal=None)`.

**Output:** `src/features/coverage/lenses.py` updated (lens_fundamentals real).

**Verification (needs DEEPSEEK_API_KEY + network):**
```
poetry run python -c "
from src.core.objects import Name, Thesis, Driver, DriverStatus
from src.features.coverage.lenses import lens_fundamentals
from src.features.coverage.types import Evidence
th = Thesis(name_ref='MU', drivers=[Driver(id='d1', summary='DRAM pricing recovery')])
ev = Evidence(name_ref='MU', fundamentals={'revenue_growth':0.3,'profit_margins':0.2})
v = lens_fundamentals(Name(ticker='MU'), th, ev)
print(v.source, '| per_driver keys:', list(v.per_driver.keys()), '| summary nonempty:', bool(v.summary))
"
```
Must print `fundamentals | per_driver keys: [...] | summary nonempty: True` (or the documented degrade line if the LLM is unavailable — that still proves the code path ran without raising).

**Build Log update:** In PART 2, Coverage Analyst "Sources vendored" → `✅`. In PART 1 Monitoring, `Thesis-health watch` note → add "lenses A/B real". Decision Log line:
`2026-06-29 · Lens A real: TradingAgents fundamentals prompt pattern via LLMAdapter → per-driver holding/strained/invalidated JSON; degrade paths for LLM error + unparseable · src/features/coverage/lenses.py`

---

## TASK P7 — End-to-end check on a real held name

**Preconditions:** Tasks P5 and P6 done.

**Exact steps:**
1. Do not create new files. This task only runs the verification and logs the result.
2. Run the command below. It assembles real evidence for MU, runs all three lenses through `run_coverage`, and prints the verdict and which lenses populated.

**Verification (needs network + DEEPSEEK_API_KEY):**
```
poetry run python -c "
from src.core.objects import Name, Thesis, Driver, DriverStatus, Verdict
from src.services.evidence import assemble
from src.features.coverage.desk import run_coverage
ev = assemble('MU')
th = Thesis(name_ref='MU', drivers=[Driver(id='d1', summary='DRAM pricing recovery', is_core=True, status=DriverStatus.HOLDING)], verdict=Verdict.INTACT)
r = run_coverage(Name(ticker='MU'), th, ev)
print('verdict', r.updated_thesis.verdict, '| pushed', r.pushed, '| rec', r.recommendation.action if r.recommendation else None)
"
```
Must print a line beginning `verdict Verdict.` without raising. (The exact verdict depends on live data — any of intact/weakening/broken is a valid PASS as long as it runs end-to-end.)

**Build Log update:** In PART 2, Coverage Analyst "Migrated to model" → `✅`. Decision Log line:
`2026-06-29 · End-to-end Coverage run on MU with real evidence (FundamentalsAdapter → EvidenceService → 3 lenses → synthesize); runs clean · verification only`

---

## STOP HERE

When P7 passes, all lenses are real and the Coverage Analyst runs end-to-end on demand. **Do not** wire triggers into `scheduler.py` or write verdicts to Notion — those are separate work orders requiring Louis's explicit go-ahead (see `coverage_lenses_plan.md` §6). Report completion and stop.
