# MCP — Setup for every supported client

The `dc` skill exposes its commands as [Model Context Protocol](https://modelcontextprotocol.io) tools when run with the `--mcp` flag. The protocol is standard, so the same server works in every MCP-compatible client.

## One-time install

The `mcp` package is the only dependency:

```bash
pip install -r .claude/skills/dc/requirements.txt
# or
pip install mcp
```

CLI and Python-import users **do not need** this — the import is lazy.

## Run the server manually

```bash
python3 .claude/skills/dc/dc_skill.py --mcp
```

The server speaks JSON-RPC over stdio. It's not meant to be used directly — wire it into a client below.

## Smoke test (no client needed)

```bash
(
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}'
  echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
  echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"profile","arguments":{}}}'
) | python3 .claude/skills/dc/dc_skill.py --mcp
```

You should see three JSON-RPC responses: `initialize` ack, `tools/list` with the full tool set, and `tools/call profile` with your profile data.

## Visual debugger (Inspector)

Anthropic's official MCP Inspector opens a browser UI to test each tool individually:

```bash
npx @modelcontextprotocol/inspector python3 .claude/skills/dc/dc_skill.py --mcp
```

Browser opens. Click any tool → fill in arguments → run → see the response. The "Console" tab shows raw JSON-RPC traffic.

## Per-client setup

### Claude Code

The repo ships an `.mcp.json` at its root, so opening this repo with `claude` auto-loads the server:

```bash
cd /path/to/dc-official
claude
```

Tools become available as `mcp__dc__profile`, `mcp__dc__trips`, etc.

To register the server in a different Claude Code project (e.g. a workspace that contains this repo as a sub-directory):

```bash
cd /path/to/your-other-project
claude mcp add dc --scope project -- python3 /absolute/path/to/dc-official/.claude/skills/dc/dc_skill.py --mcp
```

This creates `<project>/.mcp.json`. Claude Code scopes:

| Scope | File written | Visibility |
|---|---|---|
| `--scope user` | `~/.claude.json` (top-level) | You, in any project |
| `--scope local` | `~/.claude.json` under `projects[<dir>]` | You, only this project |
| `--scope project` | `<project>/.mcp.json` | Anyone who clones the repo |

To remove: `claude mcp remove dc -s <scope>`.

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
      "args": [
        "/absolute/path/to/dc-official/.claude/skills/dc/dc_skill.py",
        "--mcp"
      ]
    }
  }
}
```

Restart Claude Desktop. The `dc` tools appear in the bottom-right tools menu of every chat.

### Codex CLI

Edit `~/.codex/config.toml`:

```toml
[mcp_servers.dc]
command = "python3"
args = [
  "/absolute/path/to/dc-official/.claude/skills/dc/dc_skill.py",
  "--mcp"
]
```

Codex auto-discovers `AGENTS.md` (symlinked to `CLAUDE.md`) and `.agents/skills/` (symlinked to `.claude/skills/`) for additional context.

### Gemini CLI

Configure in your Gemini CLI settings (location depends on your install):

```yaml
mcp_servers:
  dc:
    command: python3
    args:
      - /absolute/path/to/dc-official/.claude/skills/dc/dc_skill.py
      - --mcp
```

`GEMINI.md` (symlinked to `CLAUDE.md`) provides additional context for the assistant.

### Cursor

1. Open Settings → MCP
2. Click **Add server**
3. Fill in:
   - Name: `dc`
   - Command: `python3`
   - Args: `/absolute/path/to/dc-official/.claude/skills/dc/dc_skill.py --mcp`

### Cline / Continue / Windsurf / Zed

Same shape. Each tool has its own settings UI but the data is the same:

```
command: python3
args:    [absolute path to dc_skill.py, --mcp]
```

Refer to the tool's own MCP docs for the exact location of the settings file.

### GitHub Copilot

Copilot doesn't have native MCP support yet (as of late 2025). It does read `.github/copilot-instructions.md` for project context, which we've already populated. For interactive tool use, prefer one of the clients above.

## How it works internally

When you launch the server, `DCSkill.run_mcp()`:

1. Imports `mcp.server.Server` and `mcp.server.stdio` (lazy — only at this point)
2. Creates a server named `"dc"`
3. Walks `self._commands` (the `@skill_command`-decorated methods)
4. Registers `list_tools` → returns one `Tool` per command (name, description, schema)
5. Registers `call_tool` → translates MCP arguments into a CLI-style raw_args list, invokes the command via `self._invoke()` (same code path as CLI), wraps the result as `TextContent`
6. Runs the stdio loop until the client disconnects

The MCP path **reuses the CLI parsers** — there's no separate code path for argument validation. A bug fix in a CLI parser fixes the MCP behavior automatically.

## Auth

The MCP server inherits the same `.env.dc` as the CLI:

- Server starts → `DCSkill.__init__` → `Skill.__init__` → `_load_dotenv(.env.dc)` → `DC_API_KEY` in `os.environ`
- Tool call → `_DCCore._api_key()` reads `os.environ["DC_API_KEY"]`

So `python3 dc_skill.py setup --api-key dk_...` (run once) authorizes all three modes. No separate MCP auth step.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `MCP mode requires the optional 'mcp' package` | Not installed | `pip install -r .claude/skills/dc/requirements.txt` |
| Tools list is empty in the client | Server didn't start (path wrong, perms) | Run the smoke test above to isolate |
| `unauthorized` from any tool | `DC_API_KEY` not loaded | Run `setup --api-key dk_...` once at the CLI |
| Tools list shows but calls hang | Client expects HTTP transport, not stdio | Check the client's transport setting; this server is stdio-only |
| Different Python found by client | Client's PATH differs from yours | Use an absolute path to `python3` in the args |

## Adding a virtualenv to the args

If your system Python doesn't have `mcp` installed but you've created a venv, point the client at the venv's Python:

```json
{
  "mcpServers": {
    "dc": {
      "command": "/absolute/path/to/dc-official/.venv/bin/python3",
      "args": [
        "/absolute/path/to/dc-official/.claude/skills/dc/dc_skill.py",
        "--mcp"
      ]
    }
  }
}
```

This is the cleanest setup — keeps `mcp` isolated from system Python.
