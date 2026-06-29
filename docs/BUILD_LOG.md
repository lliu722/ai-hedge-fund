# 工作日志 · AI Investment System — Build Log (Status Tracker)

> Companion to **`BLUEPRINT.md` (图纸)**. The blueprint says *what the system is*; this log says *where each piece is*.
> **Rule:** after every change, update the matching line here (status + location), and add a line to the Decision Log.
> Status key: ✅ done · 🟡 partial · 🔴 not built · ⏸ parked · 🔁 needs migration onto new model
> Last updated: 2026-06-29

---

## CURRENT SPRINT — migration to the new model (strangler; bot stays live)

1. ✅ Write canonical objects (§3.1) as code — the shared language. → `src/core/objects.py`
2. 🟡 Rebuild the **morning briefing** on spine + objects as the reference implementation. → `src/features/morning_briefing.py` (standalone; not wired to live scheduler)
3. 🔴 Spec + build **Coverage Analyst** (richest desk; closes the thesis-health / sell-discipline gap). Vendor TradingAgents fundamentals analyst + ai-hedge-fund Damodaran agent as modules.
4. 🔁 Migrate remaining tools onto the desks one at a time; commit after each.
5. 🔴 Retire the four old docs once everything is migrated; this pair becomes the only source of truth.

> Next action right now: **Coverage Analyst spec** (six fields + A/B/C sources), then objects.

---

## PART 1 · THE SPINE — function status

### Intelligence
- ✅ Macro & geo scan — geopolitical pulse, morning briefing
- ✅ News filter — Tavily + DeepSeek score, breaking ≥8/10 (2hr)
- ✅ Sector / theme monitor — theme radar (55 ETF), sector rotation
- 🟡 FICC / commodities / crypto feeds — built but shallow (FRED data, futures, CoinGecko prices)

### Research
- ✅ Deep dive (9-section)
- ✅ Valuation — P/E, EV/EBITDA, peers · 🔴 DCF socket
- 🟡 Thesis check — exists in deep dive; **🔴 proactive thesis-health watch not built** (the exit gap)
- ✅ Earnings transcript + reaction
- ✅ SEC filings
- 🟡 Report ingestion — research library (SQLite) built; **🔴 PDF ingestion not built**

### Decision
- ✅ Conviction + sizing (size_position)
- ✅ 腾位置 / portfolio advisor
- ✅ Entry points (tiered)
- ✅ House-view formation (personas) — 🔁 to migrate onto multi-source modules
- ✅ Quant screen / optimise / backtest (V3 Quant, 6 tools)

### Monitoring
- ✅ Portfolio + watchlist P&L
- ✅ Price / target alerts
- ✅ Catalyst calendar
- 🟡 Thesis-health watch — verdict state machine built, triggers not wired

### Review
- ✅ Monthly 复盘
- ✅ Decision journal (auto on trades)
- 🔴 Recommendation accuracy tracking

### Risk (cross-cutting)
- ✅ Concentration / correlation / drawdown (Phase 1)
- 🟡 Macro regime detector — built; **🔴 not wired into decisions**
- 🔴 VaR / macro stress test (Phase 2)

---

## PART 2 · THE DESKS — spec + build status

| Desk | Spec written | Built (legacy) | Migrated to model | Sources vendored | Notes |
|---|---|---|---|---|---|
| Research Librarian | 🟡 (blueprint stub) | 🟡 library only | 🔴 | 🔴 LlamaIndex | PDF ingestion missing |
| **Coverage Analyst** | 🟡 (blueprint stub) | ✅ deep dive/val | 🔴 | 🔴 TradingAgents + ai-hedge-fund | **next up**; thesis-watch is the gap |
| Idea Scout | 🟡 | ✅ radar/proactive | 🔴 | 🔴 OpenBB | multi-feed, not multi-opinion |
| House View (CIO) | 🟡 | ✅ personas/shadow | 🔴 | 🔴 ai-hedge-fund + TradingAgents | strongest A/B/C desk |
| Quant Engine | 🟡 | ✅ V3 Quant | 🔴 | 🔴 Qlib | single method |
| Risk Watch | 🟡 | ✅ Phase 1 | 🔴 | 🔴 (reference only) | always-on |

> "Spec written" = full six-field block agreed. Blueprint currently holds first-pass stubs; per-desk deep specs are the next work item.

---

## PART 3 · STANDARDS & SUPPORT — status

- ✅ Canonical objects (§3.1) — coded as dataclasses + enums in `src/core/objects.py` (7 objects, 6 enums, `to_dict` serialiser). Zero data-SDK imports (stable core).
- 🔴 Multi-source policy — agreed; modules not yet built.
- 🟡 Sources registry — listed; licenses to verify; nothing vendored yet.
- ✅ ONBOARDING.md added to root — single entry point; read order points to AGENTS → BLUEPRINT → BUILD_LOG → desk spec.
- ✅ WORK_ORDER.md written — executable, literal task list for a less-capable agent (infra → adapters → Coverage Analyst), each task self-contained with verification + Build Log wording.
- ✅ Communication & Delivery — Telegram/Notion live; timings live.
- 🟡 Systematic standards — templates exist ad-hoc; **🔴 not centralised.**
- 🟡 Knowledge — static playbooks partial; dynamic learning 🔴.
- 🟡 Operating discipline — adapter base now enforces declared `on_failure`; dependency direction checks not yet automated.
- 🟡 Infrastructure — adapters/storage/runtime live; **🔴 registry + dispatcher not built** (desks are hard-wired, not declared).
- 🟡 Coverage tag — equities deep; FICC/crypto shallow.

---

## DECISION LOG (newest first)

- **2026-06-29** — Built Coverage synthesize() verdict state machine (§5/§7): core-invalidated→broken, strained→weakening; push only on →broken; rec carries action+rationale, no sizing · `src/features/coverage/synthesize.py`
- **2026-06-29** — Added Coverage lenses: C/pillars native (reads driver.status); A/fundamentals and B/valuation interface stubs (vendoring deferred pending licence check) · `src/features/coverage/lenses.py`
- **2026-06-29** — Added Coverage Analyst desk-local types (Evidence, LensView, CoverageResult); kept out of core/objects.py per spec §10 · `src/features/coverage/types.py`
- **2026-06-29** — Built spine+objects morning briefing as standalone reference (PortfolioAdapter + PriceAdapter → Position objects → string); not wired to live scheduler · `src/features/morning_briefing.py`
- **2026-06-29** — Added PortfolioAdapter producing Position objects from get_holdings_cached (held only, shares>0) · `src/adapters/portfolio.py`
- **2026-06-29** — Added PriceAdapter wrapping src.tools.prices.get_live_prices behind the adapter interface · `src/adapters/prices.py`
- **2026-06-29** — Added adapter base interface (Adapter ABC + AdapterError, on_failure required) · `src/adapters/base.py`
- **2026-06-29** — Wrote `WORK_ORDER.md` (repo root) — an executable, literal-agent task list derived from CURRENT SPRINT + coverage_analyst.md. Tasks: 1 objects (done) → 2 adapter base → 3 PriceAdapter → 4 PortfolioAdapter → 5 morning-briefing reference → 6–9 Coverage Analyst (types, lenses, synthesize, orchestrator) → 10–11 deferred (not executable). Encoded provisional defaults for spec §13 open questions (read is_core from Driver; push only on →broken; rec carries action+rationale, no sizing). Listed in README folder layout. No code executed.
- **2026-06-29** — Added `ONBOARDING.md` to repo root as the single first-read entry point (orientation + read order + non-negotiable rules). Listed first in README folder layout ("← read this first"); referenced at the top of AGENTS.md "Where the truth lives" ("read before anything else").
- **2026-06-29** — Canonical objects coded → `src/core/objects.py`. 7 dataclasses (Name, Position, Thesis, Signal, Recommendation, Report, Event) + Driver, 6 enums (AssetClass, Verdict, DriverStatus, Action, SignalType, EventType), and a `to_dict()` serialiser (flattens enums/datetimes for Notion/SQLite). Decisions: (1) names referenced by ticker string (`name_ref`), not by Name instance — stable, serialisable, matches Notion/SQLite. (2) `Driver` promoted to its own object (id, summary, is_core, status, evidence) to support the Coverage Analyst per-driver state machine. (3) `Recommendation.size` kept free-text by design. (4) New code lives under `src/core/` (blueprint `core/` mapping, stays importable in `src` package). Verified: imports clean, round-trips through `to_dict`.
- **2026-06-29** — Adopted three-part architecture (Spine / Desks / Standards). Desks-first, then functions. Removed migration from the architecture map into this log. Multi-source per opinion desk (A/B/C) approved, with guardrail: sources are modules sharing canonical objects, not live frameworks. TradingAgents = vendored; ai-hedge-fund = vendored; OpenBB/Qlib/LlamaIndex = libraries; FinRobot/HKUDS repos = reference.

> Add one line per decision, before moving on.
