"""Shared fixtures for the offline test suite.

These tests never touch the network. They import the single-file client
(``py/dc.py``) as ``dc`` and exercise the argument parsers, request-body
construction, and MCP ``args=`` schemas directly.
"""
import inspect
import os
import sys

import pytest

# Make ``import dc`` work whether or not pytest's pythonpath is configured.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))
import dc  # noqa: E402


@pytest.fixture(autouse=True)
def _silence_emit(monkeypatch):
    """Stub Runtime.emit so core methods don't print during tests."""
    monkeypatch.setattr(dc.Runtime, "emit", staticmethod(lambda *a, **k: None), raising=False)


@pytest.fixture
def core():
    """A `_DCCore` with HTTP stubbed — captures (method, path, body) calls.

    Lets us assert what a core method *would* send without a network round
    trip. The last call is available as ``core.calls[-1]``.
    """
    c = dc._DCCore.__new__(dc._DCCore)
    calls = []
    c.calls = calls
    c._post = lambda path, body=None: (calls.append(("POST", path, body)), {"ok": True})[1]
    c._patch = lambda path, body=None: (calls.append(("PATCH", path, body)), {"ok": True})[1]
    c._get = lambda path, params=None: (calls.append(("GET", path, params)), {"ok": True})[1]
    c._delete = lambda path: (calls.append(("DELETE", path, None)), {"ok": True})[1]
    return c


@pytest.fixture
def command_args():
    """Return a lookup `fn(name) -> args= schema dict` for a skill command."""
    def _get(name):
        for _, fn in inspect.getmembers(dc.DC):
            meta = getattr(fn, "_skill_command", None)
            if isinstance(meta, dict) and meta.get("name") == name:
                return meta.get("args") or {}
        raise KeyError(f"no registered command named {name!r}")
    return _get
