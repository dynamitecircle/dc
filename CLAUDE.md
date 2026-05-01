# DC Official — AI Tool Guide

This repo ships a single self-contained Python skill that wraps the public **DC Member API** (`https://api.dynamitecircle.com`). It works the same from Claude Code, Codex, Gemini CLI, GitHub Copilot, Cursor, and any other Agent Skills- or MCP-compatible tool.

## At a glance

- **One file**: `.claude/skills/dc/dc_skill.py`
- **Three modes**: CLI, Python import, MCP server (`--mcp` flag)
- **Stdlib only** for CLI/import. The `mcp` package is **lazy-imported** — only required for `--mcp` mode
- **Full coverage** — every public Member API endpoint is wrapped (run `help` for the live list)
- **Pre-configured `.mcp.json`** at the repo root — Claude Code auto-loads the server when you `cd` in
- **Zero internal-only knowhow** — public-grade design with no telemetry, no usage tracking, no error capture, no extension hooks, no read/write gates

## What this is

`.claude/skills/dc/dc_skill.py` contains:

- A small embedded mini-runtime — `Skill` base class, `@skill_command` decorator, `ArgHelpers` (flag parsing, cursor pagination, envelopes), `HttpClient` (urllib-based)
- Two concrete classes:
  - `_DCCore` — private helper with `_parse_*` argument parsers and HTTP business logic
  - `DCSkill(Skill)` — public wrapper with `@skill_command`-decorated methods for every endpoint

The full reference for the underlying API is at https://www.dynamitecircle.com/developers/.

## First-time setup

You need a personal API key. Generate one from your DC profile dropdown → **DC Member API Key**. Then save it:

```bash
python3 .claude/skills/dc/dc_skill.py setup --api-key dk_<userID>_<random>
```

This writes `.claude/skills/dc/.env.dc` (chmod 600). The file is gitignored.

Verify:

```bash
python3 .claude/skills/dc/dc_skill.py self-test
```

You should see `connected as userID[<id>] <Your Name>` in the `profile` step.

## Running commands

```bash
# List every command (with one-line help)
python3 .claude/skills/dc/dc_skill.py help

# Inspect one command in detail
python3 .claude/skills/dc/dc_skill.py help trips

# Your own profile
python3 .claude/skills/dc/dc_skill.py profile

# Your upcoming trips
python3 .claude/skills/dc/dc_skill.py trips

# RSVP to an event
python3 .claude/skills/dc/dc_skill.py event-rsvp <eventID> --status yes
```

Full per-command CLI docs live in [.claude/skills/dc/SKILL.md](.claude/skills/dc/SKILL.md). The full live API reference — every endpoint, parameter, and response shape — is at **https://www.dynamitecircle.com/developers/** (regenerated on every deploy, always current).

## Output formats

| Format | Flag | When to use |
|---|---|---|
| **Text** (default) | none, or `--format text` | Pretty JSON for dicts/lists, raw for scalars |
| **JSON** | `--json` or `--format json` | Piping into `jq`, scripts, structured logs |
| **Python repr** | `--python` or `--format python` | Eval-safe Python objects |

```bash
python3 dc_skill.py profile             # text
python3 dc_skill.py profile --json      # JSON
python3 dc_skill.py profile --python    # repr
python3 dc_skill.py --json profile      # flag works before or after command
```

## MCP mode

The same skill can run as a [Model Context Protocol](https://modelcontextprotocol.io) server, exposing every command as a tool to MCP-compatible clients (Claude Desktop, Cursor, Codex, Cline, Continue, Windsurf, Zed, etc.).

```bash
# One-time: install the optional MCP dependency
pip install -r .claude/skills/dc/requirements.txt

# Run as an MCP server (stdio)
python3 .claude/skills/dc/dc_skill.py --mcp
```

This repo ships a `.mcp.json` at its root so **Claude Code** opens this repo with the server pre-registered. Tools become available as `mcp__dc__profile`, `mcp__dc__trips`, etc. No additional config needed beyond the one-time `pip install`.

For all other clients, see [.claude/docs/mcp.md](.claude/docs/mcp.md) for the per-tool config snippets.

## Conventions

The skill enforces a small set of conventions designed to be predictable and easy to extend. Full spec in [.claude/docs/skill-conventions.md](.claude/docs/skill-conventions.md).

| Convention | What it means |
|---|---|
| **Two-class pattern** | `DCSkill` is the public wrapper. `_DCCore` is the private helper with `_parse_*` parsers + HTTP business logic |
| **`@skill_command` decorator** | Marks a method as a CLI command. Provides `name`, `help`, optional `parser` |
| **Space-form flags** | `--limit 10`, not `--limit=10` (parser also accepts equals form for convenience, but space is canonical) |
| **Cursor pagination** | Every list-returning command takes `[--limit N] [--cursor TOKEN]` and returns `{items, count, cursor, has_more}` |
| **Envelope for lists** | `_DCCore._wrap_list(api_data, items_field)` — produces the canonical envelope, passes non-paginated extras through under `extra` |
| **Skill-local env** | API key lives in `.claude/skills/dc/.env.dc` next to the skill, not at the repo root |
| **Lazy MCP import** | `mcp` is imported in a top-level `try/except`. CLI/import paths never trigger the import |

## Architecture diagram

```
                ┌─────────────────────────┐
                │   dc_skill.py (1 file)  │
                ├─────────────────────────┤
                │                         │
                │  Mini-runtime           │
                │  ├── Skill (base)       │
                │  ├── @skill_command     │
                │  ├── ArgHelpers         │
                │  └── HttpClient         │
                │                         │
                │  Skill                  │
                │  ├── _DCCore (private)  │
                │  └── DCSkill (public)   │
                │                         │
                └─┬─────────┬─────────┬───┘
                  │         │         │
       CLI ───────┘         │         └────── MCP server
       Python import ───────┘                 (--mcp flag)

         ▼                  ▼                       ▼
  python3 dc_skill.py    from dc_skill        Claude Desktop /
    profile              import DCSkill        Cursor / Codex /
                                                Cline / etc.
```

## Files in this repo

```
dc-official/
├── README.md                          # public landing page
├── CLAUDE.md                          # this file (also AGENTS.md / GEMINI.md)
├── AGENTS.md       → CLAUDE.md        # symlink (Codex CLI)
├── GEMINI.md       → CLAUDE.md        # symlink (Gemini CLI)
├── .mcp.json                          # auto-registers `dc` MCP server in Claude Code
├── .codex/
│   └── config.toml                    # auto-registers `dc` for Codex CLI
├── .github/
│   └── copilot-instructions.md        # GitHub Copilot guide
├── .claude/
│   ├── docs/
│   │   ├── skill-conventions.md       # design rules / architecture
│   │   └── mcp.md                     # MCP setup for every supported client
│   └── skills/
│       └── dc/
│           ├── SKILL.md               # Agent Skills frontmatter + per-command usage
│           ├── config.json            # name, version, env requirements
│           ├── dc_skill.py            # CLI + Python import + --mcp server
│           ├── requirements.txt       # optional MCP dep — skip for CLI/import
│           ├── .env.dc.example        # template
│           └── .env.dc                # gitignored (created by `setup`)
├── .agents/
│   └── skills      → ../.claude/skills    # symlink (Codex CLI compat)
├── .gitignore
└── .gitattributes
```

## Multi-tool compatibility

| Tool | How it discovers the skill |
|---|---|
| **Claude Code** | `CLAUDE.md` + `.claude/skills/dc/SKILL.md` + `.mcp.json` (auto-loads server) |
| **Claude Desktop** | Manual `claude_desktop_config.json` MCP entry |
| **Codex CLI** | `AGENTS.md` (symlink) + `.agents/skills/` (symlink) + `~/.codex/config.toml` |
| **Gemini CLI** | `GEMINI.md` (symlink) + Gemini settings |
| **Cursor** | Settings → MCP → Add server |
| **GitHub Copilot** | `.github/copilot-instructions.md` |

The skill itself is plain Python — invoke it however your tool prefers.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Missing required environment variable: DC_API_KEY` | `.env.dc` not yet created | Run `setup --api-key dk_...` |
| `DC_API_KEY must start with 'dk_'` | Wrong value passed to `setup` | Check the key from the DC profile dropdown |
| `MCP mode requires the optional 'mcp' package` | `mcp` not installed | `pip install -r .claude/skills/dc/requirements.txt` |
| `unauthorized: ...` from API | Key revoked or wrong tier | Regenerate from DC profile dropdown |
| Rate-limited (429) | Above per-minute / per-day cap | Check `X-RateLimit-*` response headers |
| `Network error contacting api.dynamitecircle.com` | Local network / VPN / DNS | `curl https://api.dynamitecircle.com/profile -H "Authorization: Bearer $KEY"` to isolate |

## See also

- [README.md](README.md) — public landing page
- [.claude/docs/skill-conventions.md](.claude/docs/skill-conventions.md) — design rules / architecture
- [.claude/docs/mcp.md](.claude/docs/mcp.md) — MCP setup for every supported client
- [.claude/skills/dc/SKILL.md](.claude/skills/dc/SKILL.md) — per-command usage examples
- **https://www.dynamitecircle.com/developers/** — full live API reference
