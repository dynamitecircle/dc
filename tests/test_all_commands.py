"""Cross-cutting invariants that run against EVERY registered command.

Two guards, parametrized over the whole command surface:

1. Registration — every command exposes a non-empty help string and a typed
   ``args=`` schema (no command falls back to the catch-all MCP schema).
2. Binding — every flag a command declares in ``args=`` is actually accepted
   by its arg-binding (custom ``parser=`` or the auto-parser fallback). This
   mirrors the real MCP path: build a tool-call input from the declared
   schema, serialize it exactly as the MCP→CLI bridge does, and run only the
   binding layer — never the network-backed method body. It is the guard
   against the "command rejects its own declared flags" regression
   (the original Jeff Ritger / `267fad2` bug) across all commands at once.
"""
import inspect

import pytest

import dc


def _all_commands():
    out, seen = [], set()
    for _, fn in inspect.getmembers(dc.DC, predicate=inspect.isfunction):
        meta = getattr(fn, "_skill_command", None)
        if isinstance(meta, dict) and meta.get("name") and meta["name"] not in seen:
            seen.add(meta["name"])
            out.append((meta["name"], fn, meta))
    return sorted(out, key=lambda t: t[0])


COMMANDS = _all_commands()
IDS = [c[0] for c in COMMANDS]


def _required_positionals(fn):
    return [
        p for p in inspect.signature(fn).parameters.values()
        if p.name != "self"
        and p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY)
    ]


def _dummy_for(spec):
    t = (spec or {}).get("type")
    if t == "boolean":
        return True
    if t in ("integer", "number"):
        return 1
    if t == "array":
        return []
    return "x"


def _bridge_raw_args(fn, arguments):
    """Replicate the MCP→CLI bridge's argument serialization (dc.py).

    MCP tool fields are snake_case; the bridge maps them back to kebab CLI
    flags (`user_id` -> `--user-id`) and snake positionals to positional args.
    """
    args = dict(arguments)
    raw = []
    for p in _required_positionals(fn):
        if p.name in args:
            raw.append(str(args.pop(p.name)))
    for k, v in args.items():
        flag = f"--{k.replace('_', '-')}"
        if isinstance(v, bool):
            if v:
                raw.append(flag)
            continue
        raw.append(flag)
        raw.append(str(v))
    return raw


def test_there_are_many_commands():
    assert len(COMMANDS) > 30


def test_no_duplicate_command_names():
    names = [c[0] for c in COMMANDS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("name,fn,meta", COMMANDS, ids=IDS)
def test_command_registration(name, fn, meta):
    assert meta.get("help"), f"{name}: empty help string"
    assert meta.get("args") is not None, f"{name}: missing args= schema (falls back to catch-all)"
    assert isinstance(meta["args"], dict), f"{name}: args= must be a dict"
    assert name == name.lower(), f"{name}: command name must be kebab/lowercase"


@pytest.mark.parametrize("name,fn,meta", COMMANDS, ids=IDS)
def test_declared_flags_accepted_by_binding(name, fn, meta):
    arg_specs = meta["args"] or {}
    # Real declared flags only — skip schema-builder meta keys (e.g. _accept_extras).
    declared = {k: v for k, v in arg_specs.items() if not k.startswith("_")}

    # An MCP client sends snake_case fields: snake positionals + snake flags.
    arguments = {}
    for p in _required_positionals(fn):
        arguments[p.name] = "x"
    for k, spec in declared.items():
        arguments[k.replace("-", "_")] = _dummy_for(spec)

    raw_args = _bridge_raw_args(fn, arguments)
    parser = meta.get("parser")

    try:
        if parser is not None:
            parser(raw_args)
        else:
            params = [p for p in inspect.signature(fn).parameters.values() if p.name != "self"]
            positionals, flags = dc.ArgHelpers.parse_flags(list(raw_args))
            if flags and not arg_specs:
                pytest.fail(f"{name}: bridge produced flags but command has empty args= and no parser")
            if flags:
                dc.ArgHelpers.auto_parse_declared_flags(name, params, arg_specs, flags)
            assert len(positionals) <= len(params), f"{name}: too many positionals bound"
    except dc.UsageError as e:
        # We only care that a declared flag is RECOGNISED, not that our generic
        # dummy value passes the parser's value-format checks (valid JSON,
        # integer, etc.). Only a flag-REJECTION counts as a failure here.
        msg = str(e).lower()
        if "does not accept flag" in msg or "unknown" in msg:
            pytest.fail(f"{name}: binding rejected a declared flag — {e}")


def test_legacy_profile_aliases_are_not_canonical_args():
    meta = next(m for n, _, m in COMMANDS if n == "profile-update")
    # Aliases are remapped inputs, never canonical server fields — they must
    # not leak into the MCP schema as real fields.
    assert not (set(dc._DCCore._PROFILE_ALIASES) & set(meta["args"]))
