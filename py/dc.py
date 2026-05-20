#!/usr/bin/env python3
from __future__ import annotations
"""DC Member API client — read and act on your own DC membership data.

A self-contained Python client that wraps the public DC Member API at
https://api.dynamitecircle.com — your own profile, trips, events, virtual
events, tickets, invites, inbox, rooms, chapters, places, and locator
digest. Every endpoint is authenticated with the team member's personal
API key (see SKILL.md for setup).

Compatible with Claude Code, Codex, Gemini CLI, and GitHub Copilot — the
file is plain Python with stdlib only and a small embedded runtime that
provides command registration, argument parsing, and CLI dispatch.

All list-returning commands accept cursor pagination flags
`[--limit N] [--cursor TOKEN]` and return the standard envelope:
`{ items: [...], count: N, cursor: <next-or-null>, has_more: bool }`.

Usage as import:
    from dc import DC
    dc = DC()
    dc.profile()                              # your profile
    dc.profile_update({"headline": "..."})    # patch profile fields
    dc.limits()                               # rate limits + current usage
    dc.announcements()                        # mixed feed of recent broadcast announcements
    dc.announcements_latest()                 # one most-recent announcement per channel
    dc.trips()                                # upcoming trips
    dc.trips(past=True, cursor="abc")         # paged history
    dc.overlaps()                             # destination overlaps
    dc.trip_create(start_date="2026-12-01", end_date="2026-12-05", place_id="ChIJ...")
    dc.trip_update("<tripID>", end_date="2026-12-06")
    dc.trip_delete("<tripID>")
    dc.events()                               # upcoming in-person events
    dc.event_attendees("<eventID>")           # who's attending
    dc.event_rsvp("<eventID>", "yes")         # RSVP yes|maybe|no
    dc.virtual_events()
    dc.virtual_event_rsvp("<sessionID>", "yes")
    dc.tickets(status="valid")
    dc.invites()
    dc.permacode()
    dc.invite_create(email="x@y.com", full_name="X Y")
    dc.inbox()
    dc.rooms()
    dc.browse_rooms("channel")
    dc.chapters()                             # all DC chapters (cities)
    dc.chapter("<cityID>")                    # one chapter + members
    dc.places_search(q="Tokyo")               # Google Places search
    dc.place("<placeID>")                     # Place details
    dc.locator(sections="homeCity,favoriteCities")

Usage as CLI:
    python3 dc.py setup --api-key dk_<api-key>
    python3 dc.py profile
    python3 dc.py profile-update --headline 'CEO at Acme'
    python3 dc.py trips [--past] [--limit N] [--cursor TOKEN]
    ... (run `python3 dc.py help` for the full list)
"""

import base64
import contextlib
import contextvars
import inspect
import json
import os
import sys
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode

# ── Cross-platform stdio safety ────────────────────────────────────────
#
# Force UTF-8 on stdout / stderr so emit text and the version-mismatch
# warning don't crash on legacy Windows consoles (cmd.exe defaults to
# cp1252). On Mac and Linux this is a no-op — the streams are already
# UTF-8. `errors="replace"` ensures we never raise UnicodeEncodeError
# even on the most stubborn legacy terminal — characters we can't encode
# get replaced with `?`.
#
# `sys.stdout.reconfigure` was added in Python 3.7. The try/except guard
# protects against fringe cases where stdout has been replaced with a
# non-TextIOWrapper (e.g. some embedded launchers, IDE plugins).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError, OSError):
        pass

# Optional MCP support — only loaded when the user runs `python3 dc.py --mcp`.
# CLI and Python-import users have zero dependencies.
try:
    from mcp.server import Server as _MCPServer
    from mcp import types as _mcp_types
    from mcp.shared.message import SessionMessage as _MCPSessionMessage
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


@contextlib.asynccontextmanager
async def _mcp_stdio_server():
    """MCP stdio transport with buffered streams for Python SDK compatibility."""
    if not _MCP_AVAILABLE:
        raise RuntimeError("MCP package is not available")

    import asyncio

    import anyio

    read_stream_writer, read_stream = anyio.create_memory_object_stream(100)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(100)

    def _stdout_write(line: str):
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    async def stdin_reader():
        try:
            loop = asyncio.get_running_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
            async with read_stream_writer:
                while True:
                    raw_line = await reader.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace")
                    try:
                        message = _mcp_types.JSONRPCMessage.model_validate_json(line)
                    except Exception as exc:  # noqa: BLE001
                        await read_stream_writer.send(exc)
                        continue
                    await read_stream_writer.send(_MCPSessionMessage(message))
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stdout_writer():
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    payload = session_message.message.model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                    _stdout_write(payload)
                    await asyncio.sleep(0)
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_reader)
        tg.start_soon(stdout_writer)
        try:
            yield read_stream, write_stream
        finally:
            await read_stream.aclose()
            await write_stream.aclose()
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()


# ── Client version ──────────────────────────────────────────────────────
# Bump manually when this client catches up to a new API version. Sent as
# the User-Agent on every request; compared against the server's
# `X-API-Version` header to warn the user when they're behind.
DC_API_VERSION = "1.17.1"


# ════════════════════════════════════════════════════════════════════════
#  Embedded mini-runtime
# ════════════════════════════════════════════════════════════════════════


class DCError(RuntimeError):
    """Raised by client code when validation, auth, or API calls fail."""


class UsageError(DCError):
    """Raised when the CLI is invoked with the wrong arguments."""


# ── Emit sink ──────────────────────────────────────────────────────────
#
# `Runtime.emit(*args)` is the public way for command code to send extra
# text back to the calling agent (follow-up instructions, context hints,
# friendly status). When no command is in flight the call falls back to
# `print(...)` so it is always safe to use.
#
# The dispatcher sets `_EMIT_SINK` to a list-appender for the duration of
# each command. Anything emitted lands in the buffer, and the dispatcher
# decides where to surface it: CLI prints it to stderr after the result;
# the MCP server appends it as an extra `TextContent`; Python callers get
# it on `result.emitted`.
_EMIT_SINK: contextvars.ContextVar = contextvars.ContextVar(
    "dc_emit_sink", default=None,
)


# ── .env loader ────────────────────────────────────────────────────────

def _env_file_path(source_file: str) -> Path:
    """Return the client-local .env path — `<dc_dir>/.env.dc` next to this file."""
    return Path(source_file).resolve().parent / ".env.dc"


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ if not already set.

    Zero-dependency parser — supports plain `KEY=VALUE` lines, optional
    quotes around the value, and `#` comments. Existing env vars win.
    """
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


def _write_dotenv_value(path: Path, key: str, value: str) -> None:
    """Append or replace a KEY=VALUE entry in a .env file (atomic write)."""
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    new_line = f"{key}={value}"
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(new_line)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ── @skill_command decorator ───────────────────────────────────────────

def skill_command(*, name: str, help: str = "", parser=None, args: dict | None = None):
    """Mark a method as a CLI command.

    Args:
        name:   public command name (kebab-case)
        help:   one-line description shown in `help`
        parser: optional staticmethod that converts raw_args → (args, kwargs)
        args:   optional per-flag schema hints used to generate richer MCP
                tool input schemas. Keys are kebab-case flag names (matching
                what the CLI accepts). Values are dicts with any of:
                  - type:        "string" | "integer" | "boolean" | "number"
                  - description: human-readable explanation
                  - required:    bool (default False)
                  - enum:        list of allowed values
                  - format:      "date" | "email" | etc. (JSON Schema format)
                  - default:     default value when omitted
                Example:
                    args={
                        "start-date": {"type": "string", "format": "date", "required": True,
                                       "description": "YYYY-MM-DD"},
                        "status":     {"type": "string", "enum": ["yes", "maybe", "no"],
                                       "required": True},
                    }
                When omitted, the MCP tool schema falls back to
                `{type: object, additionalProperties: true}` (still works,
                just less helpful for the agent).
    """
    def wrap(fn):
        fn._skill_command = {
            "name":   name,
            "help":   help,
            "parser": parser,
            "args":   args,
        }
        return fn
    return wrap


def _build_input_schema(arg_specs: dict | None, *, positional: list[str] | None = None) -> dict:
    """Convert a `@skill_command(args=...)` dict into a JSON Schema object.

    `positional` lists positional args derived from the wrapper signature.
    Each positional arg is exposed as a required named field — agents pass
    them as named keys (e.g. `{"event-id": "abc"}`) and the dispatcher
    translates them back to positional CLI args.

    Positional names are only auto-included when they don't collide with
    a flag in `arg_specs` and the name doesn't look like a parser-collected
    bag (e.g. `fields` for `profile-update`, where the parser collects all
    unknown flags into a single dict).
    """
    if arg_specs is None and not positional:
        return {"type": "object", "additionalProperties": True}

    arg_specs = arg_specs or {}
    properties: dict = {}
    required: list[str] = []

    # Skip auto-included positional names that look like parser-collected
    # bags or that already appear in arg_specs.
    _PARSER_BAG_NAMES = {"fields", "raw_args", "raw-args", "kwargs", "_unused"}

    for arg_name in (positional or []):
        if arg_name in _PARSER_BAG_NAMES:
            continue
        if arg_name in arg_specs:
            continue
        properties[arg_name] = {
            "type":        "string",
            "description": f"Positional argument: {arg_name}",
        }
        required.append(arg_name)

    for flag_name, spec in arg_specs.items():
        # Skip sentinel keys (start with underscore) — they configure the
        # schema rather than describing a real flag.
        if flag_name.startswith("_"):
            continue
        prop = {"type": spec.get("type", "string")}
        if "description" in spec:
            prop["description"] = spec["description"]
        if "enum" in spec:
            prop["enum"] = spec["enum"]
        if "format" in spec:
            prop["format"] = spec["format"]
        if "default" in spec:
            prop["default"] = spec["default"]
        properties[flag_name] = prop
        if spec.get("required"):
            required.append(flag_name)

    # If any spec has `additional: True`, the schema accepts unknown flags
    # too. This is for commands like `profile-update` whose parser collects
    # every `--<key> <value>` flag — the listed args= entries are common
    # examples but the agent is free to send more.
    accept_extras = any(
        isinstance(spec, dict) and spec.get("additional") is True
        for spec in arg_specs.values()
    )

    schema: dict = {
        "type":                 "object",
        "properties":           properties,
        "additionalProperties": True if accept_extras else False,
    }
    if required:
        schema["required"] = required
    return schema


# ── Argument helpers ───────────────────────────────────────────────────

class ArgHelpers:
    """Static helpers for common CLI argument parsing patterns."""

    @staticmethod
    def parse_flags(args):
        """Split --flag=value and --flag value pairs from positional args.

        Supports three flag styles:
        - --key=value (single token)
        - --key value (two tokens, value must not start with --)
        - --flag (boolean, no value)

        Returns:
            tuple: (positional_args, flags_dict)
        """
        positional = []
        flags: dict = {}
        i = 0
        while i < len(args):
            arg = args[i]
            if arg.startswith("--"):
                key = arg[2:]
                if "=" in key:
                    k, val = key.split("=", 1)
                    flags[k] = val
                    i += 1
                elif i + 1 < len(args) and not args[i + 1].startswith("--"):
                    flags[key] = args[i + 1]
                    i += 2
                else:
                    flags[key] = True
                    i += 1
            else:
                positional.append(arg)
                i += 1
        return positional, flags

    @staticmethod
    def require_args(raw_args, count, usage):
        """Raise UsageError if fewer than `count` positional args were given."""
        if len(raw_args) < count:
            raise UsageError(usage)

    @staticmethod
    def parse_int(value, *, name: str = "value", default: int | None = None) -> int:
        if value is None or value == "":
            if default is not None:
                return default
            raise UsageError(f"--{name} is required")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise UsageError(f"--{name} must be an integer (got {value!r})")

    @staticmethod
    def parse_pagination(raw_args, *, defaults: dict | None = None):
        """Pull --limit / --cursor out of raw_args; return (pagination, remaining).

        defaults: {"limit": int} — the limit used when --limit is absent.
        """
        defaults = defaults or {}
        positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        pag = {
            "limit":  ArgHelpers.parse_int(flags.pop("limit", defaults.get("limit", 50)), name="limit"),
            "cursor": flags.pop("cursor", None) or None,
        }
        rest: list = list(positionals)
        for k, v in flags.items():
            rest.append(f"--{k}")
            if v is not True:
                rest.append(str(v))
        return pag, rest

    @staticmethod
    def envelope(items, *, cursor=None) -> dict:
        """Standard list-response shape: items, count, cursor, has_more."""
        items = list(items or [])
        return {
            "items":    items,
            "count":    len(items),
            "cursor":   cursor or None,
            "has_more": bool(cursor),
        }


# ── HTTP client (stdlib only) ──────────────────────────────────────────

class HttpClient:
    """Minimal urllib-based HTTP client — GET/POST/PATCH/DELETE returning JSON.

    Always sends `User-Agent: dc-py/<DC_API_VERSION>` so server-side
    logs can attribute traffic to the client. Reads the server's
    `X-API-Version` response header and notifies a registered observer
    (used by `_VersionTracker` to warn users when their client is behind).

    Handles HTTP 429 (rate limited) automatically: parses `Retry-After`
    (preferred — RFC 7231 standard) or `X-RateLimit-Reset` (DC's epoch
    timestamp), waits the indicated time, and retries up to
    `HttpClient.max_retries` times. Configurable via the `--max-retries N`
    and `--no-retry` global CLI flags, or by setting the class attributes
    before any request.
    """

    # Module-level observer: called once per response with the server's
    # X-API-Version header value (or None if missing). Set by
    # `_VersionTracker.attach()` at runtime construction time.
    _on_server_version = None  # type: ignore[var-annotated]

    # Retry policy. Mutable so dispatch() can adjust based on CLI flags.
    max_retries: int = 1          # number of retries on 429 (1 by default)
    max_retry_wait: int = 120     # cap any single wait at 2 minutes
    fallback_retry_wait: int = 60 # used when neither header is present

    @staticmethod
    def _parse_retry_seconds(headers, *, body: dict | None = None) -> int:
        """Extract seconds-to-wait from a 429 response.

        Order of preference:
          1. `Retry-After` header — RFC 7231 standard, may be seconds OR HTTP-date
          2. `X-RateLimit-Reset` header — DC's per-window epoch timestamp
          3. Number embedded in the JSON body's `message` field (e.g.
             "Try again in 32 seconds.") — last-ditch fallback
          4. `HttpClient.fallback_retry_wait` (60s) — gives up gracefully
        """
        if not headers:
            headers = {}

        # 1. Retry-After (seconds form)
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                return max(1, int(float(retry_after)))
            except (TypeError, ValueError):
                pass  # may be HTTP-date — fall through to the next strategy

        # 2. X-RateLimit-Reset (epoch seconds)
        reset_raw = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")
        if reset_raw:
            try:
                reset_ts = int(reset_raw)
                import time as _time
                wait = reset_ts - int(_time.time())
                if wait > 0:
                    return wait
            except (TypeError, ValueError):
                pass

        # 3. Parse "Try again in N seconds." from the body message
        if body and isinstance(body, dict):
            msg = str(body.get("message", ""))
            import re as _re
            match = _re.search(r"in (\d+)\s*second", msg, _re.IGNORECASE)
            if match:
                try:
                    return max(1, int(match.group(1)))
                except (TypeError, ValueError):
                    pass

        # 4. Last-resort fallback
        return HttpClient.fallback_retry_wait

    @staticmethod
    def request(method: str, url: str, *, headers: dict | None = None, body: dict | None = None) -> dict:
        data = None
        hdrs = dict(headers or {})
        hdrs.setdefault("User-Agent", f"dc-py/{DC_API_VERSION}")
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")

        # Outer retry loop — re-attempts on 429 only. All other errors and
        # successes fall through to a single response.
        attempt = 0
        while True:
            req = urlrequest.Request(url, data=data, headers=hdrs, method=method.upper())
            status: int | None = None
            resp_headers: dict = {}
            raw: str = "{}"
            try:
                with urlrequest.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8") or "{}"
                    resp_headers = dict(resp.headers)
                    status = resp.status
            except urlerror.HTTPError as e:
                status = e.code
                try:
                    resp_headers = dict(e.headers or {})
                except Exception:
                    resp_headers = {}
                try:
                    raw = e.read().decode("utf-8") or "{}"
                except Exception:
                    raw = "{}"
            except urlerror.URLError as e:
                raise DCError(f"Network error contacting {url}: {e.reason}")

            # Always notify the version-tracker — works on success and error
            server_version = resp_headers.get("X-API-Version") or resp_headers.get("x-api-version")
            if HttpClient._on_server_version and server_version:
                HttpClient._on_server_version(server_version)

            # Parse the body (best-effort)
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                if status is not None and status >= 400:
                    return {"ok": False, "error": "http_error",
                            "message": f"HTTP {status}: {raw[:200]}"}
                raise DCError(f"Non-JSON response from {url}: {raw[:200]}")

            # Retry on 429 if budget allows
            if status == 429 and attempt < HttpClient.max_retries:
                wait = min(HttpClient._parse_retry_seconds(resp_headers, body=payload),
                           HttpClient.max_retry_wait)
                attempt += 1
                Runtime.emit(
                    f"Rate limited (HTTP 429) — waiting {wait}s before retry "
                    f"{attempt}/{HttpClient.max_retries}..."
                )
                import time as _time
                _time.sleep(wait)
                continue

            return payload

    @staticmethod
    def get(url, **kw):    return HttpClient.request("GET",    url, **kw)
    @staticmethod
    def post(url, **kw):   return HttpClient.request("POST",   url, **kw)
    @staticmethod
    def patch(url, **kw):  return HttpClient.request("PATCH",  url, **kw)
    @staticmethod
    def delete(url, **kw): return HttpClient.request("DELETE", url, **kw)


# ── Version mismatch warning ───────────────────────────────────────────

class _VersionTracker:
    """Compare the server's X-API-Version against DC_API_VERSION; emit a
    one-shot stderr warning when the server has new features.

    Rules:
    - Major or minor bump on the server → warn (this client is behind)
    - Patch-only bump → silent (per-version-strategy: patch is bug fix)
    - Server version older than client → silent (we don't tell the user
      to downgrade — they're running newer client; that's fine)
    - Warning fires once per process to avoid spamming script users
    """

    _warned = False

    @staticmethod
    def _parse(version: str) -> tuple[int, int, int] | None:
        try:
            parts = version.strip().split(".")
            if len(parts) < 2:
                return None
            major = int(parts[0])
            minor = int(parts[1])
            patch = int(parts[2]) if len(parts) >= 3 else 0
            return major, minor, patch
        except (ValueError, AttributeError):
            return None

    @classmethod
    def observe(cls, server_version: str) -> None:
        if cls._warned:
            return
        server = cls._parse(server_version)
        client = cls._parse(DC_API_VERSION)
        if not server or not client:
            return
        # Major or minor newer on server → client is behind on features
        if server[0] > client[0] or (server[0] == client[0] and server[1] > client[1]):
            cls._warned = True
            print(
                f"\n⚠  DC API has new features available "
                f"(server {server_version}, this client built for {DC_API_VERSION}).\n"
                f"   Update the dc client: cd <your dc clone> && git pull\n",
                file=sys.stderr,
            )

    @classmethod
    def attach(cls) -> None:
        """Wire HttpClient → version-tracker observer. Call once at startup."""
        HttpClient._on_server_version = cls.observe


# ── Runtime base class ───────────────────────────────────────────────────

class Result:
    """Wraps a command's return value alongside any text emitted during the call.

    Behaves transparently like the underlying ``data`` for callers that don't
    care about emit — delegates iteration, indexing, length, bool, and
    dict-style access to ``self.data``. The ``emitted`` attribute holds any
    text produced via ``Runtime.emit()`` during command execution.

    Callers that don't care about emit simply use the object as if it were
    the raw result (`result["userID"]`, `for item in result["items"]:`, etc.).
    Callers that want the emit log access ``result.emitted``.
    """

    __slots__ = ("data", "emitted")

    def __init__(self, data, emitted: str = ""):
        self.data = data
        self.emitted = emitted

    # Transparent delegation -------------------------------------------------
    def __getitem__(self, key):     return self.data[key]
    def __setitem__(self, k, v):    self.data[k] = v
    def __contains__(self, item):   return item in self.data
    def __iter__(self):             return iter(self.data)
    def __len__(self):              return len(self.data)
    def __bool__(self):             return bool(self.data)
    def __eq__(self, other):        return self.data == (other.data if isinstance(other, Result) else other)

    def get(self, key, default=None):
        if isinstance(self.data, dict):
            return self.data.get(key, default)
        raise AttributeError(f"'{type(self.data).__name__}' has no attribute 'get'")

    def keys(self):
        if isinstance(self.data, dict):
            return self.data.keys()
        raise AttributeError(f"'{type(self.data).__name__}' has no attribute 'keys'")

    def values(self):
        if isinstance(self.data, dict):
            return self.data.values()
        raise AttributeError(f"'{type(self.data).__name__}' has no attribute 'values'")

    def items(self):
        if isinstance(self.data, dict):
            return self.data.items()
        raise AttributeError(f"'{type(self.data).__name__}' has no attribute 'items'")

    def __repr__(self):
        return f"Result(data={self.data!r}, emitted={self.emitted!r})"

    def __str__(self):
        return str(self.data) if self.data is not None else ""


class Runtime:
    """Lightweight base class — env loading, command registration, dispatch."""

    def __init__(self, name: str, source_file: str):
        self.name = name
        self.source_file = source_file
        self.env_path = _env_file_path(source_file)
        _load_dotenv(self.env_path)
        self.api_url: str | None = None
        self._commands: dict = {}

    # ── Emit ─────────────────────────────────────────────────────────
    #
    # Skills call `self.emit("instruction text")` during command
    # execution to send follow-up guidance back to the calling agent.
    # When a sink is registered (set by `_invoke()` for the duration of
    # each command), emitted text lands in the buffer instead of stdout.
    # When no sink is registered, `emit()` falls back to `print(...)` so
    # it is always safe to call.
    #
    # The dispatcher decides where to surface buffered emit:
    #   - CLI:  prints to stderr after the formatted result
    #   - MCP:  appended as a second TextContent item with an "📣 emit:" prefix
    #   - Python import: returned on `result.emitted` when wrapping is enabled

    @staticmethod
    def emit(*args, sep: str = " ", end: str = "\n", file=None, flush: bool = False) -> None:
        """Send follow-up text — or structured JSON — to the calling agent.

        Mirrors `print(...)` for plain text use, with one extra trick: any
        dict/list argument is auto-serialized as pretty-printed JSON. So both
        of these work:

            self.emit("Trip created. Run `dc trips` to see it.")
            self.emit({"hint": "next-step", "command": "trips"})

        Routed through the active emit sink when one is registered (during
        command dispatch), or passes through to `print(...)` when no sink is
        set — making `emit()` always safe to call.
        """
        rendered_parts: list[str] = []
        for arg in args:
            if isinstance(arg, (dict, list, tuple)):
                rendered_parts.append(json.dumps(arg, indent=2, ensure_ascii=False, default=str))
            else:
                rendered_parts.append(str(arg))

        sink = _EMIT_SINK.get()
        target = sys.stdout if file is None else file
        if sink is not None and target is sys.stdout:
            sink(sep.join(rendered_parts) + end)
            return
        print(*rendered_parts, sep=sep, end=end, file=file, flush=flush)

    def _discover_commands(self) -> dict:
        commands: dict = {}
        for attr in dir(self):
            if attr.startswith("_"):
                continue
            try:
                fn = getattr(self, attr)
            except AttributeError:
                continue
            meta = getattr(fn, "_skill_command", None)
            if meta:
                commands[meta["name"]] = {**meta, "fn": fn}
        return commands

    def require_env(self, key: str) -> str:
        value = os.environ.get(key)
        if not value:
            raise DCError(
                f"Missing required environment variable: {key}\n"
                f"Run: python3 {Path(self.source_file).name} setup --api-key dk_<api-key>"
            )
        return value

    def set_env(self, key: str, value: str) -> None:
        """Persist an env var to the .env file at the repo root."""
        _write_dotenv_value(self.env_path, key, value)
        os.environ[key] = value

    # ── Output formatting ────────────────────────────────────────────

    @staticmethod
    def _format_output(result, fmt: str, *, command_name: str = "", emitted: str = "") -> str:
        """Render a result for stdout in the requested format.

        Accepts either a raw value or a `Result` — extracts `.data`
        before serializing. When `--json` is requested AND emit text was
        captured, wraps the response in a structured envelope so the agent
        can see both the data and the follow-up instructions.
        """
        data = result.data if isinstance(result, Result) else result

        if fmt == "json":
            if emitted:
                payload = {
                    "ok":      True,
                    "client": "dc",
                    "command": command_name,
                    "result":  data,
                    "emitted": emitted,
                }
                return json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            return json.dumps(data, indent=2, ensure_ascii=False, default=str)

        if fmt == "python":
            return repr(data)

        if isinstance(data, (dict, list)):
            return json.dumps(data, indent=2, ensure_ascii=False, default=str)
        return str(data)

    # ── Built-ins ────────────────────────────────────────────────────

    def _builtin_help(self, command: str | None = None) -> str:
        if command and command in self._commands:
            cmd = self._commands[command]
            return f"{cmd['name']}\n  {cmd['help']}"
        lines = [f"{self.name} — commands:\n"]
        width = max((len(n) for n in self._commands), default=20)
        for name in sorted(self._commands):
            cmd = self._commands[name]
            lines.append(f"  {name:{width}}  {cmd['help']}")
        lines.append("")
        lines.append("Built-ins:")
        lines.append(f"  {'help [command]':{width}}  Show this help (or details for one command)")
        lines.append(f"  {'docs [command]':{width}}  Alias for help")
        lines.append("")
        lines.append("Global flags (before or after command):")
        lines.append(f"  {'--format text|json|python':{width}}  Output format (default: text)")
        lines.append(f"  {'--json':{width}}  Shortcut for --format json")
        lines.append(f"  {'--python':{width}}  Shortcut for --format python")
        lines.append(f"  {'--api-url <url>':{width}}  Override the API base URL")
        lines.append(f"  {'--help, -h':{width}}  Show help")
        return "\n".join(lines)

    # ── Dispatch ─────────────────────────────────────────────────────

    def dispatch(self, argv=None) -> int:
        argv = list(sys.argv[1:] if argv is None else argv)
        fmt = "text"

        cleaned: list = []
        i = 0
        while i < len(argv):
            tok = argv[i]
            if tok in ("--help", "-h"):
                rest = argv[i + 1:] if i + 1 < len(argv) else []
                target = rest[0] if rest else None
                print(self._builtin_help(target))
                return 0
            if tok == "--json":
                fmt = "json"; i += 1; continue
            if tok == "--python":
                fmt = "python"; i += 1; continue
            if tok == "--format":
                fmt = argv[i + 1] if i + 1 < len(argv) else "text"
                i += 2; continue
            if tok == "--api-url":
                self.api_url = argv[i + 1] if i + 1 < len(argv) else None
                i += 2; continue
            cleaned.append(tok); i += 1
        argv = cleaned

        if not argv:
            print(self._builtin_help())
            return 0

        cmd_name, rest = argv[0], argv[1:]

        if cmd_name in ("help", "docs"):
            target = rest[0] if rest else None
            print(self._builtin_help(target))
            return 0

        cmd = self._commands.get(cmd_name)
        if not cmd:
            print(f"Unknown command: {cmd_name}\n", file=sys.stderr)
            print(self._builtin_help(), file=sys.stderr)
            return 2

        try:
            result = self._invoke(cmd, rest)
        except UsageError as e:
            print(f"Usage: {e}", file=sys.stderr)
            return 2
        except DCError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        # `_invoke` always returns a Result; extract emit text for
        # the chosen format. In JSON mode, emit is folded into the envelope
        # by `_format_output`. In text/python mode, we print emit to stderr
        # AFTER the result so it doesn't pollute pipelines.
        emitted = result.emitted if isinstance(result, Result) else ""
        data = result.data if isinstance(result, Result) else result

        if data is not None:
            print(self._format_output(result, fmt, command_name=cmd_name, emitted=emitted))

        if emitted and fmt != "json":
            print(emitted, file=sys.stderr)

        return 0

    def _invoke(self, cmd: dict, raw_args: list) -> "Result":
        """Run a command with an emit sink installed; return a Result.

        Captures any `self.emit(...)` calls made during execution and
        attaches the joined text to the result as `.emitted`. Callers that
        don't care about emit can use `result.data` (or the result directly,
        thanks to the proxy methods on `Result`).
        """
        fn = cmd["fn"]
        parser = cmd.get("parser")

        emit_chunks: list[str] = []
        token = _EMIT_SINK.set(emit_chunks.append)
        try:
            if parser is not None:
                args, kwargs = parser(raw_args)
                raw = fn(*args, **kwargs)
            else:
                sig = inspect.signature(fn)
                params = [p for p in sig.parameters.values() if p.name != "self"]
                positionals, flags = ArgHelpers.parse_flags(list(raw_args))
                if flags:
                    raise UsageError(
                        f"Command '{cmd['name']}' does not accept flags. Got: {sorted(flags)}"
                    )
                if len(positionals) > len(params):
                    raise UsageError(
                        f"Command '{cmd['name']}' takes at most {len(params)} args; got {len(positionals)}"
                    )
                raw = fn(*positionals)
        finally:
            _EMIT_SINK.reset(token)

        emitted = "".join(emit_chunks).rstrip("\n")

        # Don't double-wrap: if a command already returned a Result,
        # merge its emit text with anything we captured.
        if isinstance(raw, Result):
            combined = "\n".join(filter(None, [raw.emitted, emitted]))
            return Result(raw.data, combined)
        return Result(raw, emitted)


# ════════════════════════════════════════════════════════════════════════
#  DC Member API client
# ════════════════════════════════════════════════════════════════════════


class _DCCore:
    """Private helper class — wraps HTTP calls to the DC Member API."""

    DEFAULT_API_URL = "https://api.dynamitecircle.com"

    # ── CLI arg parsers (registered via parser= on @skill_command) ──

    @staticmethod
    def _truthy(value) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}

    @staticmethod
    def _parse_paginated(raw_args, *, default_limit=50, extra_flags=()):
        pag, rest = ArgHelpers.parse_pagination(list(raw_args), defaults={"limit": default_limit})
        positionals, flags = ArgHelpers.parse_flags(list(rest))
        kwargs: dict = {"limit": pag["limit"], "cursor": pag["cursor"]}
        for flag in extra_flags:
            if flag in flags:
                value = flags[flag]
                if flag == "past":
                    kwargs["past"] = _DCCore._truthy(value)
                elif flag == "type":
                    kwargs["room_type"] = str(value).strip()
                else:
                    kwargs[flag.replace("-", "_")] = str(value).strip()
        return tuple(positionals), kwargs

    @staticmethod
    def _parse_list_args(raw_args):
        return _DCCore._parse_paginated(
            raw_args,
            extra_flags=("past", "status", "type", "sections", "q"),
        )

    @staticmethod
    def _parse_id_with_limit(raw_args):
        return _DCCore._parse_paginated(raw_args)

    @staticmethod
    def _parse_trip_create(raw_args):
        positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        kwargs: dict = {}
        if "start-date" in flags: kwargs["start_date"] = str(flags["start-date"]).strip()
        if "end-date"   in flags: kwargs["end_date"]   = str(flags["end-date"]).strip()
        if "place-id"   in flags: kwargs["place_id"]   = str(flags["place-id"]).strip()
        if "event-id"   in flags: kwargs["event_id"]   = str(flags["event-id"]).strip()
        return tuple(positionals), kwargs

    @staticmethod
    def _parse_trip_update(raw_args):
        return _DCCore._parse_trip_create(raw_args)

    @staticmethod
    def _parse_rsvp(raw_args):
        positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        kwargs: dict = {}
        if "status" in flags:
            kwargs["status"] = str(flags["status"]).strip()
        return tuple(positionals), kwargs

    @staticmethod
    def _parse_invite(raw_args):
        positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        kwargs: dict = {}
        if "email"     in flags: kwargs["email"]     = str(flags["email"]).strip()
        if "full-name" in flags: kwargs["full_name"] = str(flags["full-name"]).strip()
        return tuple(positionals), kwargs

    @staticmethod
    def _parse_profile_patch(raw_args):
        _positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        return tuple(), {"fields": flags}

    @staticmethod
    def _parse_notifications_patch(raw_args):
        """Parse `--cat-<category>-<channel>` flags into the nested PATCH shape."""
        _positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        cats: dict = {}
        for k, v in flags.items():
            sv = str(v).strip().lower()
            if sv in ("true", "1", "yes"):
                bv = True
            elif sv in ("false", "0", "no"):
                bv = False
            else:
                raise UsageError(f"--{k} expects true|false (got {v!r})")
            if not k.startswith("cat-"):
                raise UsageError(
                    f"Unknown flag --{k}. Use --cat-<category>-<push|email>."
                )
            rest = k[len("cat-"):]
            if "-" not in rest:
                raise UsageError(f"--cat-{rest} must be of form --cat-<category>-<channel>")
            category, channel = rest.rsplit("-", 1)
            if channel not in ("push", "email"):
                raise UsageError(f"--cat-{category}-{channel} must end with -push or -email")
            cats.setdefault(category, {})[channel] = bv
        return tuple(), {"fields": {"categories": cats} if cats else {}}

    @staticmethod
    def _parse_locator_settings_patch(raw_args):
        """Parse boolean flags --enabled / --events / --tickets / --trips."""
        _positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        allowed = {"enabled", "events", "tickets", "trips"}
        out: dict = {}
        for k, v in flags.items():
            if k not in allowed:
                raise UsageError(
                    f"Unknown flag --{k}. Allowed: --enabled, --events, --tickets, --trips."
                )
            sv = str(v).strip().lower()
            if sv in ("true", "1", "yes"):
                out[k] = True
            elif sv in ("false", "0", "no"):
                out[k] = False
            else:
                raise UsageError(f"--{k} expects true|false (got {v!r})")
        return tuple(), {"fields": out}

    @staticmethod
    def _parse_calendar_patch(raw_args):
        """Parse boolean --include* flags into the calendar PATCH body."""
        _positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        out: dict = {}
        for k, v in flags.items():
            sv = str(v).strip().lower()
            if sv in ("true", "1", "yes"):
                out[k] = True
            elif sv in ("false", "0", "no"):
                out[k] = False
            else:
                raise UsageError(f"--{k} expects true|false (got {v!r})")
        return tuple(), {"fields": out}

    @staticmethod
    def _parse_report_issue(raw_args):
        positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        kwargs: dict = {}
        if "text"       in flags: kwargs["text"]       = str(flags["text"])
        if "severity"   in flags: kwargs["severity"]   = str(flags["severity"]).strip()
        if "screenshot" in flags: kwargs["screenshot"] = str(flags["screenshot"]).strip()
        if "context"    in flags:
            ctx_raw = str(flags["context"]).strip()
            if ctx_raw:
                try:
                    parsed = json.loads(ctx_raw)
                except json.JSONDecodeError as e:
                    raise UsageError(f"--context must be valid JSON: {e}") from e
                if not isinstance(parsed, dict):
                    raise UsageError("--context must be a JSON object (e.g. '{\"key\":\"value\"}').")
                kwargs["context"] = parsed
        return tuple(positionals), kwargs

    @staticmethod
    def _parse_places_search(raw_args):
        positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        kwargs: dict = {}
        if "q"     in flags: kwargs["q"]     = str(flags["q"]).strip()
        if "limit" in flags: kwargs["limit"] = ArgHelpers.parse_int(flags["limit"], name="limit")
        return tuple(positionals), kwargs

    @staticmethod
    def _parse_setup(raw_args):
        positionals, flags = ArgHelpers.parse_flags(list(raw_args))
        kwargs: dict = {}
        if "api-key" in flags:
            kwargs["api_key"] = str(flags["api-key"]).strip()
        elif positionals:
            kwargs["api_key"] = positionals[0]
        return tuple(), kwargs

    # ── Init / HTTP plumbing ────────────────────────────────────────

    def __init__(self, runtime: Runtime):
        self._runtime = runtime

    @property
    def _api_url(self) -> str:
        return self._runtime.api_url or self.DEFAULT_API_URL

    def _api_key(self) -> str:
        key = self._runtime.require_env("DC_API_KEY")
        if not key.startswith("dk_"):
            raise DCError(
                "DC_API_KEY must start with 'dk_'. "
                "Generate one from your DC profile dropdown → DC Member API Key."
            )
        return key

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Accept":        "application/json",
        }

    def _build_url(self, path: str, params: dict | None = None) -> str:
        url = f"{self._api_url}{path}"
        if params:
            qs = urlencode({k: v for k, v in params.items() if v is not None and v != ""})
            if qs:
                url = f"{url}?{qs}"
        return url

    def _get(self, path, params=None):
        return self._unwrap(HttpClient.get(self._build_url(path, params), headers=self._headers()))

    def _post(self, path, body=None):
        return self._unwrap(HttpClient.post(self._build_url(path), headers=self._headers(), body=body or {}))

    def _patch(self, path, body=None):
        return self._unwrap(HttpClient.patch(self._build_url(path), headers=self._headers(), body=body or {}))

    def _delete(self, path):
        return self._unwrap(HttpClient.delete(self._build_url(path), headers=self._headers()))

    @staticmethod
    def _unwrap(result) -> dict:
        if not isinstance(result, dict):
            raise DCError(f"Unexpected response: {result!r}")
        if result.get("ok") is True:
            return result.get("data") or {}
        error = result.get("error") or "unknown_error"
        message = result.get("message") or ""
        raise DCError(f"{error}: {message}")

    @staticmethod
    def _wrap_list(api_data: dict, items_field: str, *, extra=None) -> dict:
        items = api_data.get(items_field) or []
        cursor = api_data.get("nextCursor")
        envelope = ArgHelpers.envelope(items, cursor=cursor)
        passthrough = {
            k: v for k, v in api_data.items()
            if k not in {items_field, "nextCursor"}
        }
        if passthrough:
            envelope["extra"] = passthrough
        if extra:
            envelope.setdefault("extra", {}).update(extra)
        return envelope

    # ── Setup ───────────────────────────────────────────────────────

    def setup(self, api_key: str = "") -> dict:
        if not api_key:
            raise UsageError("setup requires --api-key dk_<api-key>")
        if not api_key.startswith("dk_"):
            raise DCError("API key must start with 'dk_'.")
        self._runtime.set_env("DC_API_KEY", api_key)

        # Heads up for Windows users — Unix-style chmod 600 is a no-op there,
        # so the file relies on the user's home-dir permissions instead.
        if sys.platform == "win32":
            Runtime.emit(
                "Note: file permissions can't be tightened on Windows the way "
                "they can on Unix. .env.dc inherits NTFS perms from its parent "
                "directory — make sure your repo isn't on a shared drive."
            )

        Runtime.emit("Next: run `self-test` to verify the connection.")
        return {
            "ok":      True,
            "message": f"Saved DC_API_KEY to {self._runtime.env_path}",
            "envFile": str(self._runtime.env_path),
        }

    # ── Self-test ──────────────────────────────────────────────────

    def self_test(self) -> dict:
        """Validate env, network, and /profile end-to-end."""
        checks: list = []

        # 1. Env present
        api_key = os.environ.get("DC_API_KEY")
        if not api_key:
            checks.append({"step": "env", "ok": False, "message": "DC_API_KEY not set — run `setup --api-key dk_...`"})
            return {"ok": False, "checks": checks}
        checks.append({"step": "env", "ok": True, "message": f"DC_API_KEY loaded from {self._runtime.env_path}"})

        # 2. Key shape
        if not api_key.startswith("dk_"):
            checks.append({"step": "keyShape", "ok": False, "message": "DC_API_KEY must start with 'dk_'"})
            return {"ok": False, "checks": checks}
        parts = api_key.split("_", 2)
        expected_user_id = parts[1] if len(parts) >= 3 else None
        checks.append({"step": "keyShape", "ok": True,
                       "message": f"Key prefix valid (expected userID: {expected_user_id or 'unknown'})"})

        # 3. Network + profile
        try:
            profile = self.profile()
        except DCError as e:
            checks.append({"step": "profile", "ok": False, "message": str(e)})
            return {"ok": False, "checks": checks}

        if not isinstance(profile, dict) or not profile.get("userID"):
            checks.append({"step": "profile", "ok": False, "message": "Profile response missing userID"})
            return {"ok": False, "checks": checks}

        actual_user_id = profile.get("userID")
        if expected_user_id and actual_user_id != expected_user_id:
            checks.append({"step": "profile", "ok": False,
                           "message": f"userID mismatch — key prefix says {expected_user_id}, profile says {actual_user_id}"})
            return {"ok": False, "checks": checks}

        display = profile.get("displayName") or profile.get("userName") or ""
        checks.append({"step": "profile", "ok": True,
                       "message": f"connected as userID[{actual_user_id}] {display}"})

        # 4. MCP schema coverage — every @skill_command must declare an
        # explicit `args=` (even if empty) so MCP clients see a typed schema
        # instead of the catch-all `additionalProperties: true` fallback.
        # Commands without `args=` get flagged as missing.
        commands = self._runtime._commands
        missing_schema = [
            name for name, cmd in commands.items()
            if cmd.get("args") is None
        ]
        if missing_schema:
            checks.append({
                "step":    "mcpSchemas",
                "ok":      False,
                "message": f"{len(missing_schema)} command(s) missing args= schema: "
                           f"{', '.join(sorted(missing_schema))}",
            })
            return {"ok": False, "userID": actual_user_id, "displayName": display, "checks": checks}
        checks.append({
            "step":    "mcpSchemas",
            "ok":      True,
            "message": f"All {len(commands)} commands declare args= schemas",
        })

        return {
            "ok":          True,
            "userID":      actual_user_id,
            "displayName": display,
            "checks":      checks,
        }

    # ── Profile ─────────────────────────────────────────────────────

    def profile(self):
        return self._get("/profile")

    def update_profile(self, fields: dict):
        if not fields:
            raise UsageError("profile-update requires at least one --<field> <value>")
        return self._patch("/profile", fields)

    def limits(self):
        """Effective rate limits + current usage for this API key.

        Returns the same numbers exposed via the X-RateLimit-* response
        headers, in JSON form. Useful for clients that want a single
        snapshot rather than parsing headers on every call.
        """
        return self._get("/limits")

    # ── Membership ──────────────────────────────────────────────────

    def membership(self):
        """Your full membership state — role, lifecycle, trial, billing.

        Returns role label/key, joined date, DC BLACK status, trial
        info, and full billing details (status, plan, current period,
        next billing date, amounts, manage-billing URL). Use this when
        you need to know whether the member is active, on trial, or
        when their next charge is.
        """
        return self._get("/membership")

    def membership_invoices(self, limit=20):
        """Your Stripe invoices (newest first) with hosted URL + PDF.

        Returns an empty list for legacy paypal/chargify members or
        members with no Stripe customer record.
        """
        return self._get("/membership/invoices", {"limit": limit})

    # ── Notifications ───────────────────────────────────────────────

    def notifications(self):
        """Read your push/email preferences per notification category."""
        return self._get("/notifications")

    def update_notifications(self, fields: dict):
        """Update notification preferences. Pass a `categories` dict:

            {"categories": {
                "announcement": {"email": False},
                "reaction":     {"push": True}
            }}
        """
        if not fields:
            raise UsageError("notifications-update requires at least one field")
        return self._patch("/notifications", fields)

    # ── Locator (Friday email) ──────────────────────────────────────

    def locator_settings(self):
        """Read your Friday locator email digest toggles."""
        return self._get("/locator/settings")

    def update_locator_settings(self, fields: dict):
        """Update Friday locator email toggles. Any subset of:
        enabled, events, tickets, trips.
        """
        if not fields:
            raise UsageError("locator-settings-update requires at least one field")
        return self._patch("/locator/settings", fields)

    # ── Calendar ────────────────────────────────────────────────────

    def calendar(self):
        """Your iCalendar feed URLs + the 9 feed-content toggles."""
        return self._get("/calendar")

    def update_calendar(self, fields: dict):
        """Update calendar feed toggles. Any subset of:
        includeMyTickets, includeEventAgenda, includeVirtualCalls,
        includeMyTrips, includeFlagshipEvents, includeDCBlackEvents,
        includeHomeChapterEvents, includeFollowedChapterEvents,
        includeOtherChapterEvents.
        """
        if not fields:
            raise UsageError("calendar-update requires at least one field")
        return self._patch("/calendar", fields)

    # ── Report Issue ────────────────────────────────────────────────

    @staticmethod
    def _encode_screenshot(value) -> str:
        """Normalize a screenshot input to a base64 string.

        Accepts:
          - bytes: raw image bytes (e.g. from PIL or a screenshot lib)
          - str: a filesystem path, a `data:image/...;base64,...` URL,
            or an already-encoded base64 string

        Returns the base64-encoded string the API expects. Raises
        UsageError on unsupported extensions or oversize files.
        """
        max_bytes = 4 * 1024 * 1024  # mirror server cap

        # bytes → base64
        if isinstance(value, (bytes, bytearray)):
            if len(value) > max_bytes:
                raise UsageError(
                    f"Screenshot too large ({len(value) / 1024 / 1024:.1f} MB). Max 4 MB."
                )
            return base64.b64encode(bytes(value)).decode("ascii")

        if not isinstance(value, str):
            raise UsageError(
                "screenshot must be a file path, base64 string, or bytes."
            )

        s = value.strip()
        if not s:
            raise UsageError("screenshot is empty.")

        # Already a data URL — pass through; server strips the prefix.
        if s.startswith("data:image/"):
            return s

        # Looks like a file path? Read it.
        candidate = Path(os.path.expanduser(s))
        if candidate.is_file():
            ext = candidate.suffix.lower().lstrip(".")
            if ext not in {"png", "jpg", "jpeg", "webp"}:
                raise UsageError(
                    f"Unsupported screenshot type: .{ext}. Use png, jpg, jpeg, or webp."
                )
            data = candidate.read_bytes()
            if len(data) > max_bytes:
                raise UsageError(
                    f"Screenshot too large ({len(data) / 1024 / 1024:.1f} MB). Max 4 MB."
                )
            return base64.b64encode(data).decode("ascii")

        # Otherwise assume it's already a base64 string.
        return s

    def report_issue(self, text="", severity="bug", screenshot=None, context=None):
        """Submit a bug report, feedback, or question to the DC team.

        Args:
            text: Description of the issue (required, 1-4000 chars).
            severity: One of "bug", "feedback", "question". Defaults to "bug".
            screenshot: Optional. File path, base64 string, data URL, or raw bytes.
                The helper handles encoding automatically. PNG/JPEG/WebP only,
                max 4 MB raw.
            context: Optional dict of debug context — anything useful for
                triage (last error, request payload, endpoint, etc.).

        **Privacy note:** Screenshots and report text go to the DC team
        unredacted. Don't include passwords, payment details, or secrets.
        """
        if not text:
            raise UsageError("report-issue requires --text")
        if severity not in ("bug", "feedback", "question"):
            raise UsageError(
                f"--severity must be one of: bug, feedback, question (got: {severity!r})"
            )
        body: dict = {"text": text, "severity": severity}
        if screenshot is not None:
            body["screenshot"] = self._encode_screenshot(screenshot)
        if context:
            if not isinstance(context, dict):
                raise UsageError("--context must be a JSON object.")
            body["context"] = context
        result = self._post("/report-issue", body)
        Runtime.emit(
            "Issue reported. The DC team has been notified."
        )
        return result

    # ── Announcements ───────────────────────────────────────────────

    def announcements(self, limit=10, cursor=None):
        """Recent announcements from DC's broadcast channels (mixed feed)."""
        return self._get("/announcements", {
            "cursor": cursor or None,
            "limit":  limit,
        })

    def announcements_latest(self):
        """One most-recent announcement per visible channel (quick overview)."""
        return self._get("/announcements/latest")

    # ── Event extras (schedule / agenda / meetups / sponsors) ───────

    def event_schedule(self, event_id):
        """Full schedule (sessions, day-grouped) for an event you have a ticket to.

        Time fields are wall-clock ISO strings paired with `timezone` (IANA) —
        the digits are venue-local, not real UTC. See the API docs for details.
        """
        if not event_id:
            raise UsageError("event-schedule requires an event ID")
        return self._get(f"/events/{event_id}/schedule")

    def event_agenda(self, event_id, user_id=None):
        """Sessions and meetups on the agenda for an event.

        With no user_id (default): returns YOUR agenda.
        With user_id: returns another attendee's agenda — useful when
        AI agents want to plan together (find a coffee window with a
        DCer, suggest sessions to overlap, etc.). Both you and the
        target must hold a valid ticket to the event.
        """
        if not event_id:
            raise UsageError("event-agenda requires an event ID")
        if user_id:
            return self._get(f"/events/{event_id}/agenda/{user_id}")
        return self._get(f"/events/{event_id}/agenda")

    def event_agendas(self, event_id, user_ids):
        """Bulk fetch agendas for up to 20 attendees in one call.

        Cheaper than fanning out N requests when an LLM compares
        schedules across several DCers ("what sessions are Lina,
        Alex, and Jeff all attending?"). Non-attendee userIDs are
        silently dropped — pass a candidate list without pre-checking
        each ticket. You must hold a ticket to the event.
        """
        if not event_id:
            raise UsageError("event-agendas requires an event ID")
        ids = user_ids if isinstance(user_ids, list) else [s.strip() for s in str(user_ids).split(",") if s.strip()]
        if not ids:
            raise UsageError("event-agendas requires at least one userID")
        if len(ids) > 20:
            raise UsageError("event-agendas accepts at most 20 userIDs per call")
        return self._get(f"/events/{event_id}/agendas", {"userIDs": ",".join(ids)})

    def event_free_slots(self, event_id, user_ids, min_duration_mins=30, within_day_date=None):
        """Compute shared free time slots across event attendees.

        Returns the windows where the given attendees are NOT in a
        bookmarked session or meetup. Use to find a coffee window
        with one DCer or a junto-style lunch slot for a group. Slots
        are ranked by overlap (most-shared first). Non-attendee IDs
        silently dropped. Wall-clock ISO out, paired with the event's
        IANA timezone.
        """
        if not event_id:
            raise UsageError("event-free-slots requires an event ID")
        ids = user_ids if isinstance(user_ids, list) else [s.strip() for s in str(user_ids).split(",") if s.strip()]
        if not ids:
            raise UsageError("event-free-slots requires at least one userID")
        if len(ids) > 20:
            raise UsageError("event-free-slots accepts at most 20 userIDs per call")
        body = {
            "userIDs":         ids,
            "minDurationMins": int(min_duration_mins),
        }
        if within_day_date:
            body["withinDayDate"] = within_day_date
        return self._post(f"/events/{event_id}/free-slots", body)

    def profile_match(self, query=None, limit=50, location_chapter_place_id=None,
                      location_current_place_id=None, event_id=None, is_dcb=None,
                      industry=None, min_team_size=None, min_revenue=None,
                      gender=None, no_rerank=None):
        """Match DCers against a description, or recommend if no query.

        With `query`: free-form description ("DCers in Lisbon who run SaaS").
        Without `query`: server uses your own profile to recommend "DCers
        you should meet". Useful for cold-start "who should I message?"

        Optional filters (compose with AND):
            location_chapter_place_id  — DCers based here (Google Place ID)
            location_current_place_id  — DCers currently here
            event_id                   — DCers attending this event
            is_dcb                     — DC BLACK members only
            industry                   — exact match on PrimaryBusinessIndustry
                                         (e.g. "SaaS & Tech")
            min_team_size              — "at least this size" (e.g. "10-14");
                                         only DCers who set TeamSizePrivacy
                                         to "all DCers" are matched.
            min_revenue                — "at least this revenue" (e.g. "$1M+");
                                         only DCers who set AnnualRevenuePrivacy
                                         to "all DCers" are matched.
            gender                     — exact match. "Man" | "Woman" | "Non-binary".
                                         NOTE: Gender is sparsely populated —
                                         most DCers leave it blank.
            no_rerank                  — skip the keyword reranker and return
                                         results in raw vector-similarity order.

        Resolve place IDs via `places-search` first.

        Each result carries `score` (composite, sortable), `vectorScore` (pure
        semantic similarity 0..1), and `keywordScore` (raw keyword overlap, only
        when reranker ran). Limit cap 50.
        """
        body = {"limit": int(limit)}
        if query:
            body["query"] = query
        if location_chapter_place_id:
            body["locationChapterPlaceID"] = location_chapter_place_id
        if location_current_place_id:
            body["locationCurrentPlaceID"] = location_current_place_id
        if event_id:
            body["eventID"] = event_id
        if is_dcb is True:
            body["isDCB"] = True
        if industry:
            body["industry"] = industry
        if min_team_size:
            body["minTeamSize"] = min_team_size
        if min_revenue:
            body["minRevenue"] = min_revenue
        if gender:
            body["gender"] = gender
        if no_rerank is True:
            body["noRerank"] = True
        return self._post("/profile-match", body)

    def event_meetups(self, event_id):
        """Approved member-organized meetups for an event."""
        if not event_id:
            raise UsageError("event-meetups requires an event ID")
        return self._get(f"/events/{event_id}/meetups")

    def event_sponsors(self, event_id):
        """Sponsors for an event, ordered by tier then display order."""
        if not event_id:
            raise UsageError("event-sponsors requires an event ID")
        return self._get(f"/events/{event_id}/sponsors")

    def session_attendees(self, event_id, session_id):
        """Attendees who have bookmarked a specific session."""
        if not event_id or not session_id:
            raise UsageError("session-attendees requires <eventID> <sessionID>")
        return self._get(f"/events/{event_id}/schedule/{session_id}/attendees")

    def meetup_attendees(self, event_id, meetup_id):
        """Attendees who have RSVPd to a specific meetup."""
        if not event_id or not meetup_id:
            raise UsageError("meetup-attendees requires <eventID> <meetupID>")
        return self._get(f"/events/{event_id}/meetups/{meetup_id}/attendees")

    def session_bookmark(self, event_id, session_id, bookmarked=True):
        """Add or remove a session from your agenda. Requires an event ticket."""
        if not event_id or not session_id:
            raise UsageError("session-bookmark requires <eventID> <sessionID>")
        return self._post(f"/events/{event_id}/schedule/{session_id}/bookmark", {
            "bookmarked": bool(bookmarked),
        })

    def meetup_rsvp(self, event_id, meetup_id, joined=True):
        """Join or leave a meetup. Requires an event ticket."""
        if not event_id or not meetup_id:
            raise UsageError("meetup-rsvp requires <eventID> <meetupID>")
        return self._post(f"/events/{event_id}/meetups/{meetup_id}/rsvp", {
            "joined": bool(joined),
        })

    # ── Trips ───────────────────────────────────────────────────────

    def trips(self, past=False, limit=50, cursor=None):
        data = self._get("/trips", {
            "past":   "true" if past else None,
            "limit":  limit,
            "cursor": cursor or None,
        })
        return self._wrap_list(data, "trips")

    def trip(self, trip_id):
        """Get a single trip — points + enriched discovery block (top-10
        picks with mini profile + score, fullPool, whyToMeet AI paragraphs,
        overlapping trips, events in town).
        """
        if not trip_id:
            raise UsageError("trip requires a tripID")
        return self._get(f"/trips/{trip_id}")

    def trip_discovery(self, trip_id, include=None):
        """Discovery-only read for a trip. Optional `include` is a comma-
        separated subset of `people,fullPool,whyToMeet,events,overlappingTrips`
        (default = all). Useful when you just want the matchmaking signal
        without the trip body.
        """
        if not trip_id:
            raise UsageError("trip-discovery requires a tripID")
        params: dict = {}
        if include:
            params["include"] = include
        return self._get(f"/trips/{trip_id}/discovery", params or None)

    def trip_refresh(self, trip_id):
        """Owner-only: enqueue a background sync to regenerate this trip's
        discovery cache (recompute people, events, AI blurbs). Spammy
        triggers coalesce — the response is 202 immediately and the cache
        updates seconds later.
        """
        if not trip_id:
            raise UsageError("trip-refresh requires a tripID")
        return self._post(f"/trips/{trip_id}/refresh", {})

    def overlaps(self, limit=10, cursor=None):
        data = self._get("/trips/overlaps", {"limit": limit, "cursor": cursor or None})
        return self._wrap_list(data, "overlaps")

    def create_trip(self, start_date="", end_date="", place_id="", event_id="", points=None):
        if not start_date or not end_date:
            raise UsageError("trip-create requires --start-date and --end-date")
        if bool(place_id) == bool(event_id):
            raise UsageError("Provide exactly one of --place-id or --event-id (not both, not neither).")
        body: dict = {"startDate": start_date, "endDate": end_date}
        if place_id: body["placeID"] = place_id
        if event_id: body["eventID"] = event_id
        if points:   body["points"]  = points if isinstance(points, list) else [points]
        result = self._post("/trips", body)
        Runtime.emit("Trip created. Run `trips` to see your upcoming list, or `overlaps` to find DCers visiting at the same time.")
        return result

    def update_trip(self, trip_id, start_date="", end_date="", place_id="", event_id="", points=None):
        if not trip_id:
            raise UsageError("trip-update requires a tripID")
        body: dict = {}
        if start_date: body["startDate"] = start_date
        if end_date:   body["endDate"]   = end_date
        if place_id:   body["placeID"]   = place_id
        if event_id:   body["eventID"]   = event_id
        if points is not None:
            # `points` replaces the entire array. Pass [] to clear.
            body["points"] = points if isinstance(points, list) else [points]
        if not body:
            raise UsageError("trip-update requires at least one of --start-date, --end-date, --place-id, --event-id, --points")
        return self._patch(f"/trips/{trip_id}", body)

    def delete_trip(self, trip_id):
        if not trip_id:
            raise UsageError("trip-delete requires a tripID")
        return self._delete(f"/trips/{trip_id}")

    # ── Events ──────────────────────────────────────────────────────

    def events(self, past=False, limit=20, cursor=None):
        data = self._get("/events", {
            "past":   "true" if past else None,
            "limit":  limit,
            "cursor": cursor or None,
        })
        return self._wrap_list(data, "events")

    def event(self, event_id):
        return self._get(f"/events/{event_id}")

    def event_attendees(self, event_id, limit=100, cursor=None):
        data = self._get(f"/events/{event_id}/attendees", {"limit": limit, "cursor": cursor or None})
        return self._wrap_list(data, "attendees")

    def event_rsvp(self, event_id, status):
        if status not in ("yes", "maybe", "no"):
            raise UsageError("--status must be yes|maybe|no")
        result = self._post(f"/events/{event_id}/rsvp", {"status": status})
        if status == "yes":
            Runtime.emit(f"RSVP'd yes. Run `event {event_id}` for full details, or `event-attendees {event_id}` to see who else is coming.")
        return result

    # ── Virtual events ─────────────────────────────────────────────

    def virtual_events(self, past=False, limit=50, cursor=None):
        data = self._get("/virtual-events", {
            "past":   "true" if past else None,
            "limit":  limit,
            "cursor": cursor or None,
        })
        return self._wrap_list(data, "events")

    def virtual_event(self, session_id):
        return self._get(f"/virtual-events/{session_id}")

    def virtual_event_rsvp(self, session_id, status):
        if status not in ("yes", "maybe", "no"):
            raise UsageError("--status must be yes|maybe|no")
        return self._post(f"/virtual-events/{session_id}/rsvp", {"status": status})

    # ── Tickets ────────────────────────────────────────────────────

    def tickets(self, status="", limit=50, cursor=None):
        data = self._get("/tickets", {
            "status": status or None,
            "limit":  limit,
            "cursor": cursor or None,
        })
        return self._wrap_list(data, "tickets")

    # ── Invites ────────────────────────────────────────────────────

    def invites(self, limit=50, cursor=None):
        data = self._get("/invites", {"limit": limit, "cursor": cursor or None})
        return self._wrap_list(data, "invites")

    def permacode(self):
        return self._get("/invites/permacode")

    def create_invite(self, email="", full_name=""):
        if not email:     raise UsageError("invite-create requires --email")
        if not full_name: raise UsageError("invite-create requires --full-name")
        return self._post("/invites", {"email": email, "fullName": full_name})

    # ── Inbox ─────────────────────────────────────────────────────

    def inbox(self, limit=50, cursor=None):
        data = self._get("/inbox/unread", {"limit": limit, "cursor": cursor or None})
        items_field = "rooms" if "rooms" in data else "items"
        return self._wrap_list(data, items_field)

    # ── Rooms ─────────────────────────────────────────────────────

    def rooms(self, room_type="", limit=50, cursor=None):
        path = f"/rooms/inbox/{room_type}" if room_type else "/rooms"
        data = self._get(path, {
            "limit":  limit,
            "cursor": cursor or None,
        })
        return self._wrap_list(data, "rooms")

    def browse_rooms(self, room_type, limit=50, cursor=None):
        if not room_type:
            raise UsageError("browse-rooms requires a type (channel|discussion|activity)")
        data = self._get(f"/rooms/browse/{room_type}", {
            "limit":  limit,
            "cursor": cursor or None,
        })
        return self._wrap_list(data, "rooms")

    def room(self, room_id):
        if not room_id:
            raise UsageError("room requires a roomID")
        return self._get(f"/rooms/{room_id}")

    def room_messages(self, room_id, limit=50, before=None):
        if not room_id:
            raise UsageError("room-messages requires a roomID")
        data = self._get(f"/rooms/{room_id}/messages", {
            "limit":  limit,
            "before": before or None,
        })
        return self._wrap_list(data, "messages")

    def room_summary(self, room_id, summary_type):
        if not room_id:
            raise UsageError("room-summary requires a roomID")
        if summary_type not in ("daily", "weekly"):
            raise UsageError("room-summary requires --type daily or weekly")
        return self._get(f"/rooms/{room_id}/summary/{summary_type}")

    def room_summaries(self, room_id, summary_type, limit=20, cursor=None):
        if not room_id:
            raise UsageError("room-summaries requires a roomID")
        if summary_type not in ("daily", "weekly"):
            raise UsageError("room-summaries requires --type daily or weekly")
        data = self._get(f"/rooms/{room_id}/summaries/{summary_type}", {
            "limit":  limit,
            "cursor": cursor or None,
        })
        return self._wrap_list(data, "summaries")

    def _room_mutation(self, room_id, action):
        if not room_id:
            raise UsageError(f"room-{action} requires a roomID")
        return self._post(f"/rooms/{room_id}/{action}", {})

    def room_subscribe(self, room_id):
        return self._room_mutation(room_id, "subscribe")

    def room_unsubscribe(self, room_id):
        return self._room_mutation(room_id, "unsubscribe")

    def room_mute(self, room_id):
        return self._room_mutation(room_id, "mute")

    def room_unmute(self, room_id):
        return self._room_mutation(room_id, "unmute")

    def room_archive(self, room_id):
        return self._room_mutation(room_id, "archive")

    def room_unarchive(self, room_id):
        return self._room_mutation(room_id, "unarchive")

    def room_pin(self, room_id):
        return self._room_mutation(room_id, "pin")

    def room_unpin(self, room_id):
        return self._room_mutation(room_id, "unpin")

    # ── Chapters ──────────────────────────────────────────────────

    def chapters(self, limit=50, cursor=None):
        data = self._get("/chapters", {"limit": limit, "cursor": cursor or None})
        return self._wrap_list(data, "chapters")

    def chapter(self, city_id):
        if not city_id:
            raise UsageError("chapter requires a cityID (Google Place ID)")
        return self._get(f"/chapters/{city_id}")

    # ── Places ────────────────────────────────────────────────────

    def places_search(self, q="", limit=10):
        if not q:
            raise UsageError("places-search requires --q <query>")
        return self._get("/places/search", {"q": q, "limit": limit})

    def place(self, place_id):
        if not place_id:
            raise UsageError("place requires a placeID")
        return self._get(f"/places/{place_id}")

    # ── Locator ───────────────────────────────────────────────────

    def locator(self, sections=""):
        return self._get("/locator/digest", {"sections": sections or None})


class DC(Runtime):
    """Public DC Member API client — command registration and dispatch."""

    # ── Reusable schema fragments for @skill_command(args=...) ─────
    #
    # Defined once and merged into per-command schemas via the `**` spread
    # so MCP clients see consistent flag descriptions across every command
    # that takes pagination, the past-toggle, or a status filter.

    _PAGINATION_ARGS: dict = {
        "limit":  {"type": "integer", "description": "Page size (1-100)"},
        "cursor": {"type": "string",  "description": "Opaque continuation token from a previous response"},
    }
    _PAST_ARG: dict = {
        "past": {"type": "boolean", "description": "Return past records instead of upcoming",
                 "default": False},
    }
    _RSVP_STATUS_ARG: dict = {
        "status": {"type": "string", "enum": ["yes", "maybe", "no"],
                   "description": "Your RSVP response", "required": True},
    }

    def __init__(self, api_url: str | None = None):
        super().__init__("dc", __file__)
        if api_url:
            self.api_url = api_url
        self._core = _DCCore(self)
        self._commands = self._discover_commands()
        # Wire HttpClient response-header observer so we can warn the
        # user once per process when the server's API version has
        # outpaced this client's DC_API_VERSION on major or minor.
        _VersionTracker.attach()

    # ── Setup ───────────────────────────────────────────────────────

    @skill_command(name="setup",
                   help="Save your DC API key to .env.dc: --api-key dk_<api-key>",
                   parser=_DCCore._parse_setup,
                   args={
                       "api-key": {"type": "string", "required": True,
                                   "description": "Your DC Member API key, format dk_<api-key>"},
                   })
    def setup(self, api_key=""):
        return self._core.setup(api_key=api_key)

    @skill_command(name="self-test",
                   help="Validate env, network, and /profile end-to-end",
                   args={})
    def self_test(self):
        return self._core.self_test()

    # ── Profile ─────────────────────────────────────────────────────

    @skill_command(name="profile",
                   help="Get your own DC profile",
                   args={})
    def profile(self):
        return self._core.profile()

    @skill_command(name="profile-update",
                   help="Update your profile fields (e.g. --headline 'CEO at Acme')",
                   parser=_DCCore._parse_profile_patch,
                   args={
                       # _accept_extras tells the schema builder that this command's
                       # parser accepts arbitrary --<key> <value> flags beyond the
                       # documented examples below.
                       "_accept_extras":     {"additional": True},
                       "headline":           {"type": "string", "description": "Short tagline shown on your profile"},
                       "businessDescription": {"type": "string", "description": "Description of your business (HTML allowed)"},
                       "businessUrl":        {"type": "string", "description": "Your business website URL"},
                       "industry":           {"type": "string", "description": "Industry tag"},
                       "github":             {"type": "string",
                                              "description": "Your GitHub username — required for access to private DC repos"},
                       "linkedin":           {"type": "string", "description": "LinkedIn profile URL"},
                       "twitter":            {"type": "string", "description": "Twitter/X profile URL"},
                       "instagram":          {"type": "string", "description": "Instagram handle"},
                       "facebook":           {"type": "string", "description": "Facebook profile URL"},
                       "whatsapp":           {"type": "string", "description": "WhatsApp number with country code"},
                       "hobbies":            {"type": "string", "description": "Comma-separated hobby list"},
                   })
    def profile_update(self, fields: dict):
        return self._core.update_profile(fields or {})

    @skill_command(name="limits",
                   help="Show your effective rate limits (per-minute / per-day) and current usage",
                   args={})
    def limits(self):
        return self._core.limits()

    # ── Membership ──────────────────────────────────────────────────

    @skill_command(name="membership",
                   help="Get your full membership state — role, trial, billing, next renewal date",
                   args={})
    def membership(self):
        return self._core.membership()

    @skill_command(name="invoices",
                   help="Your Stripe invoices (newest first) with hosted URL + PDF [--limit N]",
                   parser=_DCCore._parse_list_args,
                   args={**_PAGINATION_ARGS})
    def invoices(self, limit=20, cursor=None, **_unused):  # cursor accepted for symmetry
        return self._core.membership_invoices(limit=limit)

    # ── Notifications ───────────────────────────────────────────────

    @skill_command(name="notifications",
                   help="Read your push/email preferences + locator (Friday email) toggles",
                   args={})
    def notifications(self):
        return self._core.notifications()

    @skill_command(name="notifications-update",
                   help="Update notification preferences. Examples: "
                        "--cat-announcement-email false / --cat-reaction-push true. "
                        "Categories: account, activity, announcement, channel, chat, "
                        "directMessage, discussion, event, mention, myReaction, photoTag, reaction. "
                        "Channels: push, email (email not supported for reaction/myReaction). "
                        "For the Friday email digest, use `locator-settings-update` instead.",
                   parser=_DCCore._parse_notifications_patch,
                   args={
                       "_accept_extras": {"additional": True},
                       "cat-announcement-email": {"type": "boolean", "description": "Email for announcements"},
                       "cat-announcement-push":  {"type": "boolean", "description": "Push for announcements"},
                       "cat-mention-email":      {"type": "boolean", "description": "Email for @mentions"},
                       "cat-mention-push":       {"type": "boolean", "description": "Push for @mentions"},
                   })
    def notifications_update(self, fields: dict):
        return self._core.update_notifications(fields or {})

    # ── Locator (Friday email) ──────────────────────────────────────

    @skill_command(name="locator-settings",
                   help="Read your Friday locator email digest toggles",
                   args={})
    def locator_settings(self):
        return self._core.locator_settings()

    @skill_command(name="locator-settings-update",
                   help="Update Friday locator email toggles. Any subset of: "
                        "--enabled --events --tickets --trips (true|false).",
                   parser=_DCCore._parse_locator_settings_patch,
                   args={
                       "enabled": {"type": "boolean", "description": "Master toggle for the Friday digest"},
                       "events":  {"type": "boolean", "description": "Include new events"},
                       "tickets": {"type": "boolean", "description": "Include DCer tickets"},
                       "trips":   {"type": "boolean", "description": "Include trip alerts"},
                   })
    def locator_settings_update(self, fields: dict):
        return self._core.update_locator_settings(fields or {})

    # ── Calendar ────────────────────────────────────────────────────

    @skill_command(name="calendar",
                   help="Your iCalendar feed URLs + content toggles. Subscribe in any calendar app.",
                   args={})
    def calendar(self):
        return self._core.calendar()

    @skill_command(name="calendar-update",
                   help="Update calendar feed toggles. Pass any of: "
                        "--includeMyTickets, --includeEventAgenda, --includeVirtualCalls, "
                        "--includeMyTrips, --includeFlagshipEvents, --includeDCBlackEvents, "
                        "--includeHomeChapterEvents, --includeFollowedChapterEvents, "
                        "--includeOtherChapterEvents (true|false).",
                   parser=_DCCore._parse_calendar_patch,
                   args={
                       "includeMyTickets":             {"type": "boolean"},
                       "includeEventAgenda":           {"type": "boolean"},
                       "includeVirtualCalls":          {"type": "boolean"},
                       "includeMyTrips":               {"type": "boolean"},
                       "includeFlagshipEvents":        {"type": "boolean"},
                       "includeDCBlackEvents":         {"type": "boolean"},
                       "includeHomeChapterEvents":     {"type": "boolean"},
                       "includeFollowedChapterEvents": {"type": "boolean"},
                       "includeOtherChapterEvents":    {"type": "boolean"},
                   })
    def calendar_update(self, fields: dict):
        return self._core.update_calendar(fields or {})

    # ── Report Issue ────────────────────────────────────────────────

    @skill_command(name="report-issue",
                   help="Report a bug, feedback, or question to the DC team. "
                        "--text REQUIRED. --severity bug|feedback|question (default bug). "
                        "--screenshot FILE_PATH (PNG/JPEG/WebP, max 4 MB, optional). "
                        "--context JSON_STRING (optional structured debug info).",
                   parser=_DCCore._parse_report_issue,
                   args={
                       "text":       {"type": "string", "required": True,
                                      "description": "Description of the issue (1-4000 chars)"},
                       "severity":   {"type": "string", "enum": ["bug", "feedback", "question"],
                                      "default": "bug",
                                      "description": "Issue severity"},
                       "screenshot": {"type": "string",
                                      "description": "Path to a PNG/JPEG/WebP file (max 4 MB), a base64 string, or a data: URL"},
                       "context":    {"type": "string",
                                      "description": "Optional JSON object as a string — debug context for triage"},
                   })
    def report_issue(self, text="", severity="bug", screenshot=None, context=None):
        return self._core.report_issue(text=text, severity=severity, screenshot=screenshot, context=context)

    # ── Announcements ───────────────────────────────────────────────

    @skill_command(name="announcements",
                   help="Recent announcements from DC's broadcast channels [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args={**_PAGINATION_ARGS})
    def announcements(self, limit=10, cursor=None, **_unused):
        return self._core.announcements(limit=limit, cursor=cursor)

    @skill_command(name="announcements-latest",
                   help="One most-recent announcement per channel — quick 'what's new across DC?' overview",
                   args={})
    def announcements_latest(self):
        return self._core.announcements_latest()

    # ── Trips ───────────────────────────────────────────────────────

    @skill_command(name="trips", help="List your trips [--past] [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args={**_PAGINATION_ARGS, **_PAST_ARG})
    def trips(self, past=False, limit=50, cursor=None):
        return self._core.trips(past=past, limit=limit, cursor=cursor)

    @skill_command(name="trip",
                   help="CANONICAL 'who should I meet on this trip?' endpoint. Full trip + ranked top-10 "
                        "DCers to meet (mini profile + score), AI-written whyToMeet paragraphs, fullPool of "
                        "every local + visitor in town, overlapping trips, events, roomID. Prefer over "
                        "`overlaps` for match-making — `overlaps` is date-window-only and far narrower.",
                   args={})
    def trip(self, trip_id):
        return self._core.trip(trip_id)

    @skill_command(name="trip-discovery",
                   help="Same 'who should I meet?' answer as `trip` but without the trip body — top-10 "
                        "picks with AI whyToMeet paragraphs, fullPool of locals+visitors, events, "
                        "overlapping trips. Prefer this (or `trip`) over `overlaps` for match-making.",
                   args={
                       "include": {"type": "string",
                                   "description": "Optional. Comma-separated subset of `people,fullPool,whyToMeet,events,overlappingTrips`. Default = all five."},
                   })
    def trip_discovery(self, trip_id, include=None):
        return self._core.trip_discovery(trip_id, include=include)

    @skill_command(name="trip-refresh",
                   help="Owner-only: re-trigger the discovery cache rebuild for a trip "
                        "(recomputes top picks, AI paragraphs, events, overlapping trips).",
                   args={})
    def trip_refresh(self, trip_id):
        return self._core.trip_refresh(trip_id)

    @skill_command(name="overlaps",
                   help="Narrow: DCers with date-overlapping trips in the same city. For 'who should I "
                        "MEET on my trip?' use `trip` or `trip-discovery` — they include locals + AI-ranked "
                        "top-10 + whyToMeet summaries. [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args=_PAGINATION_ARGS)
    def overlaps(self, limit=10, cursor=None):
        return self._core.overlaps(limit=limit, cursor=cursor)

    @skill_command(name="trip-create",
                   help="Create a trip (--start-date YYYY-MM-DD --end-date YYYY-MM-DD --place-id PID | --event-id EID). "
                        "Optional --points to attach up to 20 venue/idea notes.",
                   parser=_DCCore._parse_trip_create,
                   args={
                       "start-date": {"type": "string", "format": "date", "required": True,
                                      "description": "Trip start date (YYYY-MM-DD)"},
                       "end-date":   {"type": "string", "format": "date", "required": True,
                                      "description": "Trip end date (YYYY-MM-DD)"},
                       "place-id":   {"type": "string",
                                      "description": "Google Place ID — provide either this OR event-id (not both)"},
                       "event-id":   {"type": "string",
                                      "description": "DC event ID — copies location from event. Provide either this OR place-id"},
                       "points":     {"type": "array",
                                      "description": "Optional. Up to 20 trip points: list of `{note: str (max 280 chars), placeID?: str}`. The optional placeID is resolved against Google Places."},
                   })
    def trip_create(self, start_date="", end_date="", place_id="", event_id="", points=None):
        return self._core.create_trip(start_date=start_date, end_date=end_date, place_id=place_id, event_id=event_id, points=points)

    @skill_command(name="trip-update",
                   help="Update a trip by ID — any subset of --start-date, --end-date, --place-id, --event-id, --points. "
                        "Passing --points replaces the entire array (pass [] to clear).",
                   parser=_DCCore._parse_trip_update,
                   args={
                       "start-date": {"type": "string", "format": "date",
                                      "description": "New start date (YYYY-MM-DD)"},
                       "end-date":   {"type": "string", "format": "date",
                                      "description": "New end date (YYYY-MM-DD)"},
                       "place-id":   {"type": "string", "description": "New Google Place ID"},
                       "event-id":   {"type": "string", "description": "New DC event ID"},
                       "points":     {"type": "array",
                                      "description": "Optional. Replace the entire points array. Up to 20 items, same shape as `trip-create`. Pass `[]` to clear."},
                   })
    def trip_update(self, trip_id, start_date="", end_date="", place_id="", event_id="", points=None):
        return self._core.update_trip(trip_id, start_date=start_date, end_date=end_date,
                                      place_id=place_id, event_id=event_id, points=points)

    @skill_command(name="trip-delete", help="Delete a trip by ID", args={})
    def trip_delete(self, trip_id):
        return self._core.delete_trip(trip_id)

    # ── Events ──────────────────────────────────────────────────────

    @skill_command(name="events", help="List in-person events [--past] [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args={**_PAGINATION_ARGS, **_PAST_ARG})
    def events(self, past=False, limit=20, cursor=None):
        return self._core.events(past=past, limit=limit, cursor=cursor)

    @skill_command(name="event", help="Get a single event by ID", args={})
    def event(self, event_id):
        return self._core.event(event_id)

    @skill_command(name="event-attendees",
                   help="List attendees for an event [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_id_with_limit,
                   args=_PAGINATION_ARGS)
    def event_attendees(self, event_id, limit=100, cursor=None):
        return self._core.event_attendees(event_id, limit=limit, cursor=cursor)

    @skill_command(name="event-rsvp",
                   help="RSVP to an event: <eventID> --status yes|maybe|no",
                   parser=_DCCore._parse_rsvp,
                   args=_RSVP_STATUS_ARG)
    def event_rsvp(self, event_id, status=""):
        return self._core.event_rsvp(event_id, status)

    @skill_command(name="event-schedule",
                   help="Full event schedule (sessions, day-grouped). Requires an event ticket.",
                   args={})
    def event_schedule(self, event_id):
        return self._core.event_schedule(event_id)

    @skill_command(name="event-agenda",
                   help="Sessions + meetups on the agenda for an event. "
                        "By default returns YOUR agenda. Pass --user-id to view "
                        "another attendee's agenda — useful for planning together "
                        "(find coffee windows, suggest sessions to overlap). "
                        "Both you and the target must hold a valid ticket.",
                   args={
                       "user-id": {"type": "string", "description": "Optional. View another attendee's agenda by their userID."},
                   })
    def event_agenda(self, event_id, user_id=None):
        return self._core.event_agenda(event_id, user_id=user_id)

    @skill_command(name="event-agendas",
                   help="Bulk fetch up to 20 attendee agendas in one call. Use when comparing "
                        "schedules across several DCers (\"what sessions are Lina, Alex, and Jeff "
                        "all attending?\"). Non-attendee userIDs are silently dropped — pass a "
                        "candidate list without pre-checking each ticket. You must hold a ticket.",
                   args={
                       "user-ids": {"type": "string", "required": True, "description": "Comma-separated attendee userIDs (max 20). Non-attendees silently dropped.", "examples": ["940,1673,2572"]},
                   })
    def event_agendas(self, event_id, user_ids):
        return self._core.event_agendas(event_id, user_ids)

    @skill_command(name="event-free-slots",
                   help="Find shared free time slots across event attendees — windows where they're "
                        "NOT in a bookmarked session or meetup. Ranked by overlap (most-shared "
                        "first). Use to find a coffee window with one DCer or a junto-style lunch "
                        "slot for a group. You must hold a ticket; non-attendee IDs are silently dropped.",
                   args={
                       "user-ids":          {"type": "string", "required": True, "description": "Comma-separated attendee userIDs to compare (1-20). Non-attendees silently dropped.", "examples": ["940,1673,2572"]},
                       "min-duration-mins": {"type": "number", "default": 30, "description": "Minimum slot length in minutes (15-480, default 30)."},
                       "within-day-date":   {"type": "string", "description": "Optional. Scope to a single event day (YYYY-MM-DD venue-local). Omit for the full event range.", "examples": ["2026-05-06"]},
                   })
    def event_free_slots(self, event_id, user_ids, min_duration_mins=30, within_day_date=None):
        return self._core.event_free_slots(event_id, user_ids,
                                           min_duration_mins=min_duration_mins,
                                           within_day_date=within_day_date)

    @skill_command(name="event-meetups",
                   help="Approved member-organized meetups for an event. Requires an event ticket.",
                   args={})
    def event_meetups(self, event_id):
        return self._core.event_meetups(event_id)

    @skill_command(name="event-sponsors",
                   help="Event sponsors, ordered by tier. Requires an event ticket.",
                   args={})
    def event_sponsors(self, event_id):
        return self._core.event_sponsors(event_id)

    @skill_command(name="session-attendees",
                   help="Attendees who bookmarked a session: <eventID> <sessionID>",
                   args={})
    def session_attendees(self, event_id, session_id):
        return self._core.session_attendees(event_id, session_id)

    @skill_command(name="meetup-attendees",
                   help="Attendees who RSVPd to a meetup: <eventID> <meetupID>",
                   args={})
    def meetup_attendees(self, event_id, meetup_id):
        return self._core.meetup_attendees(event_id, meetup_id)

    @skill_command(name="session-bookmark",
                   help="Bookmark/unbookmark a session: <eventID> <sessionID> [--bookmarked true|false]",
                   args={"bookmarked": {"type": "boolean", "description": "true to add to agenda, false to remove (default true)"}})
    def session_bookmark(self, event_id, session_id, bookmarked="true"):
        # Accept "true"/"false" strings from CLI, real booleans from Python.
        is_on = str(bookmarked).strip().lower() not in {"false", "0", "no", "n"}
        return self._core.session_bookmark(event_id, session_id, bookmarked=is_on)

    @skill_command(name="meetup-rsvp",
                   help="Join/leave a meetup: <eventID> <meetupID> [--joined true|false]",
                   args={"joined": {"type": "boolean", "description": "true to join, false to leave (default true)"}})
    def meetup_rsvp(self, event_id, meetup_id, joined="true"):
        is_on = str(joined).strip().lower() not in {"false", "0", "no", "n"}
        return self._core.meetup_rsvp(event_id, meetup_id, joined=is_on)

    # ── Virtual events ─────────────────────────────────────────────

    @skill_command(name="virtual-events",
                   help="List online sessions/calls [--past] [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args={**_PAGINATION_ARGS, **_PAST_ARG})
    def virtual_events(self, past=False, limit=50, cursor=None):
        return self._core.virtual_events(past=past, limit=limit, cursor=cursor)

    @skill_command(name="virtual-event", help="Get a single virtual event by sessionID", args={})
    def virtual_event(self, session_id):
        return self._core.virtual_event(session_id)

    @skill_command(name="virtual-event-rsvp",
                   help="RSVP to a virtual event: <sessionID> --status yes|maybe|no",
                   parser=_DCCore._parse_rsvp,
                   args=_RSVP_STATUS_ARG)
    def virtual_event_rsvp(self, session_id, status=""):
        return self._core.virtual_event_rsvp(session_id, status)

    # ── Tickets ────────────────────────────────────────────────────

    @skill_command(name="tickets",
                   help="List your tickets [--status valid|maybe|refunded|canceled] [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args={**_PAGINATION_ARGS,
                         "status": {"type": "string",
                                    "enum": ["valid", "maybe", "refunded", "canceled"],
                                    "description": "Filter tickets by status"}})
    def tickets(self, status="", limit=50, cursor=None):
        return self._core.tickets(status=status, limit=limit, cursor=cursor)

    # ── Invites ────────────────────────────────────────────────────

    @skill_command(name="invites", help="List your sent invites [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args=_PAGINATION_ARGS)
    def invites(self, limit=50, cursor=None):
        return self._core.invites(limit=limit, cursor=cursor)

    @skill_command(name="permacode", help="Get your permanent invite code", args={})
    def permacode(self):
        return self._core.permacode()

    @skill_command(name="invite-create",
                   help="Send a new DC invite: --email EMAIL --full-name 'NAME'",
                   parser=_DCCore._parse_invite,
                   args={
                       "email":     {"type": "string", "format": "email", "required": True,
                                     "description": "Recipient's email address"},
                       "full-name": {"type": "string", "required": True,
                                     "description": "Recipient's full name"},
                   })
    def invite_create(self, email="", full_name=""):
        return self._core.create_invite(email=email, full_name=full_name)

    # ── Inbox ──────────────────────────────────────────────────────

    @skill_command(name="inbox",
                   help="Summary of unread inbox messages [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args=_PAGINATION_ARGS)
    def inbox(self, limit=50, cursor=None):
        return self._core.inbox(limit=limit, cursor=cursor)

    # ── Rooms ──────────────────────────────────────────────────────

    @skill_command(name="rooms",
                   help="List rooms you are subscribed to [--type channel|direct|...] [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args={**_PAGINATION_ARGS,
                         "type": {"type": "string",
                                  "enum": ["channel", "direct", "group", "discussion", "activity", "event"],
                                  "description": "Filter rooms by type (includes DMs and group DMs)"}})
    def rooms(self, room_type="", limit=50, cursor=None):
        return self._core.rooms(room_type=room_type, limit=limit, cursor=cursor)

    @skill_command(name="browse-rooms",
                   help="Browse public rooms by type (channel|discussion|activity) [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_id_with_limit,
                   args=_PAGINATION_ARGS)
    def browse_rooms(self, room_type, limit=50, cursor=None):
        return self._core.browse_rooms(room_type, limit=limit, cursor=cursor)

    @skill_command(name="room", help="Get one room's metadata by roomID", args={})
    def room(self, room_id):
        return self._core.room(room_id)

    @skill_command(name="room-messages",
                   help="List messages in a room (read only, newest first, cursor-paginated) [--limit N] [--before TOKEN]",
                   args={"room_id": {"type": "string", "required": True,
                                     "description": "Room ID. Discover via `rooms`, `inbox`, `trip` (roomID field), or event rooms."},
                         "limit":   {"type": "integer", "default": 50,
                                     "description": "Max messages (1-100)"},
                         "before":  {"type": "string",
                                     "description": "Cursor from a previous response's nextCursor to fetch the next older page."}})
    def room_messages(self, room_id, limit=50, before=None):
        return self._core.room_messages(room_id, limit=limit, before=before)

    @skill_command(name="room-summary",
                   help="Get the latest AI summary of a specific type for a room. Daily and weekly cover different windows — you always ask for one.",
                   args={
                       "type": {"type": "string", "required": True,
                                "enum": ["daily", "weekly"],
                                "description": "Which summary type to fetch."},
                   })
    def room_summary(self, room_id, type):
        return self._core.room_summary(room_id, type)

    @skill_command(name="room-summaries",
                   help="Paginate past AI summaries of a specific type (daily or weekly) for a room.",
                   args={
                       "type": {"type": "string", "required": True,
                                "enum": ["daily", "weekly"],
                                "description": "Which summary type to paginate."},
                       "limit": {"type": "integer", "default": 20,
                                 "description": "Max summaries (1-50)."},
                       "cursor": {"type": "string",
                                  "description": "Cursor from a previous response's nextCursor."},
                   })
    def room_summaries(self, room_id, type, limit=20, cursor=None):
        return self._core.room_summaries(room_id, type, limit=limit, cursor=cursor)

    @skill_command(name="room-subscribe",
                   help="Subscribe to a public channel/discussion/quick-question/event room.",
                   args={})
    def room_subscribe(self, room_id):
        return self._core.room_subscribe(room_id)

    @skill_command(name="room-unsubscribe",
                   help="Unsubscribe from a channel/discussion/quick-question/event room.",
                   args={})
    def room_unsubscribe(self, room_id):
        return self._core.room_unsubscribe(room_id)

    @skill_command(name="room-mute",
                   help="Mute notifications for a room (room stays in inbox).",
                   args={})
    def room_mute(self, room_id):
        return self._core.room_mute(room_id)

    @skill_command(name="room-unmute", help="Resume notifications for a muted room.", args={})
    def room_unmute(self, room_id):
        return self._core.room_unmute(room_id)

    @skill_command(name="room-archive",
                   help="Archive a room — hides from inbox sidebar without unsubscribing.",
                   args={})
    def room_archive(self, room_id):
        return self._core.room_archive(room_id)

    @skill_command(name="room-unarchive",
                   help="Restore a previously-archived room to the inbox sidebar.",
                   args={})
    def room_unarchive(self, room_id):
        return self._core.room_unarchive(room_id)

    @skill_command(name="room-pin",
                   help="Pin a room to the top of the inbox. Auto-subscribes if needed.",
                   args={})
    def room_pin(self, room_id):
        return self._core.room_pin(room_id)

    @skill_command(name="room-unpin",
                   help="Unpin a room. Returns to normal inbox sort order.",
                   args={})
    def room_unpin(self, room_id):
        return self._core.room_unpin(room_id)

    # ── Chapters ───────────────────────────────────────────────────

    @skill_command(name="chapters", help="List DC city-based chapters [--limit N] [--cursor TOKEN]",
                   parser=_DCCore._parse_list_args,
                   args=_PAGINATION_ARGS)
    def chapters(self, limit=50, cursor=None):
        return self._core.chapters(limit=limit, cursor=cursor)

    @skill_command(name="chapter", help="Get one chapter by cityID (Google Place ID)", args={})
    def chapter(self, city_id):
        return self._core.chapter(city_id)

    # ── Places ─────────────────────────────────────────────────────

    @skill_command(name="places-search", help="Search Google Places: --q 'tokyo' [--limit N]",
                   parser=_DCCore._parse_places_search,
                   args={
                       "q":     {"type": "string", "required": True,
                                 "description": "Search query (city, place name, etc.)"},
                       "limit": {"type": "integer", "default": 10,
                                 "description": "Maximum number of results (1-20)"},
                   })
    def places_search(self, q="", limit=10):
        return self._core.places_search(q=q, limit=limit)

    @skill_command(name="place", help="Get place details by Google Place ID", args={})
    def place(self, place_id):
        return self._core.place(place_id)

    # ── Discovery ──────────────────────────────────────────────────

    @skill_command(name="profile-match",
                   help="Match DCers from a description, or recommend if no query. "
                        "Profiles only. Filters compose with AND. Each result includes "
                        "`score` (composite, sortable), `vectorScore` (pure semantic similarity), "
                        "and `keywordScore` (when reranker ran).",
                   args={
                       "query":                    {"type": "string", "description": "Free-form description ('DCers in Lisbon who run SaaS'). Omit to get recommendations from your own profile."},
                       "limit":                    {"type": "integer", "default": 50, "description": "Max results (1-50)."},
                       "location-chapter-place-id": {"type": "string", "description": "Google Place ID — DCers based here."},
                       "location-current-place-id": {"type": "string", "description": "Google Place ID — DCers currently here."},
                       "event-id":                  {"type": "string", "description": "Event ID — DCers attending this event (valid ticket only)."},
                       "is-dcb":                    {"type": "boolean", "description": "When true, narrow to DC BLACK members only."},
                       "industry":                  {"type": "string", "description": "Exact match on PrimaryBusinessIndustry. e.g. 'SaaS & Tech', 'Marketing Agency', 'Ecommerce & Amazon', 'Coaching', 'Other'."},
                       "min-team-size":             {"type": "string", "description": "'At least this team size' filter. e.g. '10-14'. Ordered None<1-2<3-5<6-9<10-14<15-19<20-34<35-49<50-74<75-99<100+. Privacy-gated to DCers who set TeamSizePrivacy to all-DCers."},
                       "min-revenue":               {"type": "string", "description": "'At least this revenue' filter. e.g. '$1M+', '$250K+'. Privacy-gated to DCers who set AnnualRevenuePrivacy to all-DCers."},
                       "gender":                    {"type": "string", "description": "Exact match. 'Man' | 'Woman' | 'Non-binary'. NOTE: gender is sparsely populated — most DCers leave it blank; use as a 'narrow if set' hint."},
                       "no-rerank":                 {"type": "boolean", "description": "Skip the keyword reranker and return results in raw vector-similarity order. Useful for fuzzy/semantic queries or A/B comparison."},
                   })
    def profile_match(self, query=None, limit=50,
                      location_chapter_place_id=None,
                      location_current_place_id=None,
                      event_id=None, is_dcb=None,
                      industry=None, min_team_size=None, min_revenue=None,
                      gender=None, no_rerank=None):
        return self._core.profile_match(
            query=query,
            limit=limit,
            location_chapter_place_id=location_chapter_place_id,
            location_current_place_id=location_current_place_id,
            event_id=event_id,
            is_dcb=is_dcb,
            industry=industry,
            min_team_size=min_team_size,
            min_revenue=min_revenue,
            gender=gender,
            no_rerank=no_rerank,
        )

    # ── Locator ────────────────────────────────────────────────────

    @skill_command(name="locator",
                   help="Weekly locator digest [--sections homeCity,favoriteCities,favoritePeople,myTrips]",
                   parser=_DCCore._parse_list_args,
                   args={
                       "sections": {"type": "string",
                                    "description": "Comma-separated list: homeCity, favoriteCities, favoritePeople, myTrips. Empty = all sections"},
                   })
    def locator(self, sections="", **_unused):
        return self._core.locator(sections=sections)

    # ── MCP server (optional) ──────────────────────────────────────
    #
    # When the user runs `python3 dc.py --mcp`, the same registered
    # commands are exposed as MCP tools over stdio. The `mcp` package is
    # imported lazily — CLI and Python-import users never need it.

    def run_mcp(self) -> int:
        """Run as an MCP server over stdio. Requires `pip install mcp`."""
        if not _MCP_AVAILABLE:
            print(
                "MCP mode requires the optional 'mcp' package.\n"
                "Install it with: pip install -r py/requirements.txt\n"
                "    or:           pip install mcp",
                file=sys.stderr,
            )
            return 1

        import asyncio

        server = _MCPServer("dc")

        @server.list_tools()
        async def _list_tools():
            tools = []
            for name in sorted(self._commands):
                cmd = self._commands[name]
                # Derive positional names from the wrapper signature so the
                # agent gets them as named fields (`event_id`, `city_id`, …).
                sig = inspect.signature(cmd["fn"])
                positional = [
                    p.name.replace("_", "-")
                    for p in sig.parameters.values()
                    if p.name != "self"
                    and p.default is inspect.Parameter.empty
                    and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                   inspect.Parameter.POSITIONAL_ONLY)
                ]
                tools.append(_mcp_types.Tool(
                    name=name,
                    description=cmd["help"] or f"DC command: {name}",
                    inputSchema=_build_input_schema(cmd.get("args"), positional=positional),
                ))
            return tools

        @server.call_tool()
        async def _call_tool(name: str, arguments: dict):
            cmd = self._commands.get(name)
            if not cmd:
                return [_mcp_types.TextContent(type="text", text=f"Unknown tool: {name}")]
            try:
                # Reuse each command's parser by translating MCP arguments
                # back into a CLI-style raw_args list (kebab-case flags).
                # Agents send positional args by their declared name (e.g.
                # {"event-id": "abc"} for `event-rsvp <eventID>`). Translate
                # those back into positional CLI args so each command's
                # parser sees the same shape it does from the CLI.
                fn_sig = inspect.signature(cmd["fn"])
                positional_names = [
                    p.name.replace("_", "-")
                    for p in fn_sig.parameters.values()
                    if p.name != "self"
                    and p.default is inspect.Parameter.empty
                    and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                   inspect.Parameter.POSITIONAL_ONLY)
                ]
                args = dict(arguments or {})
                raw_args: list = []
                # Positionals first, in declared order
                for pname in positional_names:
                    if pname in args:
                        raw_args.append(str(args.pop(pname)))
                # Then remaining values as flags
                for k, v in args.items():
                    if isinstance(v, bool):
                        if v:
                            raw_args.append(f"--{k}")
                        continue
                    raw_args.append(f"--{k}")
                    raw_args.append(str(v))
                result = self._invoke(cmd, raw_args)
            except (UsageError, DCError) as e:
                return [_mcp_types.TextContent(type="text", text=f"Error: {e}")]

            data = result.data if isinstance(result, Result) else result
            emitted = result.emitted if isinstance(result, Result) else ""

            payload = json.dumps(data, indent=2, ensure_ascii=False, default=str) \
                if isinstance(data, (dict, list)) else str(data) if data is not None else ""

            content = [_mcp_types.TextContent(type="text", text=payload)]
            # Surface any emit() output as a second TextContent so the
            # calling agent receives both the data and the follow-up
            # instructions in a single tool-call response.
            if emitted:
                content.append(_mcp_types.TextContent(
                    type="text",
                    text=f"📣 emit:\n{emitted}",
                ))
            return content

        async def _main():
            async with _mcp_stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())

        try:
            asyncio.run(_main())
        except KeyboardInterrupt:
            pass
        return 0


def main():
    """Entry point for the `dc` console script (PyPI install)."""
    if "--mcp" in sys.argv:
        return DC().run_mcp()
    return DC().dispatch()


if __name__ == "__main__":
    sys.exit(main())
