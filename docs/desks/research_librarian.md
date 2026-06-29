# Desk Spec · Research Librarian

> Operations manual for one desk. Architecture context: `../BLUEPRINT.md` §2 Desk 1. Status: `../BUILD_LOG.md`.
> Mechanical desk (not A/B/C). It is the system's **intake**: it turns raw incoming research into structured, book-tied takeaways and routes them to the desks that act on them. Status: 🟡 partial (research library SQLite exists; PDF ingestion 🔴 not built).

---

## 1 · Identity
**Responsibility:** turn every incoming piece of external research (broker reports, earnings transcripts, SEC filings, pasted notes) into a structured `Report` with extracted thesis and risks, tie it to the names in the book, and route the takeaways to the desks that need them.

**The one job that makes it matter:** nothing the system reads should die in an inbox. Every report becomes a durable, searchable, name-linked object — and if it touches a covered name, the Coverage Analyst hears about it.

---

## 2 · Triggers
| Trigger | Type | Scope | Cadence / exact condition |
|---|---|---|---|
| A research document arrives | event (`Report` lands) | the document | fires when a PDF / broker note / transcript file is added to the research intake (Telegram document upload, or a file dropped into the library) |
| Earnings transcript published for any name | event (`Event:earnings` + transcript text available) | the reporting name | fires when a transcript becomes available for ingestion (distinct from Coverage's earnings trigger: Librarian *files* it, Coverage *re-tests the thesis* on it) |
| SEC filing fetched (10-K / 10-Q / 8-K) | event (`Event:threshold` filing) | the filing's name | fires when a new filing is pulled and its text is available to extract |
| User asks "summarise X" / pastes a report or URL | pull | the named document | on demand |
| Another desk requests an evidence pack | pull (inter-desk) | a named ticker/theme | Coverage Analyst or Idea Scout asks "what do we have filed on X?" → Librarian returns the relevant filed `Report`s + takeaways |

---

## 3 · Functions operated (from the Spine)
- **Report ingestion** — read library, extract thesis/risks (BLUEPRINT Part 1 · Research).

That is the only Spine function this desk operates. It does not deep-dive, value, or judge — it structures and routes.

---

## 4 · Inputs & outputs (canonical objects)
**Reads:** the raw document (via an ingestion adapter — never a PDF/HTTP SDK directly), the current coverage list (`Name`s held + watchlist) to resolve which names a report touches, and any existing `Thesis` for those names (so the takeaway can be framed as "supports / challenges the saved thesis").

**Writes:**
- one `Report` — `{ source, title, asset_class, date, extracted_thesis, extracted_risks, names_mentioned[] }`.
- one or more `Signal`s — one per material takeaway, `type=NEWS` (new fact) or `type=THESIS` (bears on a saved thesis), `subject_ref` = the affected ticker, `severity` 1–10, `source_desk="research_librarian"`.

On a pull request from another desk it also returns an **evidence pack** — the relevant filed `Report`s + extracted takeaways for the named ticker/theme (the report-side complement to the live-data `EvidenceService`).

**Destination (every hop is explicit):**
- **Telegram** — the takeaway card (§8) to the user.
- **Notion** — the `Report` persisted to the research library DB.
- **→ Coverage Analyst** (inter-desk) — for each **covered** name in `names_mentioned`, route the `THESIS` `Signal` so Coverage re-tests that name's thesis against the new report; and serve the evidence pack when Coverage asks.
- **→ Idea Scout** (inter-desk) — for each **uncovered** name in `names_mentioned`, route a `NEWS` `Signal` so Idea Scout can consider it as a candidate; and serve the evidence pack when Idea Scout asks.

This desk is **not** pull-only: its standing job is to fan structured signals out to Coverage and Idea Scout, and to serve evidence packs on request.

---

## 5 · Core logic
Mechanical pipeline, no opinion:
1. **Ingest** — pull the document text via the ingestion adapter. Hash the raw bytes (dedup key).
2. **Chunk** — split into passages (LlamaIndex chunking pattern) for extraction.
3. **Extract** — one structured pass: pull `extracted_thesis` (the report's core argument in 1–2 sentences), `extracted_risks[]`, and `names_mentioned[]` (tickers, resolved against the coverage list).
4. **Classify each mention** — covered (held/watchlist) vs uncovered. Covered → `THESIS` signal; uncovered → `NEWS` signal.
5. **Frame against saved thesis** — for covered names with an existing `Thesis`, label the takeaway `supports | challenges | neutral` relative to that thesis (this is the hook Coverage consumes — Librarian does not itself judge the verdict).
6. **Build + route** — assemble the `Report`, persist, send the Telegram card, and route signals per §4.

---

## 6 · Sources — single best implementation (mechanical desk, not A/B/C)
**TradingAgents role borrowed:** the **data / report-retrieval layer** that sits behind the analysts (evidence supply), not an opinion analyst. This is a mechanical desk, so it ships **one** method rather than presenting three opinions.

- **LlamaIndex** — mode **library** — RAG / chunking over reports, transcripts, filings (imported behind our ingestion interface in one place).
- **TradingAgents** — mode **reference** — crib three specific patterns, reimplemented to speak our objects:
  - `dataflows/` — the **fetch → structure** pattern (how raw sources become structured data).
  - `news_analyst.py` — the **content-ingestion** pattern (how a document is read and reduced to takeaways).
  - `reporting.py` — the **output-template** pattern (how the structured result is laid out).
- **FinGPT** — mode **reference** — financial-summarisation prompt patterns.

**No A/B/C.** Single shipped path: LlamaIndex for retrieval/chunking + an extraction/reporting prompt cribbed from the TradingAgents `dataflows/` + `news_analyst.py` + `reporting.py` patterns and FinGPT summarisation, all translated into our `Report` / `Signal` objects.

---

## 7 · Synthesis logic (mechanical — reconciliation, not opinion-merging)
There are no competing opinion sources to average. "Synthesis" here = collapsing many extracted passages into one coherent `Report`:
1. Multiple chunks mentioning the same driver/risk are **deduplicated** into a single bullet (keep the most specific phrasing).
2. Conflicting facts *within one report* (e.g. two figures for the same metric) are **surfaced, not resolved** — both are kept in `extracted_risks` flagged "source-internal conflict," because a self-contradicting report is itself a signal about its reliability.
3. Name resolution ambiguity (ticker vs company name) defaults to the coverage-list match; unresolved mentions are kept in `names_mentioned` flagged `unresolved`.

---

## 8 · Output template
```
📄 {SOURCE} — {TITLE}  ({DATE})
Takeaway: {one-line core argument}
Drivers:
  • {driver 1}
  • {driver 2}
Risks:
  • {risk 1}
  • {risk 2}
Names touched: {TICKER (covered → Coverage)}, {TICKER (new → Idea Scout)}
Filed to research library.
```

---

## 9 · Failure & guards
- **on_failure (extraction/LLM fails):** store the raw document to the library untouched, emit one `Signal` (`type=DATA`, severity 3, "extraction failed — manual review needed"), and send a Telegram line saying the file was saved but not parsed. **Never drop the file.**
- **on_failure (ingestion adapter / source unreachable):** flag the document as `pending-ingest` and re-queue; do not fabricate content.
- **degrade_to:** if name-resolution against the coverage list fails, still persist the `Report` with `names_mentioned` flagged `unresolved` — the file is filed and searchable even if routing is incomplete.
- **Cooldown:** do not re-trigger Coverage Analyst for the **same covered name** from report-ingestion more than **once per 24h** — a flurry of notes on one name produces one Coverage re-test, not many.
- **Dedup:** dedup by **report hash** (raw-bytes hash) — the same document is never ingested or routed twice. Each emitted `Signal` carries the originating report hash so a downstream desk can reject a duplicate.
- **Max chain depth:** Librarian is **hop 1** (a chain entry point — it is never triggered by another desk's output). Its routed signal may travel Librarian → Coverage (hop 2) → House View (hop 3), which is the hard cap of **3 hops total**. Librarian emits at depth 1 and stamps the chain depth on every routed signal.

---

## 10 · Module interfaces (for the builder)
```python
# all canonical types from core/objects.py
def run_librarian(document_ref: str) -> LibrarianResult: ...

# document_ref is resolved to text by an ingestion adapter (LlamaIndex behind our interface)
def ingest(document_ref: str) -> RawDoc: ...          # adapter call — no PDF/HTTP SDK in the desk
def extract(raw: RawDoc, coverage: list[Name]) -> Report: ...   # one structured LLM pass
def route(report: Report, theses: dict[str, Thesis]) -> list[Signal]: ...  # applies §4 routing

# LibrarianResult = {report: Report, signals: list[Signal], routed_to: list[str]}
```
Dependency rule: the desk never imports a PDF, HTTP, or LLM SDK directly — text arrives via the ingestion adapter and extraction goes through the LLM adapter. The desk depends inward on objects.

---

## 11 · Edge cases
- **Document mentions no covered or watchlist name** → still file the `Report`; emit no inter-desk routing; Telegram card notes "no book names touched."
- **Same report arrives twice** (re-forward) → dedup by hash; do nothing on the second arrival.
- **Multi-name report** (sector note touching 8 names) → one `Report`, N signals, but Cooldown still caps Coverage re-tests to one per name per 24h.
- **Non-English source** → extract in source language, store original + an English takeaway line.
- **Scanned/image PDF with no text layer** → ingestion adapter flags "no extractable text"; store raw, emit the `DATA` failure signal, do not guess.
- **Paywalled URL** → ingestion adapter returns failure; flag `pending-ingest`; never fabricate.

---

## 12 · Definition of done
- [ ] `Report` object is produced from a real document and persisted to the Notion research library.
- [ ] Covered-name mentions route a `THESIS` `Signal` to Coverage Analyst; uncovered-name mentions route a `NEWS` `Signal` to Idea Scout.
- [ ] Telegram card matches §8.
- [ ] Dedup by report hash verified (re-ingesting the same file is a no-op).
- [ ] Cooldown verified (two reports on the same covered name within 24h → one Coverage trigger).
- [ ] `on_failure` verified (kill the extractor → file is still stored, `DATA` signal emitted, nothing dropped).
- [ ] Chain depth stamped on every routed signal; Librarian always emits at depth 1.

---

## 13 · Open questions for Louis (decide before/while building)
1. **Intake channel** — is the primary way reports arrive a Telegram document upload, or a watched folder / email forward? (Determines the ingestion adapter's first implementation.)
2. **Covered-name routing aggressiveness** — should *every* covered-name mention trigger a Coverage re-test, or only mentions framed as "challenges the saved thesis"? (Default below: only `challenges` mentions route to Coverage; `supports`/`neutral` are filed silently.)
3. **Retention** — keep raw documents indefinitely in the library, or store only the structured `Report` + a link? (Storage vs completeness.)
