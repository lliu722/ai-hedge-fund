# 工作日志 · AI Investment System — Build Log (Status Tracker)

> Companion to **`BLUEPRINT.md` (图纸)**. The blueprint says *what the system is*; this log says *where each piece is*.
> **Rule:** after every change, update the matching line here (status + location), and add a line to the Decision Log.
> Status key: ✅ done · 🟡 partial · 🔴 not built · ⏸ parked · 🔁 needs migration onto new model
> Last updated: 2026-06-29

---

## CURRENT SPRINT — migration to the new model (strangler; bot stays live)

1. ✅ Write canonical objects (§3.1) as code — the shared language. → `src/core/objects.py`
2. 🟡 Rebuild the **morning briefing** on spine + objects as the reference implementation. → `src/features/morning_briefing.py` (standalone; not wired to live scheduler)
3. 🟡 Build **Coverage Analyst** skeleton (richest desk; closes the thesis-health / sell-discipline gap). → types + lenses + synthesize + orchestrator built & verified (`src/features/coverage/`). REMAINING: vendor lens A (TradingAgents fundamentals) + lens B (ai-hedge-fund Damodaran) — licence check needed; real evidence assembly; wire triggers (touches live scheduler).
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
| **Coverage Analyst** | 🟡 (blueprint stub) | ✅ deep dive/val | 🟡 | 🔴 TradingAgents + ai-hedge-fund | orchestrator built; triggers/lenses-vendoring pending |
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

- **2026-06-29** — Added LLMAdapter wrapping call_deepseek; on_failure (falsy or ❌) returns "" · `src/adapters/llm.py`
- **2026-06-29** — Added FundamentalsAdapter (yfinance .info → 11-key normalised dict); on_failure returns {} · `src/adapters/fundamentals.py`
- **2026-06-29** — Added NOTICE.md attributing TradingAgents (Apache-2.0) and ai-hedge-fund (MIT) per vendoring duty · `NOTICE.md`
- **2026-06-29** — Wrote `WORK_ORDER_PHASE2.md` (Coverage real lenses) after Louis's decisions: data source = yfinance (financialdatasets deferred), LLM on (all 3 lenses real), §13 defaults stand. Literal tasks P1 NOTICE.md → P2 FundamentalsAdapter (yfinance .info, 11 keys) → P3 LLMAdapter (wraps call_deepseek) → P4 EvidenceService → P5 lens B real (ported Damodaran DCF + margin-of-safety, P/E degrade) → P6 lens A real (TradingAgents prompt → per-driver JSON) → P7 end-to-end on MU. Triggers + Notion write-back explicitly out of scope. Data shapes pre-verified against aswath_damodaran.py and call_deepseek signature.
- **2026-06-29** — Verified vendoring licences for Coverage lenses: TradingAgents = Apache-2.0 (raw LICENSE checked), virattt/ai-hedge-fund = MIT © 2024 Virat Singh (raw LICENSE checked). Both permit vendoring with attribution. Key finding: lens B's source (Damodaran agent) is already in-repo at `src/agents/aswath_damodaran.py` (this repo forks ai-hedge-fund) — adapt in place, no external copy. Wrote plan → `docs/desks/coverage_lenses_plan.md` (prereq chain: FundamentalsAdapter → LLMAdapter → EvidenceService → lens B → lens A; 3 decisions flagged for Louis: data source, LLM-now-or-defer, §13 confirm). No code yet — gated on decisions.
- **2026-06-29** — Re-executed WORK_ORDER Task 5 to the hardened spec: morning briefing now computes pnl_pct vs avg_cost (was reading the always-0 Position.pnl_pct), uses exact price-dict access (`.get("price")`), treats falsy price as "data pending", sorts by computed pnl descending. Verified: header `Morning Briefing — 2026-06-29`, top line `SNDK: $2090.71 (260.2% vs cost)`. File: `src/features/morning_briefing.py`.
- **2026-06-29** — Handover review: confirmed Codex completed WORK_ORDER Tasks 1–9 (adapters, morning briefing, full Coverage Analyst skeleton). All verification commands re-run and pass (synthesize → BROKEN/SELL and run_coverage → WEAKENING exactly as specified). No blockers raised. Reconciled CURRENT SPRINT item 3 status 🔴→🟡 (was stale; skeleton built, vendoring/triggers remain). One known gap: morning briefing was built to the pre-hardening Task 5 spec (shows 0.0% pnl) — next task for the worker is to redo it to the hardened spec.
- **2026-06-29** — Built run_coverage() orchestrator wiring 3 lenses → synthesize → CoverageResult; degrade_to documented; not wired to triggers · `src/features/coverage/desk.py`
- **2026-06-29** — Built Coverage synthesize() verdict state machine (§5/§7): core-invalidated→broken, strained→weakening; push only on →broken; rec carries action+rationale, no sizing · `src/features/coverage/synthesize.py`
- **2026-06-29** — Added Coverage lenses: C/pillars native (reads driver.status); A/fundamentals and B/valuation interface stubs (vendoring deferred pending licence check) · `src/features/coverage/lenses.py`
- **2026-06-29** — Added Coverage Analyst desk-local types (Evidence, LensView, CoverageResult); kept out of core/objects.py per spec §10 · `src/features/coverage/types.py`
- **2026-06-29** — Built spine+objects morning briefing as standalone reference (PortfolioAdapter + PriceAdapter → Position objects → string); not wired to live scheduler · `src/features/morning_briefing.py`
- **2026-06-29** — Added PortfolioAdapter producing Position objects from get_holdings_cached (held only, shares>0) · `src/adapters/portfolio.py`
- **2026-06-29** — Added PriceAdapter wrapping src.tools.prices.get_live_prices behind the adapter interface · `src/adapters/prices.py`
- **2026-06-29** — Added adapter base interface (Adapter ABC + AdapterError, on_failure required) · `src/adapters/base.py`
- **2026-06-29** — Handover audit of WORK_ORDER.md against live code shapes. Fixed: (1) Task 4 PortfolioAdapter referenced a non-existent `current_price` key in get_holdings_cached (real keys: account/avg_cost/name/rating/role/sector/shares/thesis) — removed, price now comes only from PriceAdapter; (2) Task 5 morning briefing used wrong failure mode (failed ticker is present-but-`{}`, not absent) and sorted by an always-0 field — rewrote with exact inner-key access (`price`/`change_pct`) and computable pnl_pct vs avg_cost; (3) reconciled coverage_analyst.md §13 open questions vs WORK_ORDER Tasks 7–8 so a literal worker won't STOP — §13 now defers to WORK_ORDER as authoritative provisional defaults. Files: WORK_ORDER.md, docs/desks/coverage_analyst.md.
- **2026-06-29** — Wrote `WORK_ORDER.md` (repo root) — an executable, literal-agent task list derived from CURRENT SPRINT + coverage_analyst.md. Tasks: 1 objects (done) → 2 adapter base → 3 PriceAdapter → 4 PortfolioAdapter → 5 morning-briefing reference → 6–9 Coverage Analyst (types, lenses, synthesize, orchestrator) → 10–11 deferred (not executable). Encoded provisional defaults for spec §13 open questions (read is_core from Driver; push only on →broken; rec carries action+rationale, no sizing). Listed in README folder layout. No code executed.
- **2026-06-29** — Added `ONBOARDING.md` to repo root as the single first-read entry point (orientation + read order + non-negotiable rules). Listed first in README folder layout ("← read this first"); referenced at the top of AGENTS.md "Where the truth lives" ("read before anything else").
- **2026-06-29** — Canonical objects coded → `src/core/objects.py`. 7 dataclasses (Name, Position, Thesis, Signal, Recommendation, Report, Event) + Driver, 6 enums (AssetClass, Verdict, DriverStatus, Action, SignalType, EventType), and a `to_dict()` serialiser (flattens enums/datetimes for Notion/SQLite). Decisions: (1) names referenced by ticker string (`name_ref`), not by Name instance — stable, serialisable, matches Notion/SQLite. (2) `Driver` promoted to its own object (id, summary, is_core, status, evidence) to support the Coverage Analyst per-driver state machine. (3) `Recommendation.size` kept free-text by design. (4) New code lives under `src/core/` (blueprint `core/` mapping, stays importable in `src` package). Verified: imports clean, round-trips through `to_dict`.
- **2026-06-29** — Adopted three-part architecture (Spine / Desks / Standards). Desks-first, then functions. Removed migration from the architecture map into this log. Multi-source per opinion desk (A/B/C) approved, with guardrail: sources are modules sharing canonical objects, not live frameworks. TradingAgents = vendored; ai-hedge-fund = vendored; OpenBB/Qlib/LlamaIndex = libraries; FinRobot/HKUDS repos = reference.

> Add one line per decision, before moving on.
