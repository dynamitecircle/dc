"""A DCer's profile as its own page, with the web profile's tabs the Member API
can fill: Profile (a header card, then one card per ProfileCore.vue section — the
Home screen's boxes), Messages, Threads and Events (what they posted, started,
created). Opened from anywhere a DCer appears (Following, Locator, Search, a
message author…); it is not part of any section."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual import work
from textual.containers import Horizontal
from textual.widgets import Button, OptionList, Static, Tab, Tabs

from .data import Fetched
from .events import event_flag
from .format import align_row, event_dates, fmt_date, guard_flags
from .labels import event_type_label, room_icon, room_title, room_type_label
from .listing import dict_of, esc, items_of, next_page
from .profile import SECTIONS, _val
from .screens import DCScreen, WEB_APP
from .widgets import Panel


def _profiles(f: Optional[Fetched]) -> List[dict]:
    data = dict_of(f) if f is not None else {}
    return [p for p in (data.get("profiles") or data.get("items") or []) if isinstance(p, dict)]


class ProfileScreen(DCScreen):
    SECTION = "profile"
    TITLE_TEXT = "Profile"
    HINT = ""
    URL = WEB_APP + "/members"
    HAS_DETAIL = False

    DEFAULT_CSS = """
    ProfileScreen #profile-tabs { height: 2; margin: 0 0 1 0; }
    ProfileScreen #profile-name { height: auto; padding: 0 1; margin: 0 0 1 0; }
    ProfileScreen #profile-actions { height: 1; margin: 0 0 1 0; }
    ProfileScreen #profile-actions Button { height: 1; width: auto; min-width: 0; border: none; padding: 0 1; margin: 0 1 0 0;
                                            background: $panel; color: $text; text-style: none; }
    ProfileScreen #profile-actions Button.back { background: $surface; color: $primary; }
    ProfileScreen #profile-actions Button:hover, ProfileScreen #profile-actions Button:focus {
        background: $block-cursor-background; color: $block-cursor-foreground; border: none; }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._member: Dict[str, Any] = {}
        self._profile: Dict[str, Any] = {}
        self._following: Optional[bool] = None
        self._tab = "profile"

    # ── entry point ──────────────────────────────────────────────────
    def show(self, member: dict) -> None:
        self._member = dict(member or {})
        self._profile = dict(self._member)
        self._following = None
        self._tab = "profile"
        self.sub_title = self._member.get("displayName") or "Profile"
        try:
            self.query_one("#profile-tabs", Tabs).active = "pt-profile"
        except Exception:  # noqa: BLE001
            pass
        self._render_all()
        self._show_tab()
        self._load(False)

    TABS = (("profile", "Profile"), ("messages", "Messages"), ("threads", "Threads"), ("events", "Events"))

    def populate(self) -> None:
        self.add_class("tabs-first")
        self.set_main(Tabs(*[Tab(label, id="pt-" + tid) for tid, label in self.TABS], id="profile-tabs"),
                      Static("", id="profile-name"),
                      Horizontal(Button("Follow", id="profile-follow"),
                                 Button("Send DM", id="profile-dm"),
                                 Button("Open Profile", id="profile-open"), id="profile-actions"),
                      *[Panel(title, id="pf-%d" % i) for i, (title, _) in enumerate(SECTIONS)],
                      Panel("", id="pf-list"))
        self.call_after_refresh(self._show_tab)
        if self._member:
            self.call_after_refresh(self._render_all)    # the cards' lists mount on the next refresh

    def refresh_data(self, force: bool = False) -> None:
        if self._member:
            self._load(force)

    @work(thread=True, exclusive=True, group="profile", exit_on_error=False)
    def _load(self, force: bool) -> None:
        data = self.app.data  # type: ignore[attr-defined]
        user_id = self._member.get("userID")
        full = data.fetch("dcer", user_id, force=force) if user_id and hasattr(data.dc, "dcer") else None
        follows = data.fetch("follows-profiles", force=force)
        self.app.call_from_thread(self._loaded, user_id, full, follows)

    def _loaded(self, user_id: Any, full: Optional[Fetched], follows: Fetched) -> None:
        if user_id != self._member.get("userID"):
            return                                  # another profile was opened meanwhile
        if full is not None and full.ok:
            body = dict_of(full)
            self._profile.update(body.get("profile") if isinstance(body.get("profile"), dict) else body)
        self._following = any(str(p.get("userID")) == str(user_id) for p in _profiles(follows))
        self._render_all(error=full.error if full is not None and not full.ok else "")

    # ── rendering ────────────────────────────────────────────────────
    def _render_all(self, error: str = "") -> None:
        p = self._profile
        try:
            head = self.query_one("#profile-name", Static)
            self.query_one("#pf-0", Panel).list           # noqa: B018 — raises until the cards' lists are mounted
        except Exception:  # noqa: BLE001 — not composed yet; populate renders again
            return
        name = p.get("displayName") or p.get("userName") or "DCer"
        lines = ["[b $primary]%s[/]" % esc(name)]
        if p.get("headline"):
            lines.append("[#C4C7CE]%s[/]" % esc(_val(p.get("headline"))))
        meta = []
        if p.get("joinedDate"):
            meta.append("Joined DC %s" % fmt_date(p.get("joinedDate")))
        if self._following:
            meta.append("★ you follow this DCer")
        if meta:
            lines.append("[dim]%s[/dim]" % " · ".join(meta))
        if error:
            lines.append("[$warning]%s[/]" % esc(error))
        head.update("\n".join(lines))
        for i, (title, fields) in enumerate(SECTIONS):
            try:
                panel = self.query_one("#pf-%d" % i, Panel)
            except Exception:  # noqa: BLE001
                continue
            rows = [(label, _val(p.get(key))) for label, key in fields]
            rows = [(label, value) for label, value in rows if value]
            panel.display = bool(rows) and self._tab == "profile"
            panel.set_lines([guard_flags("[dim]%s[/dim]  %s" % (label, esc(value))) for label, value in rows])
        try:
            self.query_one("#profile-follow", Button).label = "Unfollow" if self._following else "Follow"
        except Exception:  # noqa: BLE001
            pass

    # ── tabs: Messages / Threads / Events by this DCer ────────────────
    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if event.tabs.id != "profile-tabs" or event.tab is None:
            return
        event.stop()
        tab = str(event.tab.id or "").replace("pt-", "", 1)
        if tab != self._tab:
            self._tab = tab
            self._show_tab()

    def _show_tab(self) -> None:
        profile = self._tab == "profile"
        for panel in self.query(Panel):
            if panel.id == "pf-list":
                panel.display = not profile
            elif not profile:
                panel.display = False
        if profile:
            self._render_all()                     # re-applies which section cards have content
            return
        try:
            lst = self.query_one("#pf-list", Panel)
            lst.border_title = dict(self.TABS)[self._tab]
            lst.set_loading()
        except Exception:  # noqa: BLE001
            return
        if self._member.get("userID"):
            self._load_tab(self._tab, str(self._member.get("userID")))

    _SEARCH = {"messages": "search-messages", "threads": "search-rooms"}

    @work(thread=True, exclusive=True, group="profile-tab", exit_on_error=False)
    def _load_tab(self, tab: str, user_id: str, page: int = 1) -> None:
        data = self.app.data  # type: ignore[attr-defined]
        if tab == "events":
            fetched = data.fetch("dcer-events", user_id)          # what they attend, as the web's Events tab
        else:
            fetched = data.fetch(self._SEARCH[tab], "", user_id=user_id, limit=100, page=page)
        self.app.call_from_thread(self._tab_loaded, tab, user_id, fetched, page)

    # Messages / Threads page like every list: highlighting the last row loads the next page
    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.parent is None or getattr(event.option_list.parent, "id", "") != "pf-list":
            return
        if self._tab in self._SEARCH and getattr(self, "_next_page", None) and not getattr(self, "_paging", False) \
                and event.option_index >= event.option_list.option_count - 2:   # the last row above "more…"
            self._paging = True
            self._load_tab(self._tab, str(self._member.get("userID")), self._next_page)

    def _tab_loaded(self, tab: str, user_id: str, fetched: Fetched, page: int = 1) -> None:
        self._paging = False
        if tab != self._tab or user_id != str(self._member.get("userID")):
            return
        try:
            lst = self.query_one("#pf-list", Panel)
        except Exception:  # noqa: BLE001
            return
        if fetched.error and fetched.data is None:
            lst.set_lines(["[$warning]%s[/]" % esc(fetched.error)])
            return
        width = lst.row_width() or max(30, self.app.size.width - 8)
        name = self._profile.get("displayName") or "this DCer"
        if tab == "events":
            self._events_loaded(lst, dict_of(fetched), width, name)
            return
        hits = [h for h in (dict_of(fetched).get("hits") or []) if isinstance(h, dict)]
        if page == 1:
            self._hits = []
        self._hits = getattr(self, "_hits", []) + hits
        self._next_page = next_page(fetched, page)
        rows = [self._row(tab, h, width) for h in self._hits]
        empty = {"messages": "No messages from %s you can see.", "threads": "%s has not started a thread you can see."}[tab] % name
        if rows and self._next_page:
            rows.append(("[dim]↓ more…[/dim]", None))           # reaching it loads the next page
        keep = lst.list.highlighted if page > 1 else None
        lst.set_rows(rows or [("[dim]%s[/dim]" % esc(empty), None)], subtitle="%d" % len(self._hits) if self._hits else "")
        if keep is not None:
            lst.list.highlighted = min(keep, lst.list.option_count - 1)

    def _events_loaded(self, lst: Panel, body: dict, width: int, name: str) -> None:
        """ProfileEventsTab.vue: attending, past global events, past local meetups, also attended."""
        rows: List[tuple] = []
        groups = (("Attending", body.get("upcoming"), "No upcoming events."),
                  ("Past global events attended", body.get("pastEvents"), ""),
                  ("Past local meetups attended", body.get("pastMeetups"), ""))
        count = 0
        for title, events, empty in groups:
            events = [e for e in (events or []) if isinstance(e, dict)]
            if not events and not empty:
                continue
            if rows:
                rows.append(("", None))
            rows.append(("[b]%s[/b]" % title, None))
            if not events:
                rows.append(("[dim]%s[/dim]" % empty, None))
            for e in events:
                count += 1
                where = (e.get("city") or {}).get("name") if isinstance(e.get("city"), dict) else ""
                right = " · ".join(x for x in (where or "", event_dates(e)) if x)
                rows.append((align_row(width, e.get("name") or "Event", right, prefix=event_flag(e) + " ", name_markup="%s"),
                             ("events", str(e["eventID"])) if e.get("eventID") else None))
        also = [str(x) for x in (body.get("alsoAttended") or []) if x]
        if also:
            rows += [("", None), ("[b]Also attended[/b]", None), (esc(", ".join(also)), None)]
        if not rows:
            rows = [("[dim]%s has no events yet.[/dim]" % esc(name), None)]
        lst.set_rows(rows, subtitle="%d" % count if count else "")

    def _row(self, tab: str, h: dict, width: int):
        if tab == "messages":
            from .search import _title
            where = h.get("roomName") or ""
            when = fmt_date(h.get("sentAt") or h.get("createdAt"))
            target = ("rooms", str(h["roomID"])) if h.get("roomID") else None
            right = "%s · %s" % (where, when) if where and when else (where or when)   # the room sits with the date
            return (align_row(width, _title({**h, "_kind": "messages"}), right, prefix=room_icon(h) + " ", name_markup="%s"), target)
        if tab == "threads":
            when = fmt_date(h.get("lastActivityAt") or h.get("createdAt"))
            right = " · ".join(x for x in (room_type_label(h.get("type")), when) if x)   # the type sits with the date
            target = ("rooms", str(h["roomID"])) if h.get("roomID") else None
            return (align_row(width, room_title(h) or "Untitled", right, prefix=room_icon(h) + " ", name_markup="%s"), target)
        return ("", None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        card = event.option_list.parent
        target = card.target() if isinstance(card, Panel) else None
        if not target:
            return
        kind, key = target
        self.app.open_in_section(kind, key)  # type: ignore[attr-defined]

    # ── actions ──────────────────────────────────────────────────────
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "profile-dm":
            self._send_dm()
        elif bid == "profile-open":
            self.app.action_open_in_browser()  # type: ignore[attr-defined]
        elif bid == "profile-follow":
            self._toggle_follow()

    @work(thread=True, exclusive=True, group="profile-dm", exit_on_error=False)
    def _send_dm(self) -> None:
        """As the web's Send DM: open the existing direct message with this DCer.
        The Member API cannot start a new DM, so without one the web profile opens."""
        user_id = str(self._member.get("userID") or "")
        fetched = self.app.data.fetch("rooms", "dm", limit=100)  # type: ignore[attr-defined]
        room = next((r for r in items_of(fetched) if isinstance(r, dict) and str((r.get("participant") or {}).get("userID") or "") == user_id), None)
        self.app.call_from_thread(self._dm_found, room)

    def _dm_found(self, room: Optional[dict]) -> None:
        if room and room.get("roomID"):
            self.app.open_in_section("rooms", str(room["roomID"]))  # type: ignore[attr-defined]
            return
        self.notify("No DM with %s yet — start it from their web profile." % (self._profile.get("displayName") or "this DCer"),
                    timeout=6)
        self.app.action_open_in_browser()  # type: ignore[attr-defined]

    @work(thread=True, exclusive=True, group="profile-follow", exit_on_error=False)
    def _toggle_follow(self) -> None:
        user_id = self._member.get("userID")
        command = "unfollow-profile" if self._following else "follow-profile"
        done = self.app.data.mutate(command, user_id)  # type: ignore[attr-defined]
        self.app.call_from_thread(self._followed, done, command)

    def _followed(self, done: Fetched, command: str) -> None:
        if done.error:
            self.notify(done.error, severity="warning", timeout=5)
            return
        self._following = command == "follow-profile"
        self.notify("Following %s" % self._profile.get("displayName") if self._following else "Unfollowed", timeout=3)
        self._render_all()

    def current_url(self) -> str:
        user = self._profile.get("userName")
        return self._profile.get("profileURL") or ("%s/profile/%s" % (WEB_APP, user) if user else self.URL)
