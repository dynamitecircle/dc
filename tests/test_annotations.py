"""MCP tool annotations are accurate, and the write-set can't silently drift.

Every MCP tool carries `readOnlyHint` / `destructiveHint` / `openWorldHint` so
clients can auto-approve reads and flag writes. The read/write split must match
what each command actually does over HTTP — a write mislabelled read-only would
let a client auto-approve a mutation. `test_write_set_matches_http_verbs`
re-derives the write set straight from the source (GET = read, everything else
= write) and fails if `_WRITE_COMMANDS` drifts from reality.
"""
import ast
import inspect
import os

import dc  # noqa: E402 (sys.path set up by conftest.py)

_SRC = os.path.join(os.path.dirname(__file__), "..", "py", "dc.py")
_WRITE_VERBS = {"_post", "_patch", "_put", "_delete"}
_ALL_VERBS = _WRITE_VERBS | {"_get"}


def _derive_writes_from_source():
    """Return the set of command names that issue a mutating HTTP verb.

    Mirrors how the hosted MCP server annotates tools: a GET is read-only,
    any other method is a write. Resolves DC wrappers through `self._core.X`.
    `setup` is excluded here (it writes a local file, no HTTP) and added back
    by the caller.
    """
    tree = ast.parse(open(_SRC, encoding="utf-8").read())
    classes = {c.name: c for c in tree.body if isinstance(c, ast.ClassDef)}

    def scan(fn):
        direct, core = set(), set()
        for n in ast.walk(fn):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "self" and n.attr in _ALL_VERBS):
                direct.add(n.attr)
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "self" and n.attr not in _ALL_VERBS):
                core.add(n.attr)
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)
                    and isinstance(n.value.value, ast.Name) and n.value.value.id == "self"
                    and n.value.attr == "_core"):
                core.add(n.attr)
        return direct, core

    def methods(cls):
        return {fn.name: scan(fn) for fn in classes[cls].body
                if isinstance(fn, ast.FunctionDef)}

    core_m, dc_m = methods("_DCCore"), methods("DC")

    cmd_method = {}
    for fn in classes["DC"].body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call) and getattr(dec.func, "id", None) == "skill_command":
                for kw in dec.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        cmd_method[kw.value.value] = fn.name

    def core_writes(name, seen=None):
        seen = seen or set()
        if name in seen or name not in core_m:
            return False
        seen.add(name)
        direct, core = core_m[name]
        return bool(direct & _WRITE_VERBS) or any(core_writes(x, seen) for x in core)

    def is_write(method):
        direct, core = dc_m.get(method, (set(), set()))
        return bool(direct & _WRITE_VERBS) or any(core_writes(x) for x in core)

    return {cmd for cmd, m in cmd_method.items() if is_write(m)}


def _registered_command_names():
    names = set()
    for _, fn in inspect.getmembers(dc.DC, predicate=inspect.isfunction):
        meta = getattr(fn, "_skill_command", None)
        if isinstance(meta, dict) and meta.get("name"):
            names.add(meta["name"])
    return names


def test_write_set_matches_http_verbs():
    derived = _derive_writes_from_source() | {"setup"}  # setup = local-only write
    assert dc._WRITE_COMMANDS == derived, (
        "_WRITE_COMMANDS drifted from the source HTTP verbs.\n"
        f"missing (writes not marked): {sorted(derived - dc._WRITE_COMMANDS)}\n"
        f"extra (marked but not writes): {sorted(dc._WRITE_COMMANDS - derived)}"
    )


def test_write_and_destructive_sets_have_no_typos():
    names = _registered_command_names()
    assert dc._WRITE_COMMANDS <= names, dc._WRITE_COMMANDS - names
    assert dc._DESTRUCTIVE_COMMANDS <= dc._WRITE_COMMANDS


def test_reads_are_read_only_and_not_destructive():
    for n in ("profile", "trips", "events", "chapters", "search",
              "announcements", "locator", "inbox", "tickets", "limits"):
        ann = dc._tool_annotations(n)
        assert ann["readOnlyHint"] is True, n
        assert ann["destructiveHint"] is False, n


def test_writes_are_not_read_only():
    for n in ("trip-create", "profile-update", "event-rsvp", "invite-create",
              "follow-profile", "trip-refresh", "report-issue", "profile-match"):
        assert dc._tool_annotations(n)["readOnlyHint"] is False, n


def test_delete_is_destructive():
    assert dc._tool_annotations("trip-delete")["destructiveHint"] is True


def test_annotations_accept_snake_or_kebab():
    assert dc._tool_annotations("trip_create") == dc._tool_annotations("trip-create")


def test_local_commands_are_not_open_world():
    assert dc._tool_annotations("setup")["openWorldHint"] is False
    assert dc._tool_annotations("workflows")["openWorldHint"] is False
    assert dc._tool_annotations("profile")["openWorldHint"] is True
