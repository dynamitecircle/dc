# GitHub Copilot — Project Instructions

This repo ships one self-contained Python skill at
`.claude/skills/dc/dc_skill.py` that wraps the public DC Member API.

When suggesting code in this repo:

- Stay stdlib-only — no `requests`, no `httpx`, no `pydantic`. The skill
  is intentionally zero-dependency.
- The skill file is the canonical entry point. Do not split it into
  multiple modules.
- Two-class pattern: `DCSkill` is the public wrapper, `_DCCore` is the
  private helper with all HTTP and parsing logic. Keep new commands in
  this same shape.
- Register CLI commands with `@skill_command(name=, help=, parser=)`.
  Don't introduce new decorators or modes.
- Space-form CLI flags (`--limit 10`, not `--limit=10`).
- All list-returning commands return the envelope
  `{items, count, cursor, has_more}` — use the `_wrap_list` helper.
- API base URL: `https://api.dynamitecircle.com`. Auth header:
  `Authorization: Bearer dk_<api-key>`.
- Env config lives in `.claude/skills/dc/.env.dc` (skill-local).

For the user-facing setup instructions, see
[../CLAUDE.md](../CLAUDE.md) and
[../.claude/skills/dc/SKILL.md](../.claude/skills/dc/SKILL.md).
