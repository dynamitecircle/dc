"""Screens — one per section, all built on :class:`DCScreen`.

Phase 1 ships the shell: every section is reachable, responsive, and
shows real status; the Home screen already renders the unread inbox that
the background tick keeps warm. Phase 2 replaces the placeholders with
the real Rooms / Trips / Events / Live Calls screens; Phase 4 adds People
and Me.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple, Type

import webbrowser

from textual import events
from textual.binding import Binding
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, OptionList, Static, Tab, Tabs

from textual import work
from textual.containers import Vertical

from .data import Fetched
from .format import align_row, date_range, flag, fmt_date, pad, plural, rpad, strip_markdown, trunc
from .layout import MODES, layout_mode
from .widgets import Panel

WEB_APP = "https://dc.dynamitecircle.com"


class Section:
    __slots__ = ("id", "title", "hint", "url")

    def __init__(self, id: str, title: str, hint: str, url: str):
        self.id = id
        self.title = title
        self.hint = hint
        self.url = url


SECTIONS: List[Section] = [
    Section("home",   "Home",       "unread · announcements · tickets · trips · locator", WEB_APP + "/"),
    Section("rooms",  "Inbox",      "DMs · groups · channels · discussions · quick questions", WEB_APP + "/inbox"),
    Section("browse", "Browse",     "discover channels · discussions · quick questions",      WEB_APP + "/inbox/browse"),
    Section("trips",  "Trips",      "your trips · create/edit · who to meet",              WEB_APP + "/trips"),
    Section("events", "Events",     "global · local · live calls · schedule · my agenda",  WEB_APP + "/events"),
    Section("locator", "Locator",   "your city · followed cities · followed people · your trips", WEB_APP + "/locator"),
    Section("people", "People",     "profile match · follows",                             WEB_APP + "/members"),
    Section("search", "Search",     "people · rooms · messages · events · chapters",       WEB_APP + "/search"),
    Section("me",     "Me",         "profile · membership · notifications · calendar",     WEB_APP + "/profile"),
]


class StatusBar(Static):
    """One-line status: budget · tier · last refresh · unread · layout mode."""


class DCScreen(Screen):
    """Base screen: header, main + optional detail pane, status bar, footer."""

    AUTO_FOCUS = "#main"                  # page scroll with arrows; lists override with "#list"
    SECTION: str = "home"
    TITLE_TEXT: str = "DC"
    HINT: str = ""
    URL: str = WEB_APP

    BINDINGS = [
        Binding("up", "page_up", "Up", show=False, priority=True),
        Binding("down", "page_down", "Down", show=False, priority=True),
        Binding("pageup", "page_up_page", "Page up", show=False, priority=True),
        Binding("pagedown", "page_down_page", "Page down", show=False, priority=True),
        Binding("home", "page_home", "Top", show=False, priority=True),
        Binding("end", "page_end", "Bottom", show=False, priority=True),
    ]

    def _page(self, step: int, *, page: bool = False, edge: bool = False) -> None:
        """↑/↓ (and PageUp/PageDown, Home/End) on a plain page scroll it, even
        when focus sits on the section bar. Never wraps."""
        focused = self.focused
        pane = self.main_pane()
        if isinstance(focused, Tabs):
            if step < 0:
                return                      # ↑ on the bar stays on the bar
            pane.focus()
        elif focused is None:
            pane.focus()
        elif step < 0 and not page and not edge and pane.scroll_y <= 0:
            self.query_one("#nav-tabs", Tabs).focus()     # ↑ at the top of the page → bar
            return
        if edge:
            (pane.scroll_home if step < 0 else pane.scroll_end)(animate=False)
        elif page:
            (pane.scroll_page_up if step < 0 else pane.scroll_page_down)()
        else:
            (pane.scroll_up if step < 0 else pane.scroll_down)()

    def action_page_up(self) -> None:
        self._page(-1)

    def action_page_down(self) -> None:
        self._page(1)

    def action_page_up_page(self) -> None:
        self._page(-1, page=True)

    def action_page_down_page(self) -> None:
        self._page(1, page=True)

    def action_page_home(self) -> None:
        self._page(-1, edge=True)

    def action_page_end(self) -> None:
        self._page(1, edge=True)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Tabs(*[Tab(sec.title, id="nav-" + sec.id) for sec in SECTIONS], id="nav-tabs")
        with Horizontal(id="body"):
            yield VerticalScroll(id="main")
            yield VerticalScroll(id="detail")
        yield StatusBar("", id="status")
        yield Footer()

    # ── Layout ────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.sub_title = self.TITLE_TEXT
        self._sync_nav()
        self.set_layout_mode(layout_mode(self.app.size.width))
        self.populate()
        self.app.refresh_status()  # type: ignore[attr-defined]

    def _settle_focus(self) -> None:
        """Focus policy: the keyboard moves ONLY when a screen is shown or on an
        explicit key. If the user chose this section on the bar, they stay on the
        bar of the new screen; otherwise the content gets focus once. Deferred one
        refresh so it lands after Textual's own auto-focus."""
        app = self.app
        if getattr(app, "_focus_nav_next", False):
            app._focus_nav_next = False

            def _bar() -> None:
                try:
                    self.query_one("#nav-tabs", Tabs).focus()
                except Exception:  # noqa: BLE001
                    pass
            self.call_after_refresh(_bar)
        elif self.focused is None:
            self.call_after_refresh(self.focus_content)

    def _sync_nav(self) -> None:
        """Highlight this section in the nav bar without firing a navigation."""
        try:
            nav = self.query_one("#nav-tabs", Tabs)
        except Exception:  # noqa: BLE001
            return
        self._nav_syncing = True
        try:
            if nav.active != "nav-" + self.SECTION:
                nav.active = "nav-" + self.SECTION
        finally:
            self.call_after_refresh(setattr, self, "_nav_syncing", False)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tabs.id == "nav-tabs" and not getattr(self, "_nav_syncing", False) and event.tab is not None:
            section = str(event.tab.id or "").replace("nav-", "", 1)
            if section != self.SECTION:
                self.app._focus_nav_next = True   # chosen on the bar → stay on the bar
                self.app.action_goto_section(section)  # type: ignore[attr-defined]

    def on_screen_resume(self) -> None:
        self._sync_nav()
        self.set_layout_mode(layout_mode(self.app.size.width))
        self.app.refresh_status()  # type: ignore[attr-defined]
        self._settle_focus()

    def focus_content(self) -> None:
        """Put the keyboard on this screen's content (override in list screens)."""
        try:
            target = self.query_one(self.AUTO_FOCUS)
            target.focus()
        except Exception:  # noqa: BLE001
            pass

    def on_resize(self, event: events.Resize) -> None:
        self.app.apply_layout(event.size.width)  # type: ignore[attr-defined]

    #: Screens without a list/detail split (the Home dashboard) set this False.
    HAS_DETAIL: bool = True

    def set_layout_mode(self, mode: str) -> None:
        for other in MODES:
            self.remove_class(other)
        self.add_class(mode)
        try:
            self.detail_pane().display = bool(self.HAS_DETAIL and mode in ("split", "wide"))
        except Exception:  # noqa: BLE001 — not composed yet
            pass

    # ── Hooks for concrete screens ────────────────────────────────────

    def populate(self) -> None:
        """Fill ``#main`` (and ``#detail``) on first mount."""

    def refresh_data(self, force: bool = False) -> None:
        """Re-fetch this screen's data (``r``)."""

    def current_url(self) -> str:
        """What ``o`` opens — override to point at the selected item."""
        return self.URL

    # ── Helpers ───────────────────────────────────────────────────────

    def main_pane(self) -> VerticalScroll:
        return self.query_one("#main", VerticalScroll)

    def detail_pane(self) -> VerticalScroll:
        return self.query_one("#detail", VerticalScroll)

    def set_main(self, *widgets) -> None:
        pane = self.main_pane()
        pane.remove_children()
        pane.mount(*widgets)


class PlaceholderScreen(DCScreen):
    """A section whose real screen lands in a later phase."""

    @classmethod
    def for_section(cls, section: Section) -> Type["PlaceholderScreen"]:
        return type("%sScreen" % section.title.replace(" ", ""), (cls,), {
            "SECTION":    section.id,
            "TITLE_TEXT": section.title,
            "HINT":       section.hint,
            "URL":        section.url,
        })

    def populate(self) -> None:
        self.set_main(
            Static("[@click=app.back]← Back[/]", classes="muted"),
            Static(self.TITLE_TEXT, classes="section-title"),
            Static(self.HINT, classes="muted"),
            Static(""),
            Static("This screen is coming next. Press [b]o[/b] to open it in the web app, "
                   "[b]/[/b] for the command palette, [b]?[/b] for keys.", classes="muted"),
        )


class HomeScreen(DCScreen):
    """The one-glance dashboard: unread rooms, latest announcements, tickets +
    upcoming events, trips, the locator digest, and you.

    Six :class:`Panel` cards packed into 1 / 2 / 3 columns depending on the
    layout mode (compact / single+split / wide). Each card paints stale cached
    data instantly and refreshes behind it; staleness or an error shows in the
    card's subtitle, never as a traceback. Because Textual widgets cannot be
    re-parented, a column-count change rebuilds the cards and replays the last
    rendered content into them (no extra API calls).
    """

    SECTION = "home"
    TITLE_TEXT = "Home"
    HINT = SECTIONS[0].hint
    URL = SECTIONS[0].url
    HAS_DETAIL = False

    DEFAULT_CSS = """
    #home-grid { height: auto; }
    #home-grid > .home-col { width: 1fr; height: auto; }
    HomeScreen.wide #home-grid > #home-col-main { width: 3fr; margin: 0 1 0 0; }
    HomeScreen.wide #home-grid > #home-col-side { width: 2fr; }
    """

    #: One column up to 139 cols, read top-down in this order.
    ORDER_SINGLE = ["p-inbox", "p-announcements", "p-tickets", "p-trips", "p-locator", "p-me"]
    #: Wide terminals: content on the left, status on the right — grouped by
    #: what they are, not dealt out round-robin.
    ORDER_WIDE = {
        "home-col-main": ["p-announcements", "p-tickets", "p-trips"],
        "home-col-side": ["p-inbox", "p-locator", "p-me"],
    }

    PANELS: List[Tuple[str, str, Tuple[Tuple[str, ...], ...]]] = [
        # (panel id, title, commands the panel needs)
        ("p-inbox",         "Inbox",            (("inbox",),)),
        ("p-announcements", "Announcements",    (("announcements-latest",), ("rooms",))),
        ("p-tickets",       "Upcoming",         (("tickets",), ("events",), ("profile",), ("follows-chapters",))),
        ("p-trips",         "Trips",            (("trips",),)),
        ("p-locator",       "Locator",          (("locator",),)),
        ("p-me",            "Me",               (("profile",), ("membership",), ("limits",))),
    ]
    TITLES = {pid: title for pid, title, _ in PANELS}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._results: Dict[str, List[Fetched]] = {}   # last fetched data per card, re-rendered on relayout
        self._columns = 0

    # ── build / relayout ──────────────────────────────────────────────

    @staticmethod
    def _columns_for(mode: str) -> int:
        return 2 if mode == "wide" else 1

    def populate(self) -> None:
        self._build(self._columns_for(layout_mode(self.app.size.width)), then_fetch=True)

    def set_layout_mode(self, mode: str) -> None:
        super().set_layout_mode(mode)
        wanted = self._columns_for(mode)
        if not self._columns:
            return
        if wanted != self._columns:
            self._build(wanted)
        else:
            for pid, results in list(self._results.items()):
                self._render_into(pid, results)

    BINDINGS = [
        Binding("up", "card_up", "Up", show=False, priority=True),
        Binding("down", "card_down", "Down", show=False, priority=True),
        Binding("pageup", "card_page_up", "Page up", show=False, priority=True),
        Binding("pagedown", "card_page_down", "Page down", show=False, priority=True),
        Binding("home", "card_home", "Top", show=False, priority=True),
        Binding("end", "card_end", "Bottom", show=False, priority=True),
        Binding("enter", "open_row", "Open", show=False),
    ]

    def _cards(self) -> List[Panel]:
        return [p for p in self.query(Panel) if p.selectable()]

    def _focused_card(self) -> Optional[Panel]:
        focused = self.focused
        if isinstance(focused, OptionList) and isinstance(focused.parent, Panel):
            return focused.parent
        return None

    def focus_content(self) -> None:
        cards = self._cards()
        if cards:
            cards[0].first()
            cards[0].list.focus()
        else:
            self.main_pane().focus()      # cards still loading: first paint hands focus over

    def _jump(self, card: "Panel", *, last: bool = False) -> None:
        card.list.focus()
        (card.last if last else card.first)()
        card.scroll_visible()

    def _move(self, step: int) -> None:
        card = self._focused_card()
        cards = self._cards()
        if card is None:
            if isinstance(self.focused, Tabs):
                if step > 0 and cards:
                    self._jump(cards[0])          # ↓ from the bar enters the first card; ↑ stays
                return
            if cards:
                self._jump(cards[0] if step > 0 else cards[-1], last=step < 0)
            else:
                self._page(step)
            return
        if step < 0 and not card.at_first():
            card.list.action_cursor_up()
            return
        if step > 0 and not card.at_last():
            card.list.action_cursor_down()
            return
        i = cards.index(card) if card in cards else -1
        nxt = i + step
        if 0 <= nxt < len(cards):
            cards[nxt].list.focus()
            (cards[nxt].first if step > 0 else cards[nxt].last)()
            cards[nxt].scroll_visible()
        elif nxt < 0:
            self.query_one("#nav-tabs", Tabs).focus()

    def action_card_up(self) -> None:
        self._move(-1)

    def action_card_down(self) -> None:
        self._move(1)

    def _card_step(self, step: int) -> None:
        """PageUp/PageDown: previous / next card."""
        cards = self._cards()
        card = self._focused_card()
        if not cards:
            return
        i = cards.index(card) if card in cards else (-1 if step > 0 else len(cards))
        nxt = max(0, min(len(cards) - 1, i + step))
        self._jump(cards[nxt])

    def action_card_page_up(self) -> None:
        self._card_step(-1)

    def action_card_page_down(self) -> None:
        self._card_step(1)

    def action_card_home(self) -> None:
        cards = self._cards()
        if cards:
            self._jump(cards[0])

    def action_card_end(self) -> None:
        cards = self._cards()
        if cards:
            self._jump(cards[-1], last=True)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        card = event.option_list.parent
        if isinstance(card, Panel):
            self._open(card.target())

    def action_open_row(self) -> None:
        card = self._focused_card()
        if card is not None:
            self._open(card.target())

    def _open(self, target) -> None:
        if not target:
            return
        kind, key = target
        if kind == "url":
            webbrowser.open(str(key))
            self.app.notify("Opened in browser", timeout=2)
        elif kind == "person":
            self.app.open_person(key)  # type: ignore[attr-defined]
        else:
            self.app.open_in_section(kind, key)  # type: ignore[attr-defined]

    def _build(self, columns: int, then_fetch: bool = False) -> None:
        """(Re)build the column layout. Removal of the old cards is asynchronous
        in Textual, so the whole rebuild runs as an exclusive worker that awaits
        it before mounting cards with the same ids again."""
        self._columns = columns
        self.run_worker(self._rebuild(columns, then_fetch), group="home-build", exclusive=True)

    async def _rebuild(self, columns: int, then_fetch: bool) -> None:
        pane = self.main_pane()
        await pane.remove_children()
        row = Horizontal(id="home-grid")
        await pane.mount(row)
        if columns == 2:
            plan = [(Vertical(id=col_id, classes="home-col"), pids) for col_id, pids in self.ORDER_WIDE.items()]
        else:
            plan = [(Vertical(id="home-col-main", classes="home-col"), self.ORDER_SINGLE)]
        await row.mount(*[col for col, _ in plan])
        for col, pids in plan:
            for pid in pids:
                panel = Panel(self.TITLES[pid], id=pid)
                await col.mount(panel)
                if pid in self._results:
                    self._render_into(pid, self._results[pid])   # re-render for the new width
        if then_fetch:
            self.refresh_data(force=False)

    # ── data ──────────────────────────────────────────────────────────

    def refresh_data(self, force: bool = False) -> None:
        for pid, _, commands in self.PANELS:
            try:
                self.query_one("#%s" % pid, Panel).set_loading()
            except Exception:  # noqa: BLE001 — not composed yet
                continue
            self._fetch(pid, list(commands), force)

    def show_unread(self, fetched: Fetched) -> None:
        """The app-level tick keeps the inbox warm; repaint that card only."""
        self._render_into("p-inbox", [fetched])

    def current_url(self) -> str:
        return WEB_APP + "/inbox"

    @work(thread=True, group="home", exit_on_error=False)
    def _fetch(self, panel_id: str, commands: List[Tuple[str, ...]], force: bool) -> None:
        data = self.app.data  # type: ignore[attr-defined]
        results = [data.fetch(cmd[0], *cmd[1:], force=force) for cmd in commands]
        if panel_id == "p-announcements":
            # channels you are not subscribed to are not in the rooms list — look them up once (cached)
            known = {r.get("roomID") for r in _items(results[1])} if len(results) > 1 else set()
            for a in _dict(results[0]).get("announcements") or []:
                rid = _room_id_from_url(a) if isinstance(a, dict) else ""
                if rid and rid not in known:
                    known.add(rid)
                    results.append(data.fetch("room", rid))
        if all(r.error and r.data is None for r in results):
            self.app.call_from_thread(self._fail, panel_id, results[0].error or "failed")
        else:
            self.app.call_from_thread(self._render_into, panel_id, results)
        self.app.call_from_thread(self.app.refresh_status)  # type: ignore[attr-defined]

    # ── painting (UI thread) ──────────────────────────────────────────

    def _render_into(self, panel_id: str, results: List[Fetched]) -> None:
        self._results[panel_id] = results
        renderer = getattr(self, "_render_" + panel_id[2:])
        rows, subtitle = renderer(results)
        self._paint(panel_id, rows, subtitle)

    def _paint(self, panel_id: str, rows: List[Tuple[str, Any]], subtitle: str) -> None:
        try:
            panel = self.query_one("#%s" % panel_id, Panel)
        except Exception:  # noqa: BLE001 — card rebuilt mid-flight; replayed by _build
            return
        panel.set_rows(rows, subtitle=subtitle)
        if self.focused is None or self.focused is self.main_pane():
            self.call_after_refresh(self.focus_content)   # first paint only; never from the bar

    def _fail(self, panel_id: str, message: str) -> None:
        try:
            self.query_one("#%s" % panel_id, Panel).set_error(message)
        except Exception:  # noqa: BLE001
            pass

    def _compact(self) -> bool:
        return self.app.layout_mode_name == "compact"  # type: ignore[attr-defined]

    def _card_width(self) -> int:
        pane = self.main_pane().size.width or self.app.size.width
        width = pane - 6
        if self._columns == 2:
            width = (pane - 2) * 3 // 5 - 4
        try:
            panel_w = self.query_one("#p-inbox", Panel).size.width
            if panel_w > 10:
                width = panel_w - 4
        except Exception:  # noqa: BLE001
            pass
        return max(20, width - 1)

    # ── renderers: (results) -> (lines, subtitle) ─────────────────────

    def _render_inbox(self, results: List[Fetched]) -> Tuple[List[str], str]:
        f = results[0]
        rooms = sorted(_items(f), key=lambda r: -int(r.get("badgeCount") or 0))
        total = _extra(f).get("totalUnread")
        if total is None:
            total = sum(int(r.get("badgeCount") or 0) for r in rooms)
        width = self._card_width()
        rows = [("[b]%s[/b]  [b]%d[/b]  [dim]%s[/dim]" % (
                    _escape(trunc(r.get("roomName") or r.get("roomID", ""), max(12, width - 16))),
                    int(r.get("badgeCount") or 0),
                    r.get("roomType") or ""), ("rooms", r.get("roomID")))
                for r in rooms[:8]]
        return rows or [("all caught up [dim]— Enter opens your inbox[/dim]", ("rooms", None))], _subtitle(plural(int(total), "unread"), f)

    def _render_announcements(self, results: List[Fetched]) -> Tuple[List[str], str]:
        f, rooms_f = results[0], results[1] if len(results) > 1 else None
        data = _dict(f)
        items = [a for a in (data.get("announcements") or []) if isinstance(a, dict)]
        # the payload names the author, not the channel — resolve the channel from the URL's roomID
        names = {r.get("roomID"): r.get("name") for r in (_items(rooms_f) if rooms_f else []) if r.get("roomID")}
        for extra in results[2:]:                       # single-room lookups for unsubscribed channels
            room = _dict(extra).get("room") if isinstance(_dict(extra).get("room"), dict) else _dict(extra)
            if room.get("roomID") and room.get("name"):
                names[room["roomID"]] = room["name"]
        width = self._card_width()
        compact = self._compact()
        lines = []
        for a in items[:6]:
            who = _announcement_channel(a, names)
            text = strip_markdown(a.get("content"))
            when = fmt_date(a.get("createdAt"))
            target = ("url", a.get("shortURL") or a.get("announcementURL")) if (a.get("shortURL") or a.get("announcementURL")) else None
            if compact:
                lines.append((align_row(width, who, when) + "\n  " + _escape(trunc(text, max(20, width - 4))), target))
            else:
                head = "[dim]%s[/dim] [b]%s[/b]  " % (pad(when, 11), _escape(pad(who, 22)))
                lines.append((head + _escape(trunc(text, max(20, width - 11 - 22 - 3))), target))
        return lines or [("[dim]no announcements[/dim]", None)], _subtitle(plural(len(items), "channel"), f, *( [rooms_f] if rooms_f else [] ))

    def _render_tickets(self, results: List[Fetched]) -> Tuple[List[str], str]:
        """Upcoming, in the order that matters: events you hold a ticket for, then
        events in your home chapter and the chapters you follow, then the rest."""
        tickets_f, events_f, profile_f, chapters_f = results
        today = date.today().isoformat()
        tickets = [t for t in _items(tickets_f)
                   if t.get("status") in ("valid", "maybe") and str(t.get("endDate") or t.get("startDate") or "")[:10] >= today]
        tickets.sort(key=lambda t: str(t.get("startDate") or ""))
        events = sorted(_items(events_f), key=lambda e: str(e.get("startDate") or ""))
        profile = _dict(profile_f)
        home = profile.get("chapter") if isinstance(profile.get("chapter"), dict) else {}
        my_places = {home.get("placeID")} if home.get("placeID") else set()
        for c in _dict(chapters_f).get("chapters") or _items(chapters_f):
            if isinstance(c, dict):
                my_places.update(x for x in (c.get("cityID"), c.get("placeID")) if x)
        held = {t.get("eventID") for t in tickets}
        width = self._card_width()

        def row(prefix: str, name: str, start, end) -> str:
            return align_row(width, name, date_range(start, end), prefix=prefix, name_markup="%s")

        lines = []
        for t in tickets[:5]:
            lines.append((row("🎟 ", t.get("eventName") or "", t.get("startDate"), t.get("endDate")), ("events", t.get("eventID"))))
        near = [e for e in events if e.get("eventID") not in held
                and (e.get("city") or {}).get("placeID") in my_places] if my_places else []
        if near:
            lines.append(("[dim]near you — home + followed chapters[/dim]", None))
            for e in near[:5]:
                lines.append((row("   ", e.get("name") or "", e.get("startDate"), e.get("endDate")), ("events", e.get("eventID"))))
        near_ids = {e.get("eventID") for e in near[:5]}
        rest = [e for e in events if e.get("eventID") not in held and e.get("eventID") not in near_ids][:3]
        if rest:
            lines.append(("[dim]elsewhere[/dim]", None))
            for e in rest:
                lines.append((row("   ", e.get("name") or "", e.get("startDate"), e.get("endDate")), ("events", e.get("eventID"))))
        if not lines:
            lines.append(("[dim]nothing upcoming[/dim]", None))
        subtitle = plural(len(tickets), "ticket") + (" · %s near you" % plural(len(near), "event") if near else "")
        return lines, _subtitle(subtitle, tickets_f, events_f)

    def _render_trips(self, results: List[Fetched]) -> Tuple[List[str], str]:
        f = results[0]
        trips = _items(f)
        lines = []
        width = self._card_width()
        for t in trips[:6]:
            loc = t.get("location") if isinstance(t.get("location"), dict) else {}
            place = t.get("place") if isinstance(t.get("place"), dict) else {}
            name = loc.get("cityName") or loc.get("name") or place.get("name") or t.get("placeName") or "?"
            lines.append((align_row(width, name, date_range(t.get("startDate"), t.get("endDate")), t.get("note") or "", prefix="✈ "), ("trips", t.get("tripID"))))
        return lines or [("[dim]no upcoming trips[/dim] — Enter to plan one", ("trips", None))], _subtitle(plural(len(trips), "trip"), f)

    def _render_locator(self, results: List[Fetched]) -> Tuple[List[str], str]:
        """Who is coming to your city, what moves in the cities and people you follow —
        each row a person (opens their profile here) or a jump into the Locator."""
        f = results[0]
        digest = _dict(f)
        lines: List[Tuple[str, Any]] = []
        width = self._card_width()
        home = digest.get("homeCity") if isinstance(digest.get("homeCity"), dict) else {}
        city = home.get("cityName") or "your city"

        def member(row: dict) -> dict:
            m = row.get("member")
            return m if isinstance(m, dict) else row

        visitors = [t for t in (home.get("comingToCity") or []) + (home.get("planningToCity") or []) if isinstance(t, dict)]
        if visitors:
            lines.append(("[dim]🏠 coming to %s[/dim]" % _escape(city), None))
            for t in visitors[:4]:
                m = member(t)
                lines.append((align_row(width, m.get("displayName") or m.get("userName") or "DCer",
                                        date_range(t.get("startDate"), t.get("endDate")), prefix="   👤 "), ("person", m)))
        new = [m for m in home.get("newMembers") or [] if isinstance(m, dict)]
        for m in new[:3]:
            mm = member(m)
            lines.append((align_row(width, mm.get("displayName") or "DCer", "", "new in %s" % city, prefix="   👤 "), ("person", mm)))
        for c in [c for c in (digest.get("favoriteCities") or []) if isinstance(c, dict)][:3]:
            trips = [t for t in (c.get("comingTrips") or []) + (c.get("newTrips") or []) if isinstance(t, dict)]
            ev = len(c.get("comingEvents") or []) + len(c.get("newEvents") or [])
            bits = [b for b in ((plural(len(trips), "visitor") if trips else ""), (plural(ev, "event") if ev else "")) if b]
            lines.append(("[dim]%s %s · %s[/dim]" % (flag(c.get("countryCode")) or "★", _escape(c.get("cityName") or ""), " · ".join(bits) or "quiet"), ("locator", None)))
            for t in trips[:3]:
                m = member(t)
                lines.append((align_row(width, m.get("displayName") or "DCer", date_range(t.get("startDate"), t.get("endDate")), prefix="   👤 "), ("person", m)))
        people = digest.get("favoritePeople") if isinstance(digest.get("favoritePeople"), dict) else {}
        seen = set()
        moving = []
        for key in ("newTrips", "comingTrips", "attending"):
            for row in people.get(key) or []:
                m = member(row) if isinstance(row, dict) else {}
                if m.get("userID") and m["userID"] not in seen:
                    seen.add(m["userID"])
                    moving.append((m, row))
        if moving:
            lines.append(("[dim]♥ people you follow[/dim]", None))
            for m, row in moving[:4]:
                where = row.get("eventName") or (row.get("location") or {}).get("city") if isinstance(row.get("location"), dict) else row.get("eventName")
                lines.append((align_row(width, m.get("displayName") or "DCer", date_range(row.get("startDate"), row.get("endDate")), where or "", prefix="   👤 "), ("person", m)))
            if len(moving) > 4:
                lines.append(("   [dim]+%d more in the Locator[/dim]" % (len(moving) - 4), ("locator", None)))
        lines.append(("[dim]open the full Locator →[/dim]", ("locator", None)))
        return lines, _subtitle("Friday digest", f)

    def _render_me(self, results: List[Fetched]) -> Tuple[List[str], str]:
        profile_f, membership_f, limits_f = results
        profile, limits = _dict(profile_f), _dict(limits_f)
        m = _dict(membership_f).get("membership")
        m = m if isinstance(m, dict) else {}
        name = profile.get("displayName") or profile.get("userName") or "you"
        role = m.get("role") if isinstance(m.get("role"), dict) else {}
        billing = m.get("billing") if isinstance(m.get("billing"), dict) else {}
        dcb = m.get("dcBlack") if isinstance(m.get("dcBlack"), dict) else {}
        badge = "DC BLACK" if dcb.get("isMember") else (role.get("label") or str(limits.get("tier") or "").upper())
        renew = fmt_date(billing.get("currentPeriodEnd"))
        days = billing.get("daysTillRenewal")
        renew_txt = ("  · renews %s" % renew) if renew else ("  · renews in %s" % plural(int(days), "day") if isinstance(days, int) else "")
        chapter = profile.get("chapter") if isinstance(profile.get("chapter"), dict) else {}
        lines = [
            ("[b]%s[/b]  [dim]@%s[/dim]" % (_escape(str(name)), _escape(str(profile.get("userName") or ""))), ("me", None)),
            ("%s%s" % (badge, renew_txt), None),
            ("[dim]API %s/min · %s/day[/dim]" % (limits.get("perMinute", "?"), limits.get("perDay", "?")), None),
        ]
        return lines, _subtitle(("%s %s" % (flag(chapter.get("countryCode")), chapter.get("cityName") or "")).strip(), profile_f, membership_f, limits_f)


# ── pure helpers (testable without Textual) ──────────────────────────

def _room_id_from_url(a: dict) -> str:
    url = str(a.get("announcementURL") or a.get("shortURL") or "")
    return url.split("/channel/", 1)[1].split("/", 1)[0] if "/channel/" in url else ""


def _announcement_channel(a: dict, names: Dict[Any, Any]) -> str:
    """Channel name for an announcement: from the payload if it ever carries one,
    else the subscribed room whose ID appears in the announcement URL."""
    for key in ("channelName", "roomName", "channel"):
        if a.get(key):
            return str(a[key])
    url = str(a.get("announcementURL") or a.get("shortURL") or "")
    if "/channel/" in url:
        room_id = url.split("/channel/", 1)[1].split("/", 1)[0]
        if names.get(room_id):
            return str(names[room_id])
    return "Announcements"

def _items(fetched: Fetched) -> list:
    """The client wraps lists as `{items, count, cursor, has_more, extra}`."""
    data = fetched.data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [i for i in data["items"] if isinstance(i, dict)]
    return [i for i in data if isinstance(i, dict)] if isinstance(data, list) else []


def _extra(fetched: Fetched) -> dict:
    data = fetched.data
    extra = data.get("extra") if isinstance(data, dict) else None
    return extra if isinstance(extra, dict) else {}


def _dict(fetched: Fetched) -> dict:
    return fetched.data if isinstance(fetched.data, dict) else {}


def _subtitle(base: str, *fetched: Fetched) -> str:
    """`base` plus a freshness flag when any source is stale or failed."""
    worst = None
    for f in fetched:
        if f.error:
            worst = "⚠ " + trunc(f.error, 28)
            break
        if f.stale:
            worst = "stale %s" % _fmt_age(f.age)
    return "%s · %s" % (base, worst) if worst else base


def _fmt_age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm" % (seconds // 60)
    return "%dh" % (seconds // 3600)


def _escape(text: str) -> str:
    return str(text).replace("[", r"\[")
