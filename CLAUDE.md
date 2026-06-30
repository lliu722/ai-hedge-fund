# CLAUDE.md

@AGENTS.md

<!--
This is a thin shim. The canonical instructions live in AGENTS.md (read by Codex, Cursor, etc.);
the @import above pulls them in for Claude Code, which does not read AGENTS.md natively.
One source of truth, no drift. Put ONLY Claude-specific notes below.
-->

## Architecture: Desks (asset-class model — being adopted)
The system is being migrated to the asset-class desk model. Canonical definition: `docs/DESKS.md` —
read it before touching any desk logic. Key rules:
- 8 idea-generating desks + 1 PM/Risk orchestrator (`pm_risk`).
- Every desk implements the shared Desk Contract (`src/desks/base.py`) and emits `IdeaCard`s (`src/desks/contracts.py`).
- Only `pm_risk` sets position size / weight / allocation. Desks never size.
- Surgical patches; commit per change; log decisions to the Notion Architecture & Decision Log;
  update `docs/DESKS.md` in the same change when scope or contract changes.
- **Strangler migration in progress:** new `src/desks/` package runs ALONGSIDE the live bot + the
  prior 6 function-desks (`src/features/`, `src/core/objects.py`). Do NOT delete the old model until
  the new one is proven and cutover is explicitly approved.

## Claude Code notes
- Detailed specs load on demand: `docs/DESKS.md` (active model), `docs/BLUEPRINT.md` + `docs/desks/*.md` (prior 6-desk model, superseded but not yet retired), `docs/BUILD_LOG.md`.
- Keep this file and AGENTS.md lean; heavy detail belongs in `docs/`, not here.
