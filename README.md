# DC Official

A self-contained Python skill that wraps the public [Dynamite Circle Member API](https://www.dynamitecircle.com/developers/) — your own profile, trips, events, virtual events, tickets, invites, inbox, rooms, chapters, places lookup, and weekly locator digest.

Single file. Zero dependencies (stdlib only). Works as a CLI, Python library, **and** Model Context Protocol (MCP) server. Compatible with Claude Code, Claude Desktop, Codex CLI, Gemini CLI, Cursor, GitHub Copilot, and every other Agent Skills / MCP-compatible tool.

```
dc/dc.py    ← one file, three integration modes
```

## How it's exposed

The same `dc.py` file is shipped as **four** integrations — pick whichever fits how your tool talks to it:

| Integration | What it is | Invoke with | Dependencies |
|---|---|---|---|
| **Agent Skill** | Auto-discovered via `SKILL.md` frontmatter (Claude Code, Codex, Gemini CLI, Cursor, Copilot) | Just open the repo with the tool — it reads [`dc/SKILL.md`](dc/SKILL.md) and offers the commands | stdlib only |
| **CLI** | Run commands directly from the shell or scripts | `python3 dc/dc.py <command>` | stdlib only |
| **Python library** | Import in your own Python code | `from dc import DC; DC().profile()` | stdlib only |
| **MCP server** | Speaks Model Context Protocol over stdio (Claude Desktop, Cursor, Codex MCP, Cline, etc.) | `python3 dc/dc.py --mcp` | `pip install mcp` (optional) |

The `mcp` package is **lazy-imported** — Agent Skill / CLI / Python-library users never need it.

## Features

- **Full Member API coverage** — read + write across every public endpoint (run `python3 dc/dc.py help` for the live list)
- **Setup command** — saves your API key to a chmod-600 `.env.dc` next to the skill
- **Self-test command** — validates env, network, key shape, and a live `/profile` call end-to-end
- **Cursor pagination** — every list-returning command uses the same `[--limit N] [--cursor TOKEN]` shape and returns the canonical envelope `{items, count, cursor, has_more}`
- **Three output formats** — text (default, pretty JSON), `--json`, `--python`
- **MCP-ready** — same skill auto-exposes all commands as MCP tools
- **Pre-configured for Claude Code** — repo ships an `.mcp.json`, just `cd` and `claude`

## Quick start

### 1. Get an API key

DC profile dropdown → **DC Member API Key** (admins/testers only). Keys look like `dk_<api-key>` and are revocable from the same dropdown.

### 2. Save the key

```bash
python3 dc/dc.py setup --api-key dk_<api-key>
```

This writes `dc/.env.dc` (chmod 600, gitignored).

### 3. Verify the connection

```bash
python3 dc/dc.py self-test
```

Expected output:

```json
{
  "ok": true,
  "userID": "<your-id>",
  "displayName": "<Your Name>",
  "checks": [
    { "step": "env",      "ok": true, "message": "DC_API_KEY loaded from ..." },
    { "step": "keyShape", "ok": true, "message": "Key prefix valid (expected userID: <id>)" },
    { "step": "profile",  "ok": true, "message": "connected as userID[<id>] <Your Name>" }
  ]
}
```

### 4. Try a few commands

```bash
python3 dc/dc.py profile
python3 dc/dc.py trips --limit 5
python3 dc/dc.py events --past --limit 3
python3 dc/dc.py chapters --limit 5
python3 dc/dc.py permacode
```

Run `python3 dc/dc.py help` for the full command list.

## Setup per AI tool

### Claude Code

`.mcp.json` is already shipped with this repo. Open the repo with `claude`:

```bash
cd dc-official
claude
```

Tools become available as `mcp__dc__*`. First-time install of the optional MCP dependency:

```bash
pip install -r dc/requirements.txt
```

Skill discovery (CLI + import) works automatically via `dc/SKILL.md`.

### Claude Desktop

Edit your config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "dc": {
      "command": "python3",
      "args": ["/absolute/path/to/dc-official/dc/dc.py", "--mcp"]
    }
  }
}
```

Restart Claude Desktop.

### Codex CLI

Edit `~/.codex/config.toml`:

```toml
[mcp_servers.dc]
command = "python3"
args = ["/absolute/path/to/dc-official/dc/dc.py", "--mcp"]
```

Codex auto-discovers `AGENTS.md` (symlinked to `CLAUDE.md`) and `.agents/skills/` (symlinked to `.claude/skills/`).

### Gemini CLI

Reads `GEMINI.md` (symlinked to `CLAUDE.md`) for context. For MCP, configure in your Gemini CLI settings:

```yaml
mcp_servers:
  dc:
    command: python3
    args:
      - /absolute/path/to/dc-official/dc/dc.py
      - --mcp
```

### Cursor

Settings → MCP → Add server, then point at the same `dc.py --mcp`.

### GitHub Copilot

Reads `.github/copilot-instructions.md` for context. Copilot doesn't have native MCP support yet — use it for in-editor suggestions while developing.

### Any other MCP client

Same recipe: command = `python3`, args = `["/path/to/dc.py", "--mcp"]`. The protocol is standard.

## Output formats

```bash
python3 dc.py profile             # text (pretty JSON for dicts/lists)
python3 dc.py profile --json      # explicit JSON
python3 dc.py profile --python    # Python repr (eval-safe)
```

Global flags work before or after the command name:

```bash
python3 dc.py --json profile
python3 dc.py profile --json
```

## Cursor pagination

All list-returning commands take the same flags:

```bash
python3 dc.py trips
python3 dc.py trips --limit 10
python3 dc.py trips --limit 10 --cursor <opaque-token-from-previous-response>
python3 dc.py trips --past --limit 5
```

Standard envelope:

```json
{
  "items":    [ /* page of records */ ],
  "count":    42,
  "cursor":   "opaque-token-or-null",
  "has_more": true
}
```

Non-paginated extras (e.g. `totalUnread` on `inbox`) are passed through under an `extra` key.

## Use as a Python library

```python
import sys
sys.path.insert(0, "dc")
from dc import DC

dc = DC()

# Reads
profile  = dc.profile()
trips    = dc.trips(past=True, limit=10)
events   = dc.events(past=True, limit=5)
chapters = dc.chapters()
overlaps = dc.overlaps()
locator  = dc.locator(sections="homeCity,favoriteCities")

# Writes
dc.profile_update({"headline": "CEO at Acme"})
dc.trip_create(start_date="2026-12-01", end_date="2026-12-05", place_id="ChIJ...")
dc.event_rsvp("<eventID>", "yes")
dc.invite_create(email="new@friend.com", full_name="New Friend")
```

Override the API URL (e.g. for a local dev server):

```python
dc = DC(api_url="http://localhost:8080")
```

## API reference

The full live reference for the DC Member API — every endpoint, parameter, and response shape — is at **https://www.dynamitecircle.com/developers/**. The page is regenerated on every deploy, so it's always current.

## Staying up to date

The DC Member API ships new endpoints and refinements regularly. This skill is the official client and we update it whenever the API changes. **Plan for updates** — the skill will warn you on stderr the first time a request returns a server `X-API-Version` newer than `SKILL_VERSION`, and major-version bumps may break older clients.

Pick whichever integration style fits your project. From simplest to most isolated:

### 1. Plain git clone — quick local use

```bash
git clone https://github.com/Dynamite-Circle-Builders/dc-official.git
cd dc-official
python3 dc/dc.py setup --api-key dk_<api-key>
```

To update: `cd dc-official && git pull`. Run `self-test` afterwards.

Best for: trying things out, scripts you run by hand, no other repo involved.

### 2. Git submodule — pinned to a specific commit

If you have your own project repo and want `dc-official` versioned alongside it:

```bash
cd your-project
git submodule add https://github.com/Dynamite-Circle-Builders/dc-official.git vendor/dc-official
git commit -m "Add dc-official as submodule"
```

To update later:

```bash
cd vendor/dc-official
git pull origin main
cd ../..
git add vendor/dc-official
git commit -m "Bump dc-official"
```

Then in your code:

```python
import sys
sys.path.insert(0, "vendor/dc-official/dc")
from dc import DC
```

Best for: production-ish code where you want explicit, reviewable bumps.

### 3. Git subtree — same updates, no submodule indirection

```bash
cd your-project
git subtree add --prefix vendor/dc-official \
  https://github.com/Dynamite-Circle-Builders/dc-official.git main --squash
```

Update with:

```bash
git subtree pull --prefix vendor/dc-official \
  https://github.com/Dynamite-Circle-Builders/dc-official.git main --squash
```

Best for: teammates who don't know submodules — files just appear in your repo.

### 4. Symlink — share one clone across many projects

If you keep all your projects in `~/code/`:

```bash
git clone https://github.com/Dynamite-Circle-Builders/dc-official.git ~/code/dc-official

# In each project that uses it:
cd ~/code/your-project
ln -s ../dc-official vendor/dc-official
```

Now `cd ~/code/dc-official && git pull` updates every consumer at once. Project-level `.mcp.json` / `.codex/config.toml` entries can use `vendor/dc-official/dc/dc.py` and they'll resolve through the symlink.

Best for: power users with multiple personal projects and one machine.

### 5. Pip-installable Git ref — one-shot for a virtualenv

The skill is one file with no setup.py, but you can install the package the MCP server needs and check the file out as a sibling:

```bash
pip install mcp
git clone https://github.com/Dynamite-Circle-Builders/dc-official.git
```

To pin to a specific commit, just `git checkout <sha>` after cloning. We use [SemVer-ish](#staying-up-to-date) version tags on the skill itself (`SKILL_VERSION` constant) so you can match a known-good version.

Best for: CI environments, ephemeral containers, scripted setups.

### Update etiquette

- **Run `self-test` after every update.** Five seconds, catches breakage.
- **Watch stderr the first time you call any command after updating.** The version-mismatch warning prints once per process when the server is on a newer minor/major.
- **Pin in production.** Either pin a submodule/subtree commit, or check the `SKILL_VERSION` constant in your CI before deploying.
- **Major version bumps may be backwards-incompatible.** Read the release notes on the GitHub repo before pulling across a major boundary.

## Rate limits

| Tier              | Per minute | Per day |
|-------------------|------------|---------|
| DC Community      | 10         | 300     |
| DC BLACK          | 60         | 3,000   |

Headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, `X-RateLimit-Daily-Remaining`.

## Platform support

Tested on macOS, Linux, and Windows 10/11. Python 3.9+ required (uses `pathlib`, `Path.replace`, `inspect.signature`, `contextvars`, `urllib`).

### Windows notes

- The skill auto-reconfigures `stdout` and `stderr` to UTF-8 at startup, so emoji and em-dashes render correctly even on legacy `cmd.exe` (which defaults to cp1252). If you still see mojibake on a very old terminal, set `PYTHONIOENCODING=utf-8` once: `setx PYTHONIOENCODING utf-8` then restart your shell.
- `setup` writes `.env.dc` and tries to chmod 600 it. On Windows this is a no-op — the file inherits NTFS perms from its parent. The skill emits a one-time note about this when you run `setup`. Make sure your repo isn't on a shared drive.
- Use `python` or `python3.exe` to invoke; the `#!/usr/bin/env python3` shebang is ignored on Windows.

## Project layout

```
dc-official/
├── README.md                          # this file
├── CLAUDE.md                          # AI-tool guide (also linked as AGENTS.md, GEMINI.md)
├── AGENTS.md       → CLAUDE.md        # symlink (Codex)
├── GEMINI.md       → CLAUDE.md        # symlink (Gemini)
├── LICENSE                            # MIT
├── manifest.json                      # MCPB manifest (MCP 2025-11 spec)
├── .mcp.json                          # auto-registers `dc` MCP server in Claude Code
├── .codex/
│   └── config.toml                    # auto-registers `dc` for Codex CLI
├── .github/
│   └── copilot-instructions.md        # GitHub Copilot
│
├── dc/                                # ← REAL skill files (canonical)
│   ├── SKILL.md                       # Agent Skills frontmatter + usage
│   ├── config.json                    # name, version, env requirements
│   ├── dc.py                          # CLI + Python import + --mcp server
│   ├── requirements.txt               # optional MCP dep — skip for CLI/import
│   ├── .env.dc.example                # template
│   └── .env.dc                        # gitignored (created by `setup`)
│
├── docs/                              # ← REAL design docs (canonical)
│   ├── skill-info.md                # design rules / architecture
│   └── mcp-info.md                    # MCP setup for every supported client
│
├── .claude/                           # Agent Skills discovery (Claude Code)
│   ├── skills/dc  → ../../dc          # symlink to canonical skill
│   └── docs       → ../docs           # symlink to canonical docs
│
├── .agents/                           # Agent Skills discovery (Codex CLI)
│   ├── skills/dc  → ../../dc          # symlink to canonical skill
│   └── docs       → ../docs           # symlink to canonical docs
│
├── .gitignore
└── .gitattributes
```

### About the layout

The skill code (`dc/`) and the design docs (`docs/`) live at the repo root so they're visible in `ls` and feel like a normal Python project. The dotfile-prefixed directories (`.claude/`, `.agents/`) exist because AI tools auto-discover skills from those specific paths — they're kept hidden but each one **symlinks straight to the canonical folder**, so you only edit files in one place. Edit `dc/dc.py` and Claude Code, Codex, and Gemini CLI all see the same file via their respective discovery directories.

If you're adding new code or docs, edit `dc/` and `docs/` directly. The discovery folders take care of themselves.

## Maintenance

This repo is maintained by the Dynamite Circle team. It's read-only for the public — clone it and use it, but don't open PRs. If you spot a bug or want a new feature, contact us through the official DC channels.

## License

[MIT](LICENSE) — see the LICENSE file for the full text.

