"""Member API 2.5 surface: profile lookups, recent trips, read/unread, room
filters, alert delivery flags, and user-only search."""
import pytest

import dc
from test_all_commands import _bridge_raw_args


def _cmd(name):
    for fn in vars(dc.DC).values():
        meta = getattr(fn, "_skill_command", None)
        if isinstance(meta, dict) and meta.get("name") == name:
            return fn, meta
    raise KeyError(name)


def _bind(name, arguments):
    """Bind MCP tool arguments exactly as the bridge + parser would."""
    fn, meta = _cmd(name)
    raw = _bridge_raw_args(fn, arguments)
    if meta.get("parser"):
        return meta["parser"](raw)
    import inspect
    params = [p for p in inspect.signature(fn).parameters.values() if p.name != "self"]
    positionals, flags = dc.ArgHelpers.parse_flags(list(raw))
    return tuple(positionals), dc.ArgHelpers.auto_parse_declared_flags(name, params, meta["args"], flags)


def test_profile_lookups(core):
    core.member_profile("123")
    core.member_events("123")
    assert [c[:2] for c in core.calls] == [("GET", "/profiles/123"), ("GET", "/profiles/123/events")]


def test_recent_trips(core):
    core.recent_trips(limit=5)
    assert core.calls[-1] == ("GET", "/trips/recent", {"limit": 5})


@pytest.mark.parametrize("action", ["read", "unread"])
def test_room_read_unread(core, action):
    getattr(core, f"room_{action}")("r1")
    assert core.calls[-1] == ("POST", f"/rooms/r1/{action}", {})


def test_room_filter_is_sent_and_validated(core):
    core.rooms(filter="pinned")
    assert core.calls[-1][2]["filter"] == "pinned"
    with pytest.raises(dc.UsageError):
        core.rooms(filter="starred")


def test_alert_create_sends_delivery_flags(core):
    core.create_alert("AI tools", notify_daily=False, notify_weekly=True)
    assert core.calls[-1] == ("POST", "/alerts", {
        "description": "AI tools", "notifyDaily": False, "notifyWeekly": True,
    })
    with pytest.raises(dc.UsageError):
        core.create_alert("AI tools", notify_daily=False, notify_weekly=False)


def test_mcp_false_reaches_alert_update():
    # An explicit false (turn the daily digest off) must survive the bridge.
    _pos, kwargs = _bind("alerts-update", {"alert_id": "a", "notify_daily": False, "notify_weekly": True})
    assert kwargs["notify_daily"] is False
    assert kwargs["notify_weekly"] is True


@pytest.mark.parametrize("name", ["search-rooms", "search-messages", "search-events"])
def test_user_only_search(core, name):
    method = getattr(core, name.replace("-", "_"))
    method(user_id="123")
    assert core.calls[-1][2]["userID"] == "123"
    with pytest.raises(dc.UsageError):
        method()


@pytest.mark.parametrize("name", ["search-rooms", "search-messages", "search-events"])
def test_user_only_search_binds_over_mcp(name):
    _pos, kwargs = _bind(name, {"user_id": "123"})
    assert kwargs["user_id"] == "123"
