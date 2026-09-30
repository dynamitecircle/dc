"""Headless, offline drives of the TUI against `FakeDC` — every section renders,
navigation works, and the actions hit the client with the right arguments."""
import asyncio
import os

import pytest

textual = pytest.importorskip("textual")

from textual.widgets import Button, DataTable, Tabs  # noqa: E402

from dc_tui.app import DCApp  # noqa: E402
from dc_tui.cache import DiskCache  # noqa: E402
from dc_tui.data import DataClient  # noqa: E402
from dc_tui.widgets import Panel  # noqa: E402
from fake_dc import FakeDC  # noqa: E402


def run(coro, timeout=90):
    """Each drive gets a hard ceiling so a stuck pilot fails instead of hanging CI."""
    return asyncio.run(asyncio.wait_for(coro, timeout))


def make_app(tmp_path):
    fake = FakeDC()
    app = DCApp(fake, data=DataClient(fake, cache=DiskCache(tmp_path / "cache")))
    return app, fake


SHOTS = os.environ.get("DC_TUI_SHOTS")  # directory: write an SVG per checkpoint


async def shot(app, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        app.save_screenshot(filename="%s.svg" % name, path=SHOTS)


def fid(app):
    f = app.focused
    return getattr(f, "id", None) or type(f).__name__


async def press(pilot, *keys):
    """`pilot.press` posts the keys, then waits on every widget — a widget being
    removed by the key's own handler (action buttons rebuilding) never answers."""
    try:
        await pilot.press(*keys)
    except Exception:  # noqa: BLE001 — WaitForScreenTimeout; keys were delivered
        pass


async def settle(pilot, seconds=0.8):
    """Let workers + remounts finish. A plain sleep first: `pilot.pause` waits on
    every widget in the tree, and one being removed mid-wait (action buttons
    rebuilding) never answers, which times the pilot out."""
    await asyncio.sleep(seconds)
    try:
        await pilot.pause()
    except Exception:  # noqa: BLE001 — WaitForScreenTimeout during a remount
        pass


def test_home_renders_cards_with_targets_and_deep_links(tmp_path):
    async def go():
        app, fake = make_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, 1.5)
            scr = app.screen
            cards = {p.id: p for p in scr.query(Panel)}
            inbox = cards["p-inbox"]
            assert inbox.targets and inbox.targets[0] == ("rooms", "r1")
            first = str(inbox.list._options[0].prompt)
            assert "Channel" in first and first.rstrip().endswith("2 new")
            assert "DCBKK 2026" in str(cards["p-tickets"].list._options[0].prompt) or any("DCBKK" in str(o.prompt) for o in cards["p-tickets"].list._options)
            assert any(t and t[0] == "person" for t in cards["p-locator"].targets)
            # Enter on the inbox row opens that room in Inbox
            inbox.list.focus(); inbox.first(); await settle(pilot, 0.2)
            await shot(app, "home")
            await press(pilot, "enter"); await settle(pilot, 1.5)
            assert type(app.screen).__name__ == "RoomsScreen"
            assert (app.screen._detail_item or {}).get("roomID") == "r1"
            assert ("room-messages", "r1") in fake.calls          # opening a room reads its messages
    run(go())


def test_section_bar_keyboard_and_back(tmp_path):
    async def go():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, 1.5)
            await press(pilot, "up"); await settle(pilot, 0.2)
            assert fid(app) == "nav-tabs"
            await press(pilot, "right"); await settle(pilot, 1.0)
            assert type(app.screen).__name__ == "RoomsScreen" and fid(app) == "nav-tabs"
            await press(pilot, "down"); await settle(pilot, 0.2)
            assert fid(app) == "list-tabs"
            await press(pilot, "escape"); await settle(pilot, 0.8)
            assert type(app.screen).__name__ == "HomeScreen"
    run(go())


def test_inbox_tabs_filter_chips_and_messages(tmp_path):
    async def go():
        app, fake = make_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, 1.0)
            await press(pilot, "2"); await settle(pilot, 1.5)
            scr = app.screen
            assert [r.get("roomID") for r in scr.items][0] == "r1"          # unread first
            assert scr.row_cells(scr.items[2])[0] == "Direct message"
            await pilot.click("#chip-unread"); await settle(pilot, 1.0)
            assert [r.get("roomID") for r in scr.items] == ["r1"]
            await pilot.click("#chip-show-all"); await settle(pilot, 1.0)
            assert len(scr.items) == 3
            scr.query_one("#list-tabs", Tabs).active = "dm"; await settle(pilot, 1.0)
            assert [r.get("type") for r in scr.items] == ["dm"]
            scr.query_one("#list-tabs", Tabs).active = "all"; await settle(pilot, 1.0)
            scr.query_one("#list", DataTable).focus(); await settle(pilot, 0.2)
            await press(pilot, "enter"); await settle(pilot, 1.5)
            await shot(app, "inbox-messages")
            assert [b.label.plain for b in scr.query("Button.action")][:4] == ["Mark read", "Mute", "Pin", "Archive"]
            await pilot.click("#act-pane-1"); await settle(pilot, 1.5)                    # Mute → Unmute
            assert ("room-mute", "r1") in fake.calls
            assert [b.label.plain for b in scr.query("Button.action")][1] == "Unmute"
            rows = list(scr.query(".detail-actions .action-row"))
            assert len([r for r in rows if r.display]) >= 2               # buttons wrap instead of running off the pane
            width = scr.detail_pane().size.width
            assert all(b.region.right <= scr.detail_pane().region.right for b in scr.query("Button.action") if b.display and b.region.width), width
            body = str(scr.query_one("#detail-body-pane").render())
            assert "replying to Simon" in body and "Hi all" in body and body.index("Simon") < body.index("Beatriz")
    run(go())


def test_events_tabs_detail_tabs_and_bookmark(tmp_path):
    async def go():
        app, fake = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await settle(pilot, 1.0)
            await press(pilot, "5"); await settle(pilot, 1.5)
            scr = app.screen
            assert [e["eventID"] for e in scr.items] == ["e-dcbkk", "e-dcbcn"]           # global tab
            assert scr.row_cells(scr.items[1])[-1] == "Jul 2027"                          # unconfirmed → month only
            table = scr.query_one("#list", DataTable)
            used = sum(c.get_render_width(table) for c in table.columns.values())
            assert used <= scr.main_pane().size.width, (used, scr._columns())              # date column never clipped
            scr.query_one("#list-tabs", Tabs).active = "local"; await settle(pilot, 1.0)
            assert [e["eventID"] for e in scr.items] == ["e-junto"]
            scr.query_one("#list-tabs", Tabs).active = "global"; await settle(pilot, 1.0)
            await press(pilot, "bracketright"); await settle(pilot, 1.5)                 # Schedule tab
            await shot(app, "events-schedule")
            assert scr.detail_tab == "schedule" and scr.detail_table().row_count >= 2
            table = scr.detail_table(); table.focus()
            table.move_cursor(row=table.get_row_index("session:s1")); await settle(pilot, 0.3)
            await press(pilot, "b"); await settle(pilot, 1.0)
            assert any(c[0] == "session-bookmark" and c[2] == "s1" for c in fake.calls)
            scr.query_one("#list-tabs", Tabs).active = "calls"; await settle(pilot, 1.0)
            assert "Community Welcome Call" in scr.detail_title(scr.items[0])
            scr.query_one("#list", DataTable).focus(); await press(pilot, "enter"); await settle(pilot, 1.0)
            assert [b.label.plain for b in scr.query("Button.action")][0] == "Going"
            await pilot.click("#act-pane-0"); await settle(pilot, 1.5)                    # mouse click on "Going"
            assert ("virtual-event-rsvp", "vc1", "yes") in fake.calls
            await shot(app, "events-calls")
            assert [b.label.plain for b in scr.query("Button.action")][0] == "Not going"
    run(go())


def test_search_all_and_type_tabs(tmp_path):
    async def go():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, 1.0)
            await press(pilot, "8"); await settle(pilot, 1.0)
            assert fid(app) == "search-query"
            for ch in "SaaS": await press(pilot, ch)
            await press(pilot, "enter"); await settle(pilot, 1.5)
            scr = app.screen
            await shot(app, "search")
            kinds = [i["_kind"] for i in scr.items]
            assert "profiles" in kinds and "rooms" in kinds and "messages" in kinds and "chapters" in kinds
            assert scr.row_cells([i for i in scr.items if i["_kind"] == "messages"][0])[0].endswith("hi")
            detail = str(scr.query_one("#detail-body-pane").render())
            assert "displayName:" not in detail and "Community" in detail      # a profile preview, not a key dump
            scr.query_one("#list-tabs", Tabs).active = "chapters"; await settle(pilot, 1.0)
            assert [i["_kind"] for i in scr.items] == ["chapters"]
    run(go())


def test_locator_page_rows_and_person_open(tmp_path):
    async def go():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(120, 44)) as pilot:
            await settle(pilot, 1.0)
            await press(pilot, "6"); await settle(pilot, 1.5)
            scr = app.screen
            await shot(app, "locator")
            cards = {p.id: p for p in scr.query(Panel)}
            rows = [str(o.prompt) for o in cards["l-home"].list._options]
            assert any("1 DCer coming to Osaka" in r for r in rows) and any("Harley" in r for r in rows)
            assert any("DC Tokyo Chapter" in str(o.prompt) for o in cards["l-cities"].list._options)
            people = [str(o.prompt) for o in cards["l-people"].list._options]
            assert any("Till Carlos is attending DCBKK 2026" in p for p in people)
            cards["l-home"].list.focus(); cards["l-home"].first(); await settle(pilot, 0.2)
            await press(pilot, "enter"); await settle(pilot, 1.5)
            assert type(app.screen).__name__ == "PeopleScreen" and (app.screen._detail_item or {}).get("displayName") == "Harley Green"
    run(go())


def test_me_screen_renders_profile_sections(tmp_path):
    async def go():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(120, 44)) as pilot:
            await settle(pilot, 1.0)
            await press(pilot, "9"); await settle(pilot, 1.5)
            scr = app.screen
            await shot(app, "me")
            text = "\n".join(str(o.prompt) for p in scr.query(Panel) for o in p.list._options)
            assert "Primary Business" in text and "announcement" in text and "webcal://x" in text
            assert "my tickets" in text and "MyTickets" not in text
    run(go())


@pytest.mark.parametrize("width", [72, 90])
def test_every_section_fits_narrow_terminals(tmp_path, width):
    """Graceful degradation: at phone-ish widths every section renders, list
    tables never overflow the pane (the date column stays visible), and an
    opened detail shows a visible ← Back button."""
    async def go():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(width, 40)) as pilot:
            await settle(pilot, 1.2)
            await shot(app, "w%d-home" % width)
            for key, name in (("2", "inbox"), ("3", "browse"), ("4", "trips"), ("5", "events"),
                              ("6", "locator"), ("7", "people"), ("9", "me")):
                await press(pilot, key); await settle(pilot, 1.2)
                scr = app.screen
                await shot(app, "w%d-%s" % (width, name))
                tables = [t for t in scr.query("#list") if isinstance(t, DataTable) and t.display]
                for table in tables:
                    used = sum(c.get_render_width(table) for c in table.columns.values())
                    assert used <= scr.main_pane().size.width, (name, used, list(table.columns))
                if name == "trips":
                    assert scr.row_cells(scr.items[0])[-1] == "03–10 Nov 2026"          # full date, last column
                if name in ("inbox", "events") and tables and scr.items:
                    tables[0].focus(); await press(pilot, "enter"); await settle(pilot, 1.2)
                    await shot(app, "w%d-%s-detail" % (width, name))
                    labels = [b.label.plain for b in scr.query("Button.action") if b.display]
                    assert labels and labels[0] == "← Back", labels
                    await press(pilot, "escape"); await settle(pilot, 0.6)
    run(go(), timeout=150)
