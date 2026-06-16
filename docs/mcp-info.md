# MCP — Setup for every supported client

There are **two ways** to get DC's tools into an MCP client:

1. **Hosted MCP (no install)** — point your client at the remote endpoint `https://api.dynamitecircle.com/mcp`. Nothing to clone, install, or update; always on the current API version. Best for chat apps (Claude web/Desktop, Cursor, ChatGPT).
2. **Local server (this client)** — run `dc.py --mcp` as a local stdio server with the `--mcp` flag. Best when you want offline capability, a pinned version, or to develop against a local API. Most of this doc covers this path.

## Hosted MCP (no install)

`https://api.dynamitecircle.com/mcp` (Streamable HTTP). Authenticate with one-click OAuth (reuses your DC login) or a `dk_` API key as a Bearer header.

| Client | How |
|---|---|
| **Claude Code** | `claude mcp add --transport http dc https://api.dynamitecircle.com/mcp` |
| **Claude web / Desktop / mobile** | Settings → Connectors → **Add custom connector** → paste URL → **Connect** → sign in with DC (paid plan; Team/Enterprise admins may need to approve first) |
| **VS Code** | `code --add-mcp '{"name":"dc","url":"https://api.dynamitecircle.com/mcp"}'` (or the badge below) |
| **Cursor / ChatGPT / other MCP apps** | Add a custom / remote MCP connector pointing at the URL above |

One-click badges (hosted MCP):

[![Add to Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](cursor://anysphere.cursor-deeplink/mcp/install?name=dc&config=eyJ1cmwiOiJodHRwczovL2FwaS5keW5hbWl0ZWNpcmNsZS5jb20vbWNwIn0=)
&nbsp;
[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_DC-007ACC?logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect/mcp/install?name=dc&config=%7B%22url%22%3A%22https%3A%2F%2Fapi.dynamitecircle.com%2Fmcp%22%7D)

Discovery metadata is published at [`/.well-known/mcp.json`](https://api.dynamitecircle.com/.well-known/mcp.json); the OAuth protected-resource descriptor is at `/.well-known/oauth-protected-resource`. The server is also listed in the [Official MCP Registry](https://registry.modelcontextprotocol.io) as `io.github.dynamitecircle/dc` (which feeds VS Code, Smithery, PulseMCP, and others).

## Local server (this client)

The `dc` skill exposes its commands as [Model Context Protocol](https://modelcontextprotocol.io) tools when run with the `--mcp` flag. The protocol is standard, so the same server works in every MCP-compatible client.

## One-time install

The `mcp` package is the only dependency:

```bash
pip install -r py/requirements.txt
# or
pip install mcp
```

CLI and Python-import users **do not need** this — the import is lazy.

## Run the server manually

```bash
python3 py/dc.py --mcp
```

The server speaks JSON-RPC over stdio. It's not meant to be used directly — wire it into a client below.

## Auto-updating local server via `uvx` (PyPI)

To run a local stdio server **without a clone** that pulls the latest published client on every launch, use [`uv`](https://docs.astral.sh/uv/)'s `uvx`:

```json
{
  "mcpServers": {
    "dc": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--refresh", "--from", "dynamitecircle[mcp]", "dc", "--mcp"],
      "env": { "DC_API_KEY": "dk_<api-key>" }
    }
  }
}
```

Three things make this work:

- **`--from dynamitecircle[mcp]`** — the package is `dynamitecircle` but the console script is `dc`, so you can't write `uvx dynamitecircle`; `--from` names the package (and the `[mcp]` extra installs the MCP dependency) while `dc` is the command to run.
- **`--refresh`** — forces `uvx` to check PyPI for a newer version instead of reusing its cache. Drop it if you'd rather pin to whatever's cached.
- **`env.DC_API_KEY`** — an ephemeral `uvx` install has no `py/.env.dc`, so pass the key via the env block. It takes precedence over any `.env.dc` anyway (existing env vars always win).

Same idea with `pipx`: `pipx run --spec 'dynamitecircle[mcp]' dc --mcp` (add `--no-cache` to force the latest).

## Quick check (no client needed)

```bash
(
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}'
  echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
  echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"profile","arguments":{}}}'
) | python3 py/dc.py --mcp
```

You should see three JSON-RPC responses: `initialize` ack, `tools/list` with the full tool set, and `tools/call profile` with your profile data.

## Visual debugger (Inspector)

Anthropic's official MCP Inspector opens a browser UI to test each tool individually:

```bash
npx @modelcontextprotocol/inspector python3 py/dc.py --mcp
```

Browser opens. Click any tool → fill in arguments → run → see the response. The "Console" tab shows raw JSON-RPC traffic.

## Per-client setup

### Claude Code

The repo ships an `.mcp.json` at its root, so opening this repo with `claude` auto-loads the server:

```bash
cd /path/to/dc
claude
```

Tools become available as `mcp__dc__profile`, `mcp__dc__trips`, etc.

To register the server in a different Claude Code project (e.g. a workspace that contains this repo as a sub-directory):

```bash
cd /path/to/your-other-project
claude mcp add dc --scope project -- python3 /absolute/path/to/dc/py/dc.py --mcp
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
        "/absolute/path/to/dc/py/dc.py",
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
  "/absolute/path/to/dc/py/dc.py",
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
      - /absolute/path/to/dc/py/dc.py
      - --mcp
```

`GEMINI.md` (symlinked to `CLAUDE.md`) provides additional context for the assistant.

### VS Code

VS Code has native MCP support and reads `.vscode/mcp.json` (per-workspace) or your user `mcp.json`. For the **hosted** server, the one-click badge above or `code --add-mcp '{"name":"dc","url":"https://api.dynamitecircle.com/mcp"}'` is all you need. For a **local** stdio server, add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "dc": {
      "type": "stdio",
      "command": "python3",
      "args": ["/absolute/path/to/dc/py/dc.py", "--mcp"]
    }
  }
}
```

VS Code shows inline **Start / Stop / Restart** actions above each server in that file. It also renders the [MCP registry](https://code.visualstudio.com/docs/agent-customization/mcp-servers) in the Extensions view, so once `dc` is listed there it's installable from inside the editor.

### Cursor

1. Open Settings → MCP
2. Click **Add server**
3. Fill in:
   - Name: `dc`
   - Command: `python3`
   - Args: `/absolute/path/to/dc/py/dc.py --mcp`

Or use the one-click **Add to Cursor** badge above (hosted MCP).

### Cline / Continue / Windsurf / Zed

Same shape. Each tool has its own settings UI but the data is the same:

```
command: python3
args:    [absolute path to dc.py, --mcp]
```

Refer to the tool's own MCP docs for the exact location of the settings file.

### GitHub Copilot

Copilot doesn't have native MCP support yet (as of late 2025). It does read `.github/copilot-instructions.md` for project context, which we've already populated. For interactive tool use, prefer one of the clients above.

## How it works internally

When you launch the server, `DC.run_mcp()`:

1. Imports `mcp.server.Server` and `mcp.server.stdio` (lazy — only at this point)
2. Creates a server named `"dc"`
3. Walks `self._commands` (the `@skill_command`-decorated methods)
4. Registers `list_tools` → returns one `Tool` per command (name, description, schema)
5. Registers `call_tool` → translates MCP arguments into a CLI-style raw_args list, invokes the command via `self._invoke()` (same code path as CLI), wraps the result as `TextContent`
6. Runs the stdio loop until the client disconnects

The MCP path **reuses the CLI parsers** — there's no separate code path for argument validation. A bug fix in a CLI parser fixes the MCP behavior automatically.

## Auth

The MCP server inherits the same `.env.dc` as the CLI:

- Server starts → `DC.__init__` → `Skill.__init__` → `_load_dotenv(.env.dc)` → `DC_API_KEY` in `os.environ`
- Tool call → `_DCCore._api_key()` reads `os.environ["DC_API_KEY"]`

So `python3 dc.py setup --api-key dk_...` (run once) authorizes all three modes. No separate MCP auth step.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `MCP mode requires the optional 'mcp' package` | Not installed | `pip install -r py/requirements.txt` |
| Tools list is empty in the client | Server didn't start (path wrong, perms) | Run the quick check above to isolate |
| `unauthorized` from any tool | `DC_API_KEY` not loaded | Run `setup --api-key dk_...` once at the CLI |
| Tools list shows but calls hang | Client expects HTTP transport, not stdio | Check the client's transport setting; this server is stdio-only |
| Different Python found by client | Client's PATH differs from yours | Use an absolute path to `python3` in the args |

## Adding a virtualenv to the args

If your system Python doesn't have `mcp` installed but you've created a venv, point the client at the venv's Python:

```json
{
  "mcpServers": {
    "dc": {
      "command": "/absolute/path/to/dc/.venv/bin/python3",
      "args": [
        "/absolute/path/to/dc/py/dc.py",
        "--mcp"
      ]
    }
  }
}
```

This is the cleanest setup — keeps `mcp` isolated from system Python.
