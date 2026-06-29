# CLAUDE.md

@AGENTS.md

<!--
This is a thin shim. The canonical instructions live in AGENTS.md (read by Codex, Cursor, etc.);
the @import above pulls them in for Claude Code, which does not read AGENTS.md natively.
One source of truth, no drift. Put ONLY Claude-specific notes below.
-->

## Claude Code notes
- Detailed specs load on demand: `docs/BLUEPRINT.md`, `docs/BUILD_LOG.md`, `docs/desks/*.md`.
- When starting a desk, read its `docs/desks/{desk}.md` first — it is the operations manual.
- Keep this file and AGENTS.md lean; heavy detail belongs in `docs/`, not here.
