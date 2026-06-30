# WORK_ORDER.md — Active Work Order for AI Agents

> This is an executable work order. It is written for a literal coding agent.
> Execute tasks in order. Do not improvise. Do not reorder. When in doubt, STOP.

---

## SECTION 1 — WHO YOU ARE AND WHAT THIS IS

This repo is a **live** multi-asset Telegram investment bot running 24/7 on Railway; it manages a real portfolio and **must not go down**. You are a coding agent executing this work order. You do **not** make architecture decisions, you do **not** resolve conflicts between files, and you do **not** guess. You write correct code from explicit steps. If any step is unclear, incomplete, missing a detail you need, or conflicts with another file, you **stop immediately and flag it** (see Section 6). Guessing is a failure; stopping to ask is success.

---

## SECTION 2 — READ THESE FILES BEFORE WRITING A SINGLE LINE OF CODE

Read all of these, fully, in this order. Do not skip any. Do not start coding after reading only one.

1. `ONBOARDING.md` — orientation: what the system is and the read order. Your first read.
2. `AGENTS.md` — the canonical working rules every agent follows. The hard rules in Section 3 below come from here.
3. `docs/BLUEPRINT.md` — the architecture: the Spine (functions), the Desks (operators), and Standards & Support (foundations, including the canonical objects in §3.1 and the code mapping in §3.8).
4. `docs/BUILD_LOG.md` — the status tracker and the CURRENT SPRINT. This work order's task list is derived from it. You update this file after every task.
5. `docs/desks/coverage_analyst.md` — the full operations manual for the Coverage Analyst desk (Tasks 6–9 build directly from it). Read it before starting any Coverage task.
6. `docs/desks/_TEMPLATE.md` — the desk spec template, for reference on the shape of a desk.

You have not finished reading until you have opened all six. Only then begin Task 1.

---

## SECTION 3 — THE RULES YOU FOLLOW ON EVERY SINGLE TASK (NO EXCEPTIONS)

1. **Read every file in Section 2 before writing code.** All of them. In order.
2. **One change at a time.** Build exactly one task. Never batch two features or two tasks into one piece of work.
3. **Commit after every successful change.** Commit message format is `type: description` — e.g. `feat: add PriceAdapter to src/adapters/prices.py`. Allowed types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`.
4. **Update `docs/BUILD_LOG.md` in the same commit as the code.** Two edits, every time: (a) update the status emoji for the item you just completed, and (b) add one line to the Decision Log in the format `date · what you did · file(s) touched`. The code change and the BUILD_LOG update go in **one** commit together.
5. **Never import a data SDK inside a Spine function or a desk feature.** No `yfinance`, no `fredapi`, no `requests` to an external API, no `tavily`, no Notion SDK inside `src/features/**`. All external calls go through an adapter in `src/adapters/`. If the adapter you need does not exist yet, the task tells you to create it first — if it does not, STOP and flag.
6. **Every adapter declares `on_failure`. Every desk module declares `degrade_to`.** If you are writing an adapter without an `on_failure` attribute, or a desk module without a documented `degrade_to` behaviour, stop and add it before you finish the task.
7. **If a step is unclear, incomplete, or conflicts with another file — STOP.** Do not guess. Add a `BLOCKED` entry to `docs/BUILD_LOG.md` (format in Section 6) with the exact question, then stop working until a human resolves it.
8. **Do not refactor outside the scope of the current task.** Touch only the files the task names. Do not "clean up" or "improve" anything else.
9. **The bot is live on Railway.** Do **not** edit `src/tools/scheduler.py`, `src/tools/telegram_bot.py`, the `Procfile`, `pyproject.toml`, or any Railway config unless a task explicitly tells you to. None of the tasks in Section 4 do. If you think you need to, STOP and flag.

---

## SECTION 4 — THE TASK LIST

### Folder mapping (READ THIS FIRST — it prevents the most common mistake)

`docs/BLUEPRINT.md` §3.8 lists code folders by bare name (`core/`, `adapters/`, `features/`, `services/`, `delivery/`, `handlers/`). In this repo, **all of these live under the `src/` package**. The importable paths are:

| Blueprint name | Real path in this repo | Import prefix |
|---|---|---|
| `core/` | `src/core/` | `from src.core...` |
| `adapters/` | `src/adapters/` | `from src.adapters...` |
| `features/` | `src/features/` | `from src.features...` |
| `services/` | `src/services/` | `from src.services...` |
| `delivery/` | `src/delivery/` | `from src.delivery...` |

Always create new code under `src/`. Never create a top-level `core/` or `adapters/` folder at the repo root — it will not be importable. When you create a new folder under `src/`, also create an empty `__init__.py` inside it.

All verification commands run with `poetry run python -c "..."` from the repo root.

The task order below follows `docs/BUILD_LOG.md` CURRENT SPRINT, with infrastructure (objects, then adapters) before any desk logic. **Do not reorder.**

---

### TASK 1 — Confirm canonical objects exist (already built; do not rewrite)

**Preconditions:** none.

**Status:** This task is already complete. `src/core/objects.py` exists. Your job is only to confirm it, not to rebuild it.

**Exact steps:**
1. Open `src/core/objects.py`. Confirm it defines these dataclasses: `Name`, `Position`, `Driver`, `Thesis`, `Signal`, `Recommendation`, `Report`, `Event`, and these enums: `AssetClass`, `Verdict`, `DriverStatus`, `Action`, `SignalType`, `EventType`, and the function `to_dict`.
2. Do **not** edit this file. If any of the names above are missing, STOP and flag (the rest of the work order depends on them).

**Output:** no file change.

**Verification:**
```
poetry run python -c "from src.core.objects import Name, Position, Driver, Thesis, Signal, Recommendation, Report, Event, to_dict; print('objects ok')"
```
Must print `objects ok`.

**Build Log update:** none (already logged). If you had to flag, add the BLOCKED entry instead.

---

### TASK 2 — Create the adapter base interface

**Preconditions:** Task 1 verified.

**Exact steps:**
1. Create folder `src/adapters/` with an empty `src/adapters/__init__.py`.
2. Create `src/adapters/base.py`. In it define:
   - An exception class `AdapterError(Exception)`.
   - An abstract base class `Adapter(ABC)` (import `ABC, abstractmethod` from `abc`) with:
     - an instance attribute `on_failure: str` — a plain-English description of what the adapter does when its source fails (e.g. "return empty result; caller degrades"). It MUST be set in `__init__`. If a subclass does not set it, raise `AdapterError` in `__init__`.
     - an `@abstractmethod` method `fetch(self, *args, **kwargs)` that subclasses implement.
3. This file imports only from the Python standard library. No external SDKs.

**Output:** `src/adapters/__init__.py`, `src/adapters/base.py` exist.

**Verification:**
```
poetry run python -c "from src.adapters.base import Adapter, AdapterError; print('adapter base ok')"
```
Must print `adapter base ok`.

**Build Log update:** In PART 3, change the line `🔴 Operating discipline …` toward done as appropriate, and add Decision Log line:
`2026-06-29 · Added adapter base interface (Adapter ABC + AdapterError, on_failure required) · src/adapters/base.py`

---

### TASK 3 — Create the price adapter (wraps existing price code)

**Preconditions:** Task 2 verified.

**Exact steps:**
1. Create `src/adapters/prices.py`.
2. Define `class PriceAdapter(Adapter)`. In `__init__`, set `self.on_failure = "return empty dict; caller treats missing prices as stale and degrades"`.
3. Implement `fetch(self, tickers: list[str]) -> dict`:
   - Inside this method (and ONLY here), import and call the existing function `get_live_prices` from `src.tools.prices`.
   - Wrap the call in `try/except`. On any exception, return `{}` (this is the declared `on_failure` behaviour). Do not re-raise.
   - On success, return the dict that `get_live_prices` returns, unchanged.
4. Do **not** modify `src/tools/prices.py`. You are wrapping it, not changing it.

**Output:** `src/adapters/prices.py` exists.

**Verification:**
```
poetry run python -c "from src.adapters.prices import PriceAdapter; a=PriceAdapter(); print(a.on_failure); print(type(a.fetch(['NVDA'])))"
```
Must print the on_failure string and `<class 'dict'>`.

**Build Log update:** Decision Log line:
`2026-06-29 · Added PriceAdapter wrapping src.tools.prices.get_live_prices behind the adapter interface · src/adapters/prices.py`

---

### TASK 4 — Create the portfolio adapter (produces Position objects)

**Preconditions:** Task 3 verified.

**Exact steps:**
1. Create `src/adapters/portfolio.py`.
2. Define `class PortfolioAdapter(Adapter)`. In `__init__`, set `self.on_failure = "return empty list; caller reports no positions available"`.
3. Implement `fetch(self) -> list[Position]`:
   - Import `Position` from `src.core.objects`.
   - Inside this method only, import and call the existing function `get_holdings_cached` from `src.tools.notion_holdings`.
   - Wrap in `try/except`. On any exception, return `[]` (declared `on_failure`).
   - On success, `get_holdings_cached()` returns a dict keyed by ticker. Each value dict `d` has exactly these keys: `account`, `avg_cost`, `name`, `rating`, `role`, `sector`, `shares`, `thesis`. There is NO `current_price` key — do not read one. For each ticker `t` and its data dict `d`, build a `Position` with: `name_ref=t`, `account=d.get("account","default")`, `shares=d.get("shares",0)`, `avg_cost=d.get("avg_cost",0)`. Leave `current_price`, `pnl_abs`, `pnl_pct`, `weight` at their defaults (0.0) — live price is supplied separately by `PriceAdapter`, not by this adapter. Only include tickers where `shares` is greater than 0 (held positions, not watchlist).
   - Return the list of `Position` objects.
4. Do **not** modify `src/tools/notion_holdings.py`.

**Output:** `src/adapters/portfolio.py` exists.

**Verification:**
```
poetry run python -c "from src.adapters.portfolio import PortfolioAdapter; ps=PortfolioAdapter().fetch(); print(len(ps), 'positions'); print(ps[0] if ps else 'none')"
```
Must print a count and a `Position(...)` (or `none` if Notion returns nothing — that is acceptable, it means the adapter ran).

**Build Log update:** In PART 1 Monitoring, leave statuses as-is. Decision Log line:
`2026-06-29 · Added PortfolioAdapter producing Position objects from get_holdings_cached (held only, shares>0) · src/adapters/portfolio.py`

---

### TASK 5 — Morning briefing reference implementation (CURRENT SPRINT item 2)

**Preconditions:** Tasks 3 and 4 verified.

**Scope limit (read carefully):** Build this as a **standalone module**. Do **not** import, modify, or wire into `src/tools/scheduler.py` or `src/tools/telegram_bot.py`. Wiring the new briefing into the live schedule is OUT OF SCOPE for this task and requires a separate explicit instruction. This task only proves the spine-and-objects version can produce a briefing string.

**Exact steps:**
1. Create folder `src/features/` with empty `src/features/__init__.py` (if it does not already exist).
2. Create `src/features/morning_briefing.py`.
3. Define `def build_morning_briefing() -> str`:
   - Use `PortfolioAdapter` (from `src.adapters.portfolio`) to get `positions: list[Position]`.
   - Collect the tickers: `tickers = [p.name_ref for p in positions]`.
   - Use `PriceAdapter` (from `src.adapters.prices`) to fetch `prices = PriceAdapter().fetch(tickers)`. The returned shape is `{ticker: {"price": float, "change_pct": float}}`. IMPORTANT: a ticker that failed to fetch is PRESENT in the dict but maps to an empty dict `{}` — it is not absent. Access it as `prices.get(p.name_ref, {}).get("price")` which yields `None` for a failed ticker.
   - For each position `p`, compute:
     - `price = prices.get(p.name_ref, {}).get("price")` (may be `None`).
     - if `price` is falsy (None or 0): the line is `f"{p.name_ref}: data pending"`, and use a sort key of `-9999` for it.
     - else: `pnl_pct = round((price - p.avg_cost) / p.avg_cost * 100, 1) if p.avg_cost else 0.0`, the line is `f"{p.name_ref}: ${price} ({pnl_pct}% vs cost)"`, and the sort key is `pnl_pct`.
   - Build the output string: header line `f"Morning Briefing — {date.today().isoformat()}"` (import `date` from `datetime`), then the position lines sorted by sort key **descending**, one per line, joined with `"\n"`.
   - `degrade_to`: if `PortfolioAdapter().fetch()` returns `[]`, return exactly `"Morning Briefing — no positions available (data pending)"`. Document this `degrade_to` behaviour in the module docstring.
   - Do not call any data SDK directly — only the two adapters.
4. Do not send anything to Telegram. This task returns a string only.

**Output:** `src/features/__init__.py`, `src/features/morning_briefing.py` exist.

**Verification:**
```
poetry run python -c "from src.features.morning_briefing import build_morning_briefing; print(build_morning_briefing()[:200])"
```
Must print a briefing string starting with `Morning Briefing —`.

**Build Log update:** In CURRENT SPRINT, change item 2 from `🔁` to `🟡` (reference implementation built, not yet wired live) and append `→ src/features/morning_briefing.py (standalone; not wired to live scheduler)`. Decision Log line:
`2026-06-29 · Built spine+objects morning briefing as standalone reference (PortfolioAdapter + PriceAdapter → Position objects → string); not wired to live scheduler · src/features/morning_briefing.py`

---

### TASK 6 — Coverage Analyst: desk-local types (CURRENT SPRINT item 3, part 1)

**Preconditions:** Task 1 verified. You have read `docs/desks/coverage_analyst.md` in full.

**Decision already made for you (do not change):** The types `Evidence`, `LensView`, and `CoverageResult` referenced in `coverage_analyst.md` §10 are **desk-local types**, not canonical §3.1 objects. Define them in the Coverage desk folder, **not** in `src/core/objects.py`. Do not add them to the canonical objects file.

**Exact steps:**
1. Create folder `src/features/coverage/` with empty `src/features/coverage/__init__.py`.
2. Create `src/features/coverage/types.py`. Import canonical objects from `src.core.objects`. Define three dataclasses:
   - `Evidence`: fields `name_ref: str`, `prices: dict` (default empty), `news: list` (default empty), `fundamentals: dict` (default empty), `transcript: str` (default ""), `filings: list` (default empty). This is the bundle a service assembles for one name.
   - `LensView`: fields `source: str` (one of "fundamentals", "valuation", "pillars"), `per_driver: dict` (maps driver id → `DriverStatus`), `summary: str`, `signal: Signal | None` (default None).
   - `CoverageResult`: fields `updated_thesis: Thesis`, `recommendation: Recommendation | None` (default None), `pushed: bool` (default False).
3. Use `from __future__ import annotations` and `dataclasses`. No external SDK imports.

**Output:** `src/features/coverage/__init__.py`, `src/features/coverage/types.py` exist.

**Verification:**
```
poetry run python -c "from src.features.coverage.types import Evidence, LensView, CoverageResult; print('coverage types ok')"
```
Must print `coverage types ok`.

**Build Log update:** Decision Log line:
`2026-06-29 · Added Coverage Analyst desk-local types (Evidence, LensView, CoverageResult); kept out of core/objects.py per spec §10 · src/features/coverage/types.py`

---

### TASK 7 — Coverage Analyst: the three lens modules (CURRENT SPRINT item 3, part 2)

**Preconditions:** Task 6 verified.

**Decision already made for you (do not change):** Lens **C (pillars)** is built fully now. Lenses **A (fundamentals)** and **B (valuation)** require vendoring code from external repos (TradingAgents, ai-hedge-fund) whose licences are listed as "to verify" in `BLUEPRINT.md` §3.3. **You may not vendor external code in this task.** Build A and B as interface-correct stubs that return a valid `LensView` with `summary="not yet vendored — pending licence verification"` and an empty `per_driver`. Vendoring A and B is a separate task that requires explicit instruction. If you are tempted to copy external code, STOP and flag.

**Exact steps:**
1. Create `src/features/coverage/lenses.py`. Import `Name`, `Thesis`, `DriverStatus` from `src.core.objects` and `Evidence`, `LensView` from `src.features.coverage.types`.
2. Define `def lens_pillars(name: Name, thesis: Thesis, evidence: Evidence) -> LensView` (lens C, native):
   - For each `driver` in `thesis.drivers`, decide its status: this first version maps each driver to its **existing** `driver.status` (read it straight from the saved Thesis — do not infer new statuses yet; real evidence-evaluation logic is a later task). Build `per_driver = {driver.id: driver.status for driver in thesis.drivers}`.
   - Return `LensView(source="pillars", per_driver=per_driver, summary="pillar status read from saved thesis", signal=None)`.
3. Define `def lens_fundamentals(name, thesis, evidence) -> LensView` (lens A, stub): return `LensView(source="fundamentals", per_driver={}, summary="not yet vendored — pending licence verification", signal=None)`.
4. Define `def lens_valuation(name, thesis, evidence) -> LensView` (lens B, stub): return `LensView(source="valuation", per_driver={}, summary="not yet vendored — pending licence verification", signal=None)`.
5. No external SDK imports. No copying of external repo code.

**Output:** `src/features/coverage/lenses.py` exists.

**Verification:**
```
poetry run python -c "from src.features.coverage.lenses import lens_pillars, lens_fundamentals, lens_valuation; print('lenses ok')"
```
Must print `lenses ok`.

**Build Log update:** In PART 2 desks table, Coverage Analyst "Sources vendored" stays `🔴` (A and B are stubs, not vendored). Decision Log line:
`2026-06-29 · Added Coverage lenses: C/pillars native (reads driver.status); A/fundamentals and B/valuation interface stubs (vendoring deferred pending licence check) · src/features/coverage/lenses.py`

---

### TASK 8 — Coverage Analyst: synthesize() verdict state machine (CURRENT SPRINT item 3, part 3)

**Preconditions:** Task 7 verified. You have re-read `coverage_analyst.md` §5 and §7.

**Decisions already made for you (do not change), tied to spec §13 open questions — implement EXACTLY as written:**
- Core vs non-core (spec Q1): read `driver.is_core` straight from the `Driver` object. Do **not** infer it.
- Push threshold (spec Q2): set `pushed=True` only when the new verdict is `BROKEN` and the previous verdict was not `BROKEN`. For a degrade to `WEAKENING`, set `pushed=False` (it will be batched into the Sunday sweep by a later task).
- Trim vs sell (spec Q3): the `Recommendation` carries `action` and `rationale` only; set `size=""` (no sizing — that is House View's job, wired later).

**Exact steps:**
1. Create `src/features/coverage/synthesize.py`. Import `Thesis`, `Verdict`, `DriverStatus`, `Recommendation`, `Action` from `src.core.objects` and `LensView`, `CoverageResult` from `src.features.coverage.types`.
2. Define `def synthesize(views: list[LensView], thesis: Thesis) -> CoverageResult`:
   - Find the pillars view (the `LensView` with `source == "pillars"`). Use its `per_driver` as the authoritative driver statuses. If absent, STOP is not needed — instead treat all drivers as their saved status.
   - Update each `driver.status` in a copy of the thesis from `per_driver` where present.
   - Compute the new verdict by this exact rule (from §5):
     - `BROKEN` if any driver with `is_core == True` has status `INVALIDATED`.
     - else `WEAKENING` if any driver has status `STRAINED` (and none core-invalidated).
     - else `INTACT`.
   - Record `prev = thesis.verdict`; set the updated thesis's `verdict` to the new verdict and set `last_reviewed` to `datetime.now()`.
   - Determine `pushed` per the Q2 rule above.
   - If the new verdict is worse than `prev` (order: INTACT < WEAKENING < BROKEN) build a `Recommendation`: `name_ref=thesis.name_ref`, `action=Action.SELL` if new verdict is `BROKEN` else `Action.TRIM`, `size=""`, `rationale` = a one-line string naming the first failing driver. Otherwise `recommendation=None`.
   - Return `CoverageResult(updated_thesis=<updated copy>, recommendation=<rec or None>, pushed=<bool>)`.
3. Do not mutate the input `thesis` in place — work on a copy (`copy.deepcopy`).

**Output:** `src/features/coverage/synthesize.py` exists.

**Verification:**
```
poetry run python -c "
from src.core.objects import Thesis, Driver, DriverStatus, Verdict
from src.features.coverage.lenses import lens_pillars, lens_fundamentals, lens_valuation
from src.features.coverage.types import Evidence
from src.features.coverage.synthesize import synthesize
th = Thesis(name_ref='MU', drivers=[Driver(id='d1', summary='DRAM', is_core=True, status=DriverStatus.INVALIDATED)], verdict=Verdict.INTACT)
ev = Evidence(name_ref='MU')
views = [lens_pillars(None, th, ev), lens_fundamentals(None, th, ev), lens_valuation(None, th, ev)]
r = synthesize(views, th)
print(r.updated_thesis.verdict, r.pushed, r.recommendation.action if r.recommendation else None)
"
```
Must print `Verdict.BROKEN True Action.SELL`.

**Build Log update:** In PART 1 Monitoring, change `🔴 Thesis-health watch` to `🟡 Thesis-health watch — verdict state machine built, triggers not wired`. Decision Log line:
`2026-06-29 · Built Coverage synthesize() verdict state machine (§5/§7): core-invalidated→broken, strained→weakening; push only on →broken; rec carries action+rationale, no sizing · src/features/coverage/synthesize.py`

---

### TASK 9 — Coverage Analyst: run_coverage() orchestrator (CURRENT SPRINT item 3, part 4)

**Preconditions:** Task 8 verified.

**Scope limit:** Do **not** wire this to any trigger, schedule, or `scheduler.py`. Trigger wiring is a separate task that touches live code and needs explicit instruction. This task builds the callable orchestrator only.

**Exact steps:**
1. Create `src/features/coverage/desk.py`. Import `Name`, `Thesis` from `src.core.objects`, `Evidence`, `CoverageResult` from `src.features.coverage.types`, the three lens functions from `src.features.coverage.lenses`, and `synthesize` from `src.features.coverage.synthesize`.
2. Define `def run_coverage(name: Name, thesis: Thesis, evidence: Evidence) -> CoverageResult`:
   - Call the three lenses with `(name, thesis, evidence)`, collect into a `views` list.
   - Call `synthesize(views, thesis)` and return its `CoverageResult`.
   - `degrade_to`: document in the module docstring — if the LLM/evidence layer is unavailable, the desk still runs lens C on the saved thesis and returns a `CoverageResult` (verdict unchanged, `pushed=False`), so the gap is visible rather than silent. (No LLM call exists yet, so this version always runs cleanly.)
3. No external SDK imports.

**Output:** `src/features/coverage/desk.py` exists.

**Verification:**
```
poetry run python -c "
from src.core.objects import Name, Thesis, Driver, DriverStatus, Verdict
from src.features.coverage.types import Evidence
from src.features.coverage.desk import run_coverage
n = Name(ticker='MU')
th = Thesis(name_ref='MU', drivers=[Driver(id='d1', summary='DRAM', is_core=True, status=DriverStatus.STRAINED)], verdict=Verdict.INTACT)
r = run_coverage(n, th, Evidence(name_ref='MU'))
print('verdict', r.updated_thesis.verdict, 'pushed', r.pushed)
"
```
Must print `verdict Verdict.WEAKENING pushed False`.

**Build Log update:** In PART 2 desks table, Coverage Analyst "Migrated to model" → `🟡` (orchestrator built, triggers/lenses-vendoring pending). Decision Log line:
`2026-06-29 · Built run_coverage() orchestrator wiring 3 lenses → synthesize → CoverageResult; degrade_to documented; not wired to triggers · src/features/coverage/desk.py`

---

### TASK 10 — Migrate remaining tools onto desks (CURRENT SPRINT item 4) — NOT EXECUTABLE YET

**Do not start this task.** It is a placeholder. Migrating each existing tool (`src/tools/*.py`) onto the desk model touches live code and must be done one tool at a time, each with its own work order specifying exactly which tool, which desk, and which adapter. Stop here and request the next work order. If you reached this task, all executable work in this order is done.

---

### TASK 11 — Retire old docs (CURRENT SPRINT item 5) — NOT EXECUTABLE YET

**Do not start this task.** Deleting or retiring docs requires explicit instruction and may only happen after all migration is complete. Do not delete any file. Stop.

---

## SECTION 5 — WHAT YOU MUST NEVER DO

- **Never** create architecture, folders, layers, or patterns not described in `docs/BLUEPRINT.md`.
- **Never** rename, restructure, or re-field any canonical object in `src/core/objects.py`.
- **Never** add a new external dependency (a new `poetry add`, a new import of a third-party package) without STOPPING and flagging it first.
- **Never** vendor/copy code from an external repo without explicit instruction and a verified licence.
- **Never** delete or move a file without an explicit instruction to do so.
- **Never** merge two tasks into one commit. One task, one commit.
- **Never** skip the `docs/BUILD_LOG.md` update. Code without a Build Log update in the same commit is a broken commit.
- **Never** edit `src/tools/scheduler.py`, `src/tools/telegram_bot.py`, `Procfile`, or `pyproject.toml` unless a task explicitly says to (none here do).
- **Never** guess when unclear. Stop and flag.

---

## SECTION 6 — IF YOU ARE STUCK

The moment something is unclear, incomplete, or conflicts with another file, do exactly this and nothing more:

1. Open `docs/BUILD_LOG.md`.
2. Add a new section at the top of the file titled `## BLOCKED` (create it if it does not exist).
3. Under it, add an entry with exactly these three things:
   - **(a) Task number** you were on.
   - **(b) The exact question** — phrased so a human can answer yes/no or with one decision.
   - **(c) The specific conflict or gap** — name the two files (and sections) that disagree, or the exact piece of information that is missing.
4. Commit that change alone with message `docs: flag blocker on task <N>`.
5. **Stop working.** Do not attempt a workaround. Do not proceed to the next task. Wait for a human to resolve the blocker.

A blocker raised is the correct outcome. A wrong guess is not.
