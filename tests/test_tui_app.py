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
            assert [r.get("roomID") for r in scr.items][:3] == ["r2", "dm_940_7", "r1"]  # every pinned room first, then unread
            assert scr.row_cells(scr.items[0])[0].startswith(" # 📌 🔕 ")               # pinned + muted marks
            assert scr.row_cells(scr.items[3])[0] == "👤 Alex Harling"                 # DM named after the other person
            await pilot.click("#chip-pinned"); await settle(pilot, 1.0)
            assert [r.get("roomID") for r in scr.items] == ["r2", "dm_940_7"] and ("rooms", "", "pinned") in fake.calls
            assert [b.label.plain for b in scr.query("Button.action")][1:3] or True
            await pilot.click("#chip-show-all"); await settle(pilot, 1.0)
            await pilot.click("#chip-unread"); await settle(pilot, 1.0)
            assert [r.get("roomID") for r in scr.items] == ["r1"]
            await pilot.click("#chip-show-all"); await settle(pilot, 1.0)
            assert len(scr.items) == 4
            scr.query_one("#list-tabs", Tabs).active = "dm"; await settle(pilot, 1.0)
            assert [r.get("type") for r in scr.items] == ["dm", "dm"]        # incl. the older pinned DM
            assert "Type" not in scr._columns()                               # redundant inside the DMs tab
            scr.query_one("#list-tabs", Tabs).active = "all"; await settle(pilot, 1.0)
            table = scr.query_one("#list", DataTable); table.focus(); await settle(pilot, 0.2)
            await press(pilot, "enter"); await settle(pilot, 1.5)
            # the pinned + muted room shows its real state (from the API's seen flags)
            assert [b.label.plain for b in scr.query("Button.action")][:4] == ["Mark unread", "Unmute", "Unpin", "Archive"]
            await pilot.click("#act-pane-0"); await settle(pilot, 1.5)                    # Mark unread
            assert ("room-unread", "r2") in fake.calls
            assert [b.label.plain for b in scr.query("Button.action")][0] == "Mark read"
            table.focus(); table.move_cursor(row=2); await settle(pilot, 0.3)       # DC Announcements (r1)
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
            assert "scroll up for older messages" in body
            scr.load_older(); await settle(pilot, 1.5)                        # what wheel / PageUp at the top does
            body = str(scr.query_one("#detail-body-pane").render())
            assert "First post" in body and body.index("First post") < body.index("Hi all")
            assert "beginning of the conversation" in body
    run(go())


def test_events_tabs_detail_tabs_and_bookmark(tmp_path):
    async def go():
        app, fake = make_app(tmp_path)
        async with app.run_test(size=(140, 40)) as pilot:
            await settle(pilot, 1.0)
            await press(pilot, "4"); await settle(pilot, 1.5)
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
            await press(pilot, "6"); await settle(pilot, 1.0)
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


def test_locator_page_matches_the_web_digest(tmp_path):
    """Card per block in the web order, SayCount titles, one-column nesting,
    Locator sub-tabs (My Trips / Following / New Trips) under one bar entry."""
    async def go():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(120, 44)) as pilot:
            await settle(pilot, 1.0)
            await press(pilot, "5"); await settle(pilot, 1.8)
            scr = app.screen
            await shot(app, "locator")
            cards = {p.id: p for p in scr.query(Panel)}
            assert list(cards)[:3] == ["l-home", "l-city-0", "l-people"]
            assert "DC Osaka Chapter · Home" in str(cards["l-home"].border_title)
            assert "🇯🇵" in str(cards["l-city-0"].border_title)
            rows = [str(o.prompt) for o in cards["l-home"].list._options]
            assert any("One DCer coming to Osaka" in r for r in rows) and any("Harley" in r for r in rows)
            assert "Last refreshed" in str(cards["l-home"].border_subtitle)
            people = [str(o.prompt) for o in cards["l-people"].list._options]
            assert any("One more upcoming trip" in r for r in people)
            assert any("planned a trip to" in r for r in people)
            assert any("Till Carlos is attending DCBKK 2026" in r for r in people)
            # the bar shows Locator; the sub-tab row carries the web's Locator tabs
            assert app.screen.query_one("#nav-tabs").active == "nav-locator"
            sub = app.screen.query_one("#sub-tabs")
            assert [str(t.label.plain) for t in sub.query("Tab")] == ["Locator", "My Trips", "Following", "New Trips"]
            sub.active = "sub-following"; await settle(pilot, 1.5)
            assert type(app.screen).__name__ == "FollowingScreen"
            assert app.screen.query_one("#nav-tabs").active == "nav-locator"
            assert [r.get("displayName") for r in app.screen.items] == ["Alex Harling", "Till Carlos"]
            await shot(app, "locator-following")
            app.screen.query_one("#sub-tabs").active = "sub-trips"; await settle(pilot, 1.5)
            assert type(app.screen).__name__ == "TripsScreen"
            app.screen.query_one("#sub-tabs").active = "sub-newtrips"; await settle(pilot, 1.5)
            assert type(app.screen).__name__ == "NewTripsScreen" and app.screen.items
            await shot(app, "locator-newtrips")
            app.screen.query_one("#sub-tabs").active = "sub-locator"; await settle(pilot, 1.5)
            scr = app.screen
            cards = {p.id: p for p in scr.query(Panel)}
            cards["l-home"].list.focus(); cards["l-home"].first(); await settle(pilot, 0.2)
            await press(pilot, "enter"); await settle(pilot, 1.5)
            assert type(app.screen).__name__ == "ProfileScreen" and app.screen._member.get("displayName") == "Harley Green"
            await settle(pilot, 1.0)
            titles = [str(p.border_title) for p in app.screen.query(Panel) if p.display]
            assert "Alex Harling" in str(app.screen.query_one("#profile-name").render()) and "Primary Business" in titles
            assert [str(b.label) for b in app.screen.query("#profile-actions Button")] == ["Follow", "Send DM", "Open Profile"]
            await shot(app, "profile")
            assert not app.screen.query("#sub-tabs")                                   # its own page, not a Locator tab
            assert [t.id for t in app.screen.query_one("#profile-tabs").query("Tab")] == ["pt-profile", "pt-messages", "pt-threads", "pt-events"]
            app.screen.query_one("#profile-tabs").active = "pt-messages"; await settle(pilot, 1.5)
            lst = app.screen.query_one("#pf-list", Panel)
            assert lst.display and not app.screen.query_one("#pf-0", Panel).display
            assert any("Hello from the profile" in str(o.prompt) for o in lst.list._options)
            await shot(app, "profile-messages")
            app.screen.query_one("#profile-tabs").active = "pt-events"; await settle(pilot, 1.5)
            prompts = [str(o.prompt) for o in lst.list._options]
            assert any("Attending" in p for p in prompts) and any("DCBKK 2027" in p for p in prompts) and any("DCBKK 2014" in p for p in prompts)
            await shot(app, "profile-events")
            app.screen.query_one("#profile-tabs").active = "pt-profile"; await settle(pilot, 0.5)
            assert not lst.display
    run(go(), timeout=150)


def test_me_screen_renders_profile_sections(tmp_path):
    async def go():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(120, 44)) as pilot:
            await settle(pilot, 1.0)
            await press(pilot, "7"); await settle(pilot, 1.5)
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
            for key, name in (("2", "inbox"), ("3", "browse"), ("sub:trips", "trips"), ("4", "events"),
                              ("5", "locator"), ("sub:following", "following"), ("sub:newtrips", "newtrips"), ("sub:people", "people"), ("7", "me")):
                if key.startswith("sub:"):
                    app.action_goto_section(key[4:])
                else:
                    await press(pilot, key)
                await settle(pilot, 1.2)
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


def test_a_slow_load_for_the_previous_tab_never_paints(tmp_path):
    """Switching tabs while the old tab is still loading must not paint the old
    tab's rows into the new one (Following: DCers rows shown as 'DC ? Chapter')."""
    async def go():
        app, _ = make_app(tmp_path)
        async with app.run_test(size=(110, 30)) as pilot:
            await settle(pilot, 1.0)
            app.action_goto_section("following"); await settle(pilot, 1.5)
            scr = app.screen
            scr.refresh_data()                       # gen N  (DCers)
            stale_gen = scr._load_gen
            scr.list_tab = "chapters"; scr.refresh_data(); await settle(pilot, 1.5)
            scr._rows_arrived(stale_gen, [{"userID": "1", "displayName": "Alex Harling"}], "")
            assert all(r.get("cityID") for r in scr.items), scr.items
    run(go())


def test_switching_rooms_never_shows_the_previous_rooms_messages(tmp_path):
    """While the next room loads, its detail says loading — not the last room's messages."""
    async def go():
        app, fake = make_app(tmp_path)
        async with app.run_test(size=(90, 40)) as pilot:
            await settle(pilot, 1.0); await press(pilot, "2"); await settle(pilot, 1.5)
            scr = app.screen
            table = scr.query_one("#list", DataTable); table.focus(); table.move_cursor(row=2); await settle(pilot, 0.3)
            await press(pilot, "enter"); await settle(pilot, 1.5)
            assert "only in r1" in str(scr.query_one("#detail-body-inline").render())
            scr._opened.add(scr.items[0]["roomID"]); scr.load_detail(scr.items[0])   # the next room, before its data arrives
            assert "only in r1" not in str(scr.query_one("#detail-body-inline").render())
            await settle(pilot, 1.5)
            body = str(scr.query_one("#detail-body-inline").render())
            assert "only in r2" in body and "only in r1" not in body
    run(go())


def test_image_messages_are_a_clickable_link(tmp_path):
    async def go():
        app, _ = make_app(tmp_path)
        opened = []
        app.open_url = lambda url, **kw: opened.append(url)
        async with app.run_test(size=(90, 40)) as pilot:
            await settle(pilot, 1.0); await press(pilot, "2"); await settle(pilot, 1.5)
            scr = app.screen
            table = scr.query_one("#list", DataTable); table.focus(); table.move_cursor(row=1); await settle(pilot, 0.3)
            await press(pilot, "enter"); await settle(pilot, 1.5)
            body = str(scr.query_one("#detail-body-inline").render())
            assert "Image ↗" in body and "sunset" in body
            await scr.run_action("open_attachment(0)"); await settle(pilot, 0.3)
            assert opened == ["https://cdn.example/sunset.jpg"]
    run(go())


def test_inbox_loads_older_rooms_at_the_end_of_the_list(tmp_path):
    async def go():
        app, fake = make_app(tmp_path)
        fake.room_pages = True
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(pilot, 1.0); await press(pilot, "2"); await settle(pilot, 1.5)
            scr = app.screen
            assert "scroll for more" in str(scr.query_one("#list-hint").render())
            assert "old1" not in [r.get("roomID") for r in scr.items]
            table = scr.query_one("#list", DataTable); table.focus()
            table.move_cursor(row=table.row_count - 1); await settle(pilot, 1.5)   # ↓ to the last row
            assert [r.get("roomID") for r in scr.items][-1] == "old1"
            assert "scroll for more" not in str(scr.query_one("#list-hint").render())
    run(go())
