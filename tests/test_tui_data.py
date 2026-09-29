def test_align_row_fits_any_width_and_ends_with_the_date():
    from dc_tui.format import align_row, display_width
    import re
    strip = lambda s: re.sub(r"\[/?[^\]]*\]", "", s)
    for width in (30, 36, 48, 80, 120):
        row = strip(align_row(width, "Chonticha Hanon", "30 Oct – 15 Dec 2026", "Chiang Mai, Thailand", prefix="   "))
        assert display_width(row) == width, (width, row)
        assert row.endswith("30 Oct – 15 Dec 2026")                        # flush right
    narrow = strip(align_row(32, "Chonticha Hanon", "01–06 Oct 2026", "a very long place name"))
    assert "place" not in narrow and narrow.endswith("01–06 Oct 2026")   # extra dropped, date kept


"""Offline tests for the `dc tui` data layer — cache, rate budget, layout maths,
and the DataClient's stale-while-revalidate behaviour with a stub client.

No Textual import here: these run on the stdlib alone, on Python 3.9+.
"""
import sys

import pytest

from dc_tui.budget import RateBudget
from dc_tui.cache import DiskCache
from dc_tui.data import DataClient, INVALIDATES
from dc_tui.layout import layout_mode, pane_widths


class _Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class _StubDC:
    """Stands in for `dc.DC`: counts calls, can be told to fail."""

    def __init__(self):
        self.calls = []
        self.fail = False

    def trips(self, past=False, limit=50, cursor=None):
        self.calls.append(("trips", past))
        if self.fail:
            raise RuntimeError("boom")
        return {"items": [{"tripID": "t1"}], "count": 1}

    def limits(self):
        self.calls.append(("limits",))
        return {"tier": "dcb", "perMinute": 60, "perDay": 3000}

    def trip_delete(self, trip_id):
        self.calls.append(("trip-delete", trip_id))
        return {"ok": True}


@pytest.fixture
def client(tmp_path):
    clock = _Clock()
    dc = _StubDC()
    cache = DiskCache(tmp_path / "cache", clock=clock)
    api = DataClient(dc, cache=cache, budget=RateBudget(clock=clock), clock=clock)
    return api, dc, clock


# ── layout ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("width,mode", [(40, "compact"), (80, "compact"), (81, "single"),
                                        (99, "single"), (100, "split"), (139, "split"), (140, "wide"), (300, "wide")])
def test_layout_mode_breakpoints(width, mode):
    assert layout_mode(width) == mode


def test_pane_widths_sum_to_width():
    for width in (20, 80, 100, 140, 231):
        left, right = pane_widths(width)
        assert left + right == width
        assert right == 0 or right >= 40


# ── cache ─────────────────────────────────────────────────────────────

def test_cache_roundtrip_and_ttl(tmp_path):
    clock = _Clock()
    cache = DiskCache(tmp_path, clock=clock)
    key = DiskCache.key("trips", past=False)
    assert cache.get(key) is None
    cache.set(key, "trips", {"items": []})
    assert cache.get_fresh(key, "trips") is not None
    clock.t += cache.ttl_for("trips") + 1
    assert cache.get_fresh(key, "trips") is None          # stale …
    assert cache.get(key) is not None                     # … but still there


def test_cache_key_is_stable_and_filename_safe():
    a = DiskCache.key("event-schedule", "ev/1", limit=5)
    b = DiskCache.key("event-schedule", "ev/1", limit=5)
    assert a == b and "/" not in a and a.startswith("event-schedule.")
    assert DiskCache.key("event-schedule", "ev/2") != a


def test_cache_invalidate_by_command(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set(DiskCache.key("trips"), "trips", 1)
    cache.set(DiskCache.key("rooms"), "rooms", 2)
    assert cache.invalidate(["trips"]) >= 1
    assert cache.get(DiskCache.key("trips")) is None
    assert cache.get(DiskCache.key("rooms")) is not None


# ── budget ────────────────────────────────────────────────────────────

def test_budget_reads_headers_case_insensitively():
    clock = _Clock()
    b = RateBudget(clock=clock)
    b.observe_headers({"x-ratelimit-limit": "60", "X-RateLimit-Remaining": "12",
                       "X-RateLimit-Reset": str(int(clock.t) + 30), "X-RateLimit-Daily-Remaining": "2500"})
    snap = b.snapshot()
    assert snap["minute"]["limit"] == 60 and snap["minute"]["remaining"] == 12
    assert snap["day"]["remaining"] == 2500
    assert "12/60 min" in b.summary()


def test_budget_reserve_blocks_background_not_foreground():
    b = RateBudget(clock=_Clock())
    b.observe_headers({"X-RateLimit-Limit": "10", "X-RateLimit-Remaining": "2"})
    assert not b.can_spend(1, background=True)      # 20% reserve of 10 = 2
    assert b.can_spend(1, background=False)


def test_budget_poll_interval_slower_for_dcc_than_dcb():
    dcc, dcb = RateBudget(clock=_Clock()), RateBudget(clock=_Clock())
    dcc.observe_limits({"tier": "dcc", "perMinute": 10, "perDay": 300})
    dcb.observe_limits({"tier": "dcb", "perMinute": 60, "perDay": 3000})
    assert dcc.poll_interval() > dcb.poll_interval()
    assert dcb.poll_interval(idle_seconds=1200) > dcb.poll_interval()


# ── data client ───────────────────────────────────────────────────────

def test_fetch_uses_cache_then_refetches_when_stale(client):
    api, dc, clock = client
    first = api.fetch("trips")
    assert not first.from_cache and first.ok and first.data["count"] == 1
    second = api.fetch("trips")
    assert second.from_cache and not second.stale
    assert dc.calls.count(("trips", False)) == 1
    clock.t += api.cache.ttl_for("trips") + 1
    third = api.fetch("trips")
    assert not third.from_cache and dc.calls.count(("trips", False)) == 2


def test_fetch_falls_back_to_stale_on_error(client):
    api, dc, clock = client
    api.fetch("trips")
    clock.t += 10_000
    dc.fail = True
    fetched = api.fetch("trips")
    assert fetched.stale and fetched.error and fetched.data["count"] == 1


def test_fetch_error_without_cache_has_no_data(client):
    api, dc, _ = client
    dc.fail = True
    fetched = api.fetch("trips")
    assert fetched.data is None and not fetched.ok


def test_limits_feed_the_budget(client):
    api, _, _ = client
    api.fetch("limits")
    assert api.budget.snapshot()["tier"] == "dcb"
    assert api.budget.snapshot()["day"]["limit"] == 3000


def test_mutate_invalidates_dependent_reads(client):
    api, dc, _ = client
    api.fetch("trips")
    result = api.mutate("trip-delete", "t1")
    assert result.ok and ("trip-delete", "t1") in dc.calls
    assert "trips" in INVALIDATES["trip-delete"]
    assert api.fetch("trips").from_cache is False        # cache was dropped


def test_unknown_command_is_an_error_not_a_crash(client):
    api, _, _ = client
    fetched = api.fetch("no-such-command")
    assert not fetched.ok and "no command" in fetched.error


# ── entry point ───────────────────────────────────────────────────────

def test_run_tui_prints_install_hint_without_textual(monkeypatch, capsys):
    import dc
    monkeypatch.setitem(sys.modules, "textual", None)      # make `import textual` fail
    import dc_tui
    assert dc_tui.run(dc.DC, []) == 1
    assert "dynamitecircle[tui]" in capsys.readouterr().err


def test_dc_main_routes_tui_subcommand(monkeypatch):
    import dc
    seen = {}
    monkeypatch.setattr(dc.DC, "run_tui", lambda self, argv=None: (seen.__setitem__("argv", list(argv)), 0)[1])
    monkeypatch.setattr(sys, "argv", ["dc", "tui", "--clear-cache"])
    assert dc.main() == 0 and seen["argv"] == ["--clear-cache"]


def test_tui_is_not_an_mcp_tool():
    """`tui` is a CLI-only built-in — it must never be registered as a command."""
    import dc
    assert "tui" not in dc.DC()._commands


# ── formatting ────────────────────────────────────────────────────────

def test_strip_markdown_flattens_announcement_bodies():
    from dc_tui.format import strip_markdown
    raw = "**Traveling soon? Post Your Trip!**\n[![](https://dc.mba/x)](https://dc.mba/x)\n_Add_ your [trip](https://dc.mba/t) `now`"
    assert strip_markdown(raw) == "Traveling soon? Post Your Trip! Add your trip now"
    assert strip_markdown(None) == ""


def test_run_help_and_clear_cache_paths(monkeypatch, capsys, tmp_path):
    """The entry point's non-app paths must import cleanly (the app itself needs a terminal)."""
    import dc
    import dc_tui
    monkeypatch.setenv("DC_CACHE_DIR", str(tmp_path))
    assert dc_tui.run(dc.DC, ["--help"]) == 0
    assert "usage: dc tui" in capsys.readouterr().out
    dc_tui.clear_cache()
    assert "cleared" in capsys.readouterr().err


# ── screen helpers (pure functions, no Textual app needed) ────────────

def test_listing_plain_strips_html_and_collapses_whitespace():
    pytest.importorskip("textual")
    from dc_tui.listing import plain
    assert plain("<p>Hello&nbsp;<b>world</b></p>\n\n  again", True) == "Hello world again"
    assert plain("  a   b ") == "a b"


def test_events_time_and_day_helpers():
    pytest.importorskip("textual")
    from dc_tui.events import _day_label, _hhmm, _is_global
    assert _hhmm("2026-10-22T09:30:00+07:00") == "09:30"
    assert _hhmm("14:05") == "14:05"
    assert _hhmm(None) == ""
    assert _day_label("2026-10-22") == "Thursday Oct 22"
    assert _day_label("") == "undated"


def test_people_flatten_search_hit():
    pytest.importorskip("textual")
    from dc_tui.people import _flatten
    assert _flatten({"profile": {"userID": "1", "displayName": "A"}, "score": 0.9})["_score"] == 0.9
    assert _flatten({"userID": "2"})["userID"] == "2"


def test_every_section_has_a_real_screen():
    pytest.importorskip("textual")
    from dc_tui.app import SCREEN_CLASSES
    from dc_tui.screens import SECTIONS
    assert {s.id for s in SECTIONS} == set(SCREEN_CLASSES)


def test_events_global_vs_local_split():
    pytest.importorskip("textual")
    from dc_tui.events import _is_global
    assert _is_global({"eventType": "dcbkk"}) and _is_global({"eventType": "dc-black"})
    assert not _is_global({"eventType": "junto"}) and not _is_global({"eventType": "dc-chapter-event"})


def test_trunc_and_pad_are_cell_aware():
    from dc_tui.format import display_width, pad, rpad, trunc
    assert display_width("🗺 Trip") == 7                      # emoji = 2 columns + space + 4
    assert display_width(trunc("🗺 Traveling soon", 8)) <= 8
    assert display_width(pad("日本", 6)) == 6 and rpad("Sep 29", 8) == "  Sep 29"


def test_dates_are_zero_padded_with_year():
    from dc_tui.format import date_range, fmt_date
    assert fmt_date("2026-10-06") == "06 Oct 2026" and fmt_date("2026-09-28T10:00:00Z") == "28 Sep 2026"
    assert date_range("2026-10-22", "2026-10-25") == "22–25 Oct 2026"
    assert date_range("2027-03-02", "2027-03-04") == "02–04 Mar 2027"
    assert date_range("2026-09-30", "2026-10-02") == "30 Sep – 02 Oct 2026"
    assert date_range("2026-12-21", "2027-01-06") == "21 Dec 2026 – 06 Jan 2027"


def test_locator_grouping_helpers():
    pytest.importorskip("textual")
    from dc_tui.locator import _group_by_event, _group_by_member, _name_list
    a, b = {"userID": "1", "displayName": "Ann"}, {"userID": "2", "displayName": "Bo"}
    groups = _group_by_member([{"tripID": "t2", "member": a, "startDate": "2026-11-01"},
                               {"tripID": "t1", "member": a, "startDate": "2026-10-01"},
                               {"tripID": "t3", "member": b, "startDate": "2026-09-15"},
                               {"tripID": "t1", "member": a, "startDate": "2026-10-01"}])   # duplicate tripID dropped
    assert [g["member"]["userID"] for g in groups] == ["2", "1"]            # earliest trip first
    assert [t["tripID"] for t in groups[1]["trips"]] == ["t1", "t2"]
    ev = _group_by_event([{"eventID": "e", "eventName": "DCBKK", "member": a}, {"eventID": "e", "eventName": "DCBKK", "member": b},
                          {"eventID": "e", "eventName": "DCBKK", "member": a}])
    assert ev[0]["count"] == 2
    assert _name_list(["A"]) == "A" and _name_list(["A", "B"]) == "A and B"
    assert _name_list(list("ABCDEFGH")) == "A, B, C, D, E and 3 others"


def test_announcement_channel_resolves_from_url():
    pytest.importorskip("textual")
    from dc_tui.screens import _announcement_channel
    a = {"announcementURL": "https://dc.dynamitecircle.com/channel/yUoLEhfJb4JSJptyZ1O6/message/TBK"}
    assert _announcement_channel(a, {"yUoLEhfJb4JSJptyZ1O6": "DC Announcements"}) == "DC Announcements"
    assert _announcement_channel(a, {}) == "Announcements"
    assert _announcement_channel({"channelName": "DCBKK Announcements"}, {}) == "DCBKK Announcements"


def test_reply_prefix_is_split_out():
    pytest.importorskip("textual")
    from dc_tui.rooms import _split_reply
    assert _split_reply("▌ Replying to Sharif ElKomi in SaaS The app generates reports") == ("The app generates reports", "Sharif ElKomi")
    assert _split_reply("plain message") == ("plain message", None)




def test_flag_from_country_code():
    from dc_tui.format import flag
    assert flag("JP") == "\U0001F1EF\U0001F1F5" and flag("th") == "\U0001F1F9\U0001F1ED"
    assert flag("") == "" and flag("X1") == "" and flag(None) == ""
