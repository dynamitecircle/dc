# Skill Conventions

Design rules for the `dc` skill. The skill is structured to be predictable, easy to extend, and equally usable as a CLI, a Python library, or an MCP server.

## How to read this doc

- **MUST** — required policy. Violations break the contract.
- **SHOULD** — strong recommendation. Deviations need a reason.
- **INFO** — explanation or rationale.

## File layout

The entire skill lives in **one Python file**: `py/dc.py`.

| File | Required? | Purpose |
|---|---|---|
| `dc.py` | MUST | The skill — runtime + CLI + MCP entry point |
| `SKILL.md` | MUST | Agent Skills frontmatter + per-command usage |
| `config.json` | MUST | Skill metadata — name, version, env requirements |
| `requirements.txt` | MUST | Optional dep for MCP mode (`mcp>=0.9.0`). CLI/import users skip it |
| `.env.dc` | gitignored | Skill-local env file with `DC_API_KEY=…` (created by `setup` command) |
| `.env.dc.example` | MUST | Template documenting expected env vars |

## Module layout (inside `dc.py`)

Top of file (in order):

1. Module docstring
2. `__future__` import
3. Stdlib imports (`inspect`, `json`, `os`, `sys`, `pathlib`, `urllib`)
4. **Optional** MCP import wrapped in `try/except ImportError` → `_MCP_AVAILABLE` flag
5. **Mini-runtime** — `DCError`, `UsageError`, `_load_dotenv`, `_write_dotenv_value`, `skill_command` decorator, `ArgHelpers`, `HttpClient`, `Runtime` base class
6. **Skill code** — `_DCCore` (private), `DC` (public)
7. **Entry point** — `if __name__ == "__main__":` dispatching `--mcp` vs CLI

No bare functions outside classes. No top-level state mutation other than the optional `mcp` import.

## Two-class pattern (MUST)

Every skill ships two classes:

```python
class _DCCore:
    """Private — argument parsers + HTTP business logic."""

class DC(Skill):
    """Public — command registration and dispatch."""
```

Why split:

- **`_DCCore`** is the unit of testing/reuse. It has no knowledge of CLI dispatch — every method takes plain Python args and returns plain Python data
- **`DC`** is the wrapper. Each method is decorated with `@skill_command` and delegates to `_core`. Wrappers must be thin — no business logic

Wrapper responsibilities:

1. `super().__init__("dc", __file__)` to set up name + env loading
2. Optionally accept an `api_url=` kwarg for local-dev override
3. Construct `self._core = _DCCore(self)`
4. Re-run `_discover_commands()` after `_core` is set (decorators reference `self._core` indirectly)
5. Define every public command as a `@skill_command`-decorated method
6. End the file with `if __name__ == "__main__": ...`

## `@skill_command` decorator

Mark a method as a CLI command and (automatically) an MCP tool:

```python
@skill_command(name="trips",
               help="List your trips [--past] [--limit N] [--cursor TOKEN]",
               parser=_DCCore._parse_list_args)
def trips(self, past=False, limit=50, cursor=None):
    return self._core.trips(past=past, limit=limit, cursor=cursor)
```

Fields:

| Field | Required | Meaning |
|---|---|---|
| `name` | MUST | Public command name. Kebab-case. Used in CLI and as MCP tool name |
| `help` | SHOULD | One-line description for `help` listing |
| `parser` | optional | Static method on `_DCCore` that converts raw CLI args → `(args, kwargs)`. Required if the command takes flags |

There are **no** `mode="read"|"write"` labels, no permission gates, no extension hooks. The decorator is intentionally minimal.

## Argument parsing

### Space-form flags (canonical)

```bash
python3 dc.py trips --limit 10 --cursor abc
```

The `--limit=10` form is also accepted by `ArgHelpers.parse_flags`, but space form is the documented style.

### Parsers

Each command that takes flags has a matching `_parse_*` static method on `_DCCore`. The runtime calls the parser with the raw arg list and expects a `(positional_args_tuple, kwargs_dict)` return.

Common parsers (already implemented):

| Parser | Used by | Handles |
|---|---|---|
| `_parse_list_args` | every list command | `--past`, `--status`, `--type`, `--sections`, `--q` + cursor pagination |
| `_parse_id_with_limit` | `event-attendees`, `browse-rooms` | positional ID + cursor pagination |
| `_parse_trip_create` / `_parse_trip_update` | trip CRUD | `--start-date`, `--end-date`, `--place-id`, `--event-id` |
| `_parse_rsvp` | event/virtual-event RSVP | positional ID + `--status yes\|maybe\|no` |
| `_parse_invite` | `invite-create` | `--email`, `--full-name` |
| `_parse_profile_patch` | `profile-update` | passes all `--<key> <value>` flags through as a `fields` dict |
| `_parse_places_search` | `places-search` | `--q`, `--limit` |
| `_parse_setup` | `setup` | `--api-key` or positional |

When adding a new command:

1. If it has flags → add a parser to `_DCCore`
2. Reference it via `parser=_DCCore._parse_yourparser` on the `@skill_command` decorator
3. The wrapper's signature must match what your parser returns

## Cursor pagination (MUST)

Every list-returning command takes:

```bash
[--limit N] [--cursor TOKEN]
```

And returns the canonical envelope:

```json
{
  "items":    [ /* array of records */ ],
  "count":    42,
  "cursor":   "opaque-token-or-null",
  "has_more": true
}
```

Non-paginated extras (e.g. `totalUnread` on `inbox`) must pass through under `extra`:

```json
{
  "items":    [ /* rooms */ ],
  "count":    3,
  "cursor":   null,
  "has_more": false,
  "extra": {
    "totalUnread": 7
  }
}
```

Use `_DCCore._wrap_list(api_data, items_field)` — it reads `nextCursor` from the upstream response and wraps the list.

## HTTP layer

`HttpClient` is stdlib-only (`urllib.request`). All API calls go through `_DCCore._get` / `_post` / `_patch` / `_delete`, which:

1. Build the URL with query params (filtering out `None`/empty)
2. Inject `Authorization: Bearer <DC_API_KEY>` and `Accept: application/json`
3. Encode JSON body if present
4. Parse the response and call `_unwrap` to extract `data` from `{ ok, data?, error?, message? }`
5. Raise `DCError` on `ok: false` or non-JSON responses

Never call `urllib` directly inside `_DCCore` business methods — go through `_get` / `_post` / etc.

## Versioning + version-mismatch warning

`DC_API_VERSION` is declared at the top of `dc.py`. Bump it manually when the skill catches up to a new API version.

Two things happen with this version:

- **Outbound** — every request sends `User-Agent: dc-py/<DC_API_VERSION>` so server-side logs can attribute traffic.
- **Inbound** — `HttpClient` reads the server's `X-API-Version` response header. `_VersionTracker.observe()` compares it to `DC_API_VERSION` and prints a one-shot stderr warning when the server has new features (major or minor bump). Patch-only differences are silent. If the skill is *ahead* of the server, no warning — that's a normal upgrade path.

The warning fires once per process. Scripts and MCP servers don't get spammed.

## Output formatting

Three formats, decided in `Skill._format_output`:

| Format | Trigger | Behavior |
|---|---|---|
| `text` | default | Pretty-print dicts/lists as JSON, scalars as `str(...)` |
| `json` | `--json` or `--format json` | `json.dumps(result, indent=2, ensure_ascii=False)` |
| `python` | `--python` or `--format python` | `repr(result)` |

Commands return native Python objects. Formatting happens at the dispatch boundary — never inside business methods.

## Error handling

Two exception types:

- **`UsageError`** — argument validation failures. Raised by parsers and command methods. Exit code 2. Prefixed with `Usage:` in CLI output
- **`DCError`** — env, network, auth, API errors. Exit code 1. Prefixed with `Error:` in CLI output

Wrappers should let these bubble up. The base `Skill.dispatch` catches both and prints to stderr.

When raising:

- Be specific. `"trip-create requires --start-date and --end-date"` beats `"missing args"`.
- Don't expose internals. `"unauthorized"` is fine. Stack traces are not.

## Env handling

The skill loads its env from `py/.env.dc` — **next to the skill file**, not at the repo root. This makes the skill self-contained: copy the folder, copy the env.

- `_load_dotenv` is a zero-dep parser (KEY=VALUE, optional quotes, `#` comments)
- `_write_dotenv_value` is atomic (temp file → rename) and chmod 600s the result
- The `setup` command is the only place that writes to the env file
- Env vars set by the shell win over the file (POSIX-standard precedence)

## MCP mode

The same skill auto-exposes its commands as MCP tools:

```bash
python3 dc.py --mcp
```

How it works:

1. `_MCP_AVAILABLE` flag set at module load via `try: from mcp.server import Server`
2. `--mcp` in `sys.argv` → entry point calls `DC().run_mcp()`
3. `run_mcp()` builds an `mcp.server.Server`, registers `list_tools` (one per `@skill_command`) and `call_tool` (translates MCP args → CLI raw_args, then invokes via `self._invoke`)
4. Result serialized as `TextContent` (JSON for dicts/lists, str for scalars)

If `mcp` is not installed → clean install hint, no traceback. CLI and Python-import users have **zero** dependencies.

## Adding a new command

1. Add the business logic to `_DCCore` (returns plain Python data)
2. If it takes flags → add a `_parse_*` static method to `_DCCore`
3. Add a `@skill_command`-decorated wrapper to `DC` that delegates to `_core`
4. Update `SKILL.md` with usage examples
5. Verify the new endpoint is documented in the live API reference: https://www.dynamitecircle.com/developers/
6. Smoke-test:
   ```bash
   python3 py/dc.py help                    # appears in list
   python3 py/dc.py <new-command> --json    # round-trips
   python3 py/dc.py self-test               # unaffected
   ```

## What's intentionally absent

These were design choices. **Do not add them without a discussion**:

- ❌ Telemetry / usage tracking
- ❌ Error logging to disk (`.errors.jsonl`)
- ❌ Read/write mode labels on commands
- ❌ Extension hooks (`@skill_extension`)
- ❌ Owner-binding / runtime metadata
- ❌ Lint rules / sweep / pulse
- ❌ Cross-skill loaders
- ❌ Background workers / queues
- ❌ Third-party deps for the core skill (only optional `mcp` for the server mode)

The skill is a **public-grade example**. Keep it that way.
