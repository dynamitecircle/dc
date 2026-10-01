"""A DCer's profile as its own page, with the web profile's tabs the Member API
can fill: Profile (a header card, then one card per ProfileCore.vue section — the
Home screen's boxes), Messages, Threads and Events (what they posted, started,
created). Opened from anywhere a DCer appears (Following, Locator, Search, a
message author…); it is not part of any section."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual import work
from textual.containers import Horizontal
from textual.widgets import Button, OptionList, Tab, Tabs

from .data import Fetched
from .format import align_row, event_dates, fmt_date, guard_flags
from .labels import event_type_label, room_title, room_type_label
from .listing import dict_of, esc
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
    ProfileScreen #profile-actions { height: 1; margin: 0 0 1 0; }
    ProfileScreen #profile-actions Button { height: 1; min-width: 0; border: none; padding: 0 1; margin: 0 1 0 0;
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
                      Horizontal(Button("← Back", id="profile-back", classes="back"),
                                 Button("Follow", id="profile-follow"),
                                 Button("Open in app", id="profile-open"), id="profile-actions"),
                      Panel("Profile", id="pf-head"),
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
            head = self.query_one("#pf-head", Panel)
            head.list                              # noqa: B018 — raises until the card's list is mounted
        except Exception:  # noqa: BLE001 — not composed yet; populate renders again
            return
        name = p.get("displayName") or p.get("userName") or "DCer"
        nick = (" “%s”" % p.get("nickname")) if p.get("nickname") and p.get("nickname") != name else ""
        lines = ["[b]%s[/b]" % esc(nick.strip())] if nick else []   # the name is the card's title
        if p.get("headline"):
            lines.append(esc(_val(p.get("headline"))))
        if p.get("joinedDate"):
            lines.append("[dim]Joined DC %s[/dim]" % fmt_date(p.get("joinedDate")))
        if self._following is not None:
            lines.append("[dim]%s[/dim]" % ("★ you follow this DCer" if self._following else "not following"))
        if error:
            lines.append("[$warning]%s[/]" % esc(error))
        head.border_title = "👤 " + esc(name)
        head.display = self._tab == "profile"
        head.set_lines(lines)
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
            elif profile:
                if panel.id == "pf-head":
                    panel.display = True
            else:
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

    _SEARCH = {"messages": "search-messages", "threads": "search-rooms", "events": "search-events"}

    @work(thread=True, exclusive=True, group="profile-tab", exit_on_error=False)
    def _load_tab(self, tab: str, user_id: str) -> None:
        fetched = self.app.data.fetch(self._SEARCH[tab], "", user_id=user_id, limit=50)  # type: ignore[attr-defined]
        self.app.call_from_thread(self._tab_loaded, tab, user_id, fetched)

    def _tab_loaded(self, tab: str, user_id: str, fetched: Fetched) -> None:
        if tab != self._tab or user_id != str(self._member.get("userID")):
            return
        try:
            lst = self.query_one("#pf-list", Panel)
        except Exception:  # noqa: BLE001
            return
        if fetched.error and fetched.data is None:
            lst.set_lines(["[$warning]%s[/]" % esc(fetched.error)])
            return
        hits = [h for h in (dict_of(fetched).get("hits") or []) if isinstance(h, dict)]
        width = lst.row_width() or max(30, self.app.size.width - 8)
        name = self._profile.get("displayName") or "this DCer"
        rows = [self._row(tab, h, width) for h in hits]
        empty = {"messages": "No messages from %s you can see.", "threads": "%s has not started a discussion or question.",
                 "events": "%s has not created an event."}[tab] % name
        lst.set_rows(rows or [("[dim]%s[/dim]" % esc(empty), None)], subtitle="%d" % len(rows) if rows else "")

    def _row(self, tab: str, h: dict, width: int):
        if tab == "messages":
            from .search import _title
            where = h.get("roomName") or ""
            when = fmt_date(h.get("sentAt") or h.get("createdAt"))
            target = ("rooms", str(h["roomID"])) if h.get("roomID") else None
            right = "%s · %s" % (where, when) if where and when else (where or when)   # the room sits with the date
            return (align_row(width, _title({**h, "_kind": "messages"}), right, prefix="💬 ", name_markup="%s"), target)
        if tab == "threads":
            when = fmt_date(h.get("lastActivityAt") or h.get("createdAt"))
            target = ("rooms", str(h["roomID"])) if h.get("roomID") else None
            return (align_row(width, room_title(h) or "Untitled", when, room_type_label(h.get("type")), prefix="# ", name_markup="%s"), target)
        dates = event_dates({"startDate": h.get("startDate") or h.get("startAt"), "endDate": h.get("endDate") or h.get("endAt"),
                             "isDateConfirmed": h.get("isDateConfirmed")})
        target = ("events", str(h["eventID"])) if h.get("eventID") else None
        return (align_row(width, h.get("name") or h.get("title") or "Event", dates, event_type_label(h.get("eventType")),
                          prefix="📅 ", name_markup="%s"), target)

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
        if bid == "profile-back":
            self.app.action_back()  # type: ignore[attr-defined]
        elif bid == "profile-open":
            self.app.action_open_in_browser()  # type: ignore[attr-defined]
        elif bid == "profile-follow":
            self._toggle_follow()

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
