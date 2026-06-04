"""Cross-command MCP schema invariants.

These are the structural guards: every command exposes a typed `args=`
schema, and the closed-set field commands keep their schema in lockstep
with the parser. This is the layer that catches "declared-but-wrong field
name" drift (the class of bug behind the profile-update 400s) before release.
"""
import inspect

import dc


def _all_commands():
    cmds = {}
    for _, fn in inspect.getmembers(dc.DC):
        meta = getattr(fn, "_skill_command", None)
        if isinstance(meta, dict) and meta.get("name"):
            cmds[meta["name"]] = meta
    return cmds


def test_there_are_commands_registered():
    assert len(_all_commands()) > 20


def test_every_command_declares_args_schema():
    # Mirrors self-test's `mcpSchemas` check: a missing args= means MCP
    # clients fall back to the catch-all `additionalProperties: true`.
    missing = [name for name, meta in _all_commands().items() if meta.get("args") is None]
    assert not missing, f"commands missing args= schema: {sorted(missing)}"


def test_closed_set_commands_have_no_alias_names_as_canonical_args():
    # The legacy profile aliases must NOT appear as canonical args — they
    # are inputs the parser remaps, not real server fields.
    profile_args = set(_all_commands()["profile-update"]["args"])
    assert not (set(dc._DCCore._PROFILE_ALIASES) & profile_args)
