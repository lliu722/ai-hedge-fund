# CLAUDE.md

@AGENTS.md

<!--
This is a thin shim. The canonical instructions live in AGENTS.md (read by Codex, Cursor, etc.);
the @import above pulls them in for Claude Code, which does not read AGENTS.md natively.
One source of truth, no drift. Put ONLY Claude-specific notes below.
-->

## Architecture: the asset-class desk model
Canonical spec: `src/desks/MASTER.md` (map) + `src/desks/DESKS.md` (detail). Read before touching desk logic.
- 8 idea-generating desks + 1 PM/Risk orchestrator (`pm_risk`).
- Every desk extends the Desk Contract (`src/desks/base.py`) and emits `IdeaCard`s (`src/desks/contracts.py`).
- Only `pm_risk` sets size / weight / allocation. Desks never size.
- Update `src/desks/MASTER.md` (and the desk's `spec/`) in the same change when scope or contract changes.
- **Strangler migration:** `src/desks/` runs ALONGSIDE the live bot (`src/tools/`). Do NOT cut over until proven + approved.

## Claude Code notes
- New work lives in `src/desks/`. The live bot is `src/tools/`. `legacy/` is read-only reference — never import from it (copy + rewire).
- Detail loads on demand: `src/desks/DESKS.md`, per-desk `spec/`, `docs/BUILD_LOG.md`.
- Keep this file and AGENTS.md lean; heavy detail belongs in `src/desks/` specs, not here.
