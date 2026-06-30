# Spike · TradingAgents → desk vendoring map (read-only inspection)

> Result of inspecting TradingAgents' real code (`tradingagents/agents/` + `agent_states.py`)
> to decide what real code each vendored desk can lift, and how cleanly. No code changed.
> Companion to `coverage_lenses_plan.md`. Source: TauricResearch/TradingAgents (Apache-2.0).

---

## How their pipeline shares data (the coupling)

TradingAgents is a LangGraph graph over one shared `AgentState`. The relevant fields:

- `market_report` ← Technical Analyst
- `sentiment_report` ← Sentiment (social) Analyst
- `news_report` ← News Analyst
- `fundamentals_report` ← Fundamentals Analyst
- `investment_debate_state` (bull_history · bear_history · current_response · count · judge_decision) ← Bull/Bear researchers + Research Manager
- `trader_investment_plan` ← Trader
- `risk_debate_state` ← Risk team (3 debaters)
- `final_trade_decision` ← Portfolio Manager
- `past_context` ← reflection/memory

**Confirmed by reading the code:**
- The **4 analysts are fully independent** — each reads only ticker/date + *its own* data tools, writes its own `*_report`, and never reads another analyst's report. → clean to lift.
- The **bull/bear researchers call NO data tools** — pure LLM. They read the 4 reports + the running debate (`count`, histories) and loop for multiple rounds. → no dependency baggage; the only work is feeding them the reports + running the loop.

---

## The elegant part: their 4 reports map 1:1 onto your desks

| TradingAgents report | Produced in their pipeline by | In YOUR system = output of |
|---|---|---|
| `fundamentals_report` | Fundamentals Analyst | **Coverage Analyst** |
| `market_report` | Technical Analyst | **Quant Engine** |
| `news_report` | News Analyst | **Idea Scout** |
| `sentiment_report` | Sentiment Analyst | **Idea Scout** |

So House View's bull/bear debate consumes exactly what Coverage + Idea Scout + Quant already emit. The vendoring lines up with the inter-desk flow we already designed (Coverage/Quant/Idea Scout → House View). No structural change needed.

---

## Per-desk liftability grades

| Desk | Module(s) to lift | Reads | Data-tool baggage | Grade |
|---|---|---|---|---|
| **Coverage** | `analysts/fundamentals_analyst.py` | ticker/date + financial-statement tools | **Yes** — swap their `get_balance_sheet`/`get_cashflow`/etc. → your FundamentalsAdapter | **Clean lift** |
| **Idea Scout** | `analysts/news_analyst.py` + the social/sentiment analyst | ticker/date + `get_news`/`get_global_news`/`get_macro_indicators`/sentiment tools | **Yes** — swap → your Tavily/news + FRED adapters | **Clean lift** |
| **House View** | `researchers/bull_researcher.py` + `bear_researcher.py` + `managers/research_manager` + `trader/trader.py` | the 4 reports + debate state | **None** (pure LLM) | **Lift-with-stub** — feed the 4 reports from upstream desks + run the `count` loop |
| Quant | — (Technical Analyst) | — | — | **Reference** (your own V3) — per your table |
| Risk | — (Risk team) | — | — | **Reference** (your own engine) — per your table |
| Librarian | `dataflows/` patterns | — | — | **Reference** — per your table |

---

## What this refines vs my earlier warning

I said "their data tools/deps ride along" for all vendored desks. The spike corrects that:
- **True for the analysts** (Coverage, Idea Scout) — they call data tools, so the integration work is swapping those tools for your adapters.
- **NOT true for House View's debate** — bull/bear/trader call no data tools, only the LLM. So lifting the debate has *almost no dependency baggage*; its only complexity is orchestration (assemble the 4 reports + run the multi-round loop). The thing I called "hardest" is hard only in wiring, not in dependencies.

---

## Recommended vendoring order (cleanest-first)

1. **News→Coverage evidence** seam fix (small, independent).
2. **Coverage** — lift real Fundamentals Analyst; rewire data tools → FundamentalsAdapter; output → per-driver `Thesis` statuses.
3. **Idea Scout** — lift real News + Sentiment Analysts; rewire → news/FRED adapters; output → `Signal`s.
4. **House View** — lift Bull/Bear + Research Manager + Trader; feed the 4 reports from Coverage/Quant/Idea Scout; run the `count` debate loop; output → `Recommendation`.

Each is its own work order, each verified, building a desk once.

---

## Open decisions before House View (the only non-trivial one)
1. **Debate rounds** — how many bull/bear rounds (`count` cap)? TradingAgents default is small (1–2). Suggest 2.
2. **Reflection/memory** (`past_context`) — lift their reflect-on-past-decisions loop now, or defer? Suggest defer (it needs a decision-history store; your decision journal could feed it later).
3. **Research Manager + Trader** — lift both, or let your existing `synthesize_view` play the manager role and only lift the debate? Suggest: lift bull/bear (the depth) + Research Manager (the judge); keep your sizing rule as the trader for now.
