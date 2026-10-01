"""Browse — discover public rooms you are not in yet: Channels, Discussions
and Quick Questions (the web's /inbox/browse). Subscribe from the detail."""
from __future__ import annotations

from typing import Any, List, Tuple

from .data import Fetched
from .format import fmt_date, plural
from .labels import room_type_label
from .listing import ListDetailScreen, dict_of, esc, items_of, plain
from .screens import WEB_APP


class BrowseScreen(ListDetailScreen):
    SECTION = "browse"
    TITLE_TEXT = "Browse"
    HINT = "↑↓ pick a room · Enter shows it · Subscribe adds it to your Inbox"
    URL = WEB_APP + "/inbox/browse"
    LIST_TABS = (("channel", "Channels"), ("discussion", "Discussions"), ("quick-question", "Quick Questions"))
    COLUMNS = ("Room", "Members", "Activity")
    COLUMNS_COMPACT = ("Room", "Activity")
    COLUMN_WIDTHS = {"Members": 8, "Activity": 11}
    EMPTY_TEXT = "nothing to discover in this type right now"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._mine = set()

    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        mine = data.fetch("rooms", force=force)
        self._mine = {r.get("roomID") for r in items_of(mine)}
        fetched = data.fetch("browse-rooms", self.list_tab, limit=50, force=force)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        rooms = items_of(fetched)
        rooms.sort(key=lambda r: str(r.get("lastActivityAt") or ""), reverse=True)
        return rooms

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("roomID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        name = str(item.get("name") or item.get("roomID") or "")
        if item.get("roomID") in self._mine:
            name = "✓ " + name
        cells = {"Room": name, "Members": str(stats.get("subscribers") or ""), "Activity": fmt_date(item.get("lastActivityAt"))}
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        label = {"channel": "channels", "discussion": "discussions", "quick-question": "quick questions"}[self.list_tab]
        return "%d %s  [dim]%s · ✓ = already in your Inbox[/dim]" % (len(self.items), label, self.HINT)

    def detail_actions(self):
        item = self._detail_item or {}
        if item.get("roomID") in self._mine:
            return [("Open in Inbox", "open_in_inbox"), ("Unsubscribe", "unsubscribe"), ("Open on web", "app.open_in_browser")]
        return [("Subscribe", "subscribe"), ("Open on web", "app.open_in_browser")]

    def detail_title(self, item: dict) -> str:
        return "%s  [dim]%s%s[/dim]" % (esc(item.get("name")), room_type_label(item.get("type")), " · DC BLACK" if item.get("scope") == "dcb" else "")

    def fetch_detail(self, item: dict, force: bool) -> Any:
        return self.app.data.fetch("room", item.get("roomID"), force=force)  # type: ignore[attr-defined]

    def render_detail(self, item: dict, data: Any) -> List[str]:
        lines: List[str] = []
        desc = plain(item.get("description"))
        if desc:
            lines.append(esc(desc[:600]))
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        bits = [plural(int(stats.get("subscribers") or 0), "member"), plural(int(stats.get("comments") or 0), "message")]
        if item.get("lastActivityAt"):
            bits.append("last activity %s" % fmt_date(item.get("lastActivityAt")))
        lines.append("[dim]%s[/dim]" % " · ".join(bits))
        room = dict_of(data)
        weekly = room.get("aiSummaryWeekly") if isinstance(room.get("aiSummaryWeekly"), dict) else None
        if weekly and plain(weekly.get("html"), True):
            lines.append("")
            lines.append("[b]This week[/b]  [dim]%s msgs · %s people[/dim]" % (weekly.get("messageCount", "?"), weekly.get("participantCount", "?")))
            lines.append(esc(plain(weekly.get("html"), True)[:700]))
        if data is not None and getattr(data, "error", None):
            lines.append("[$warning]%s[/]" % esc(data.error))
        lines.append("")
        lines.append("[dim]%s[/dim]" % ("already in your Inbox" if item.get("roomID") in self._mine else "Subscribe to read and get it in your Inbox"))
        return lines

    def action_subscribe(self) -> None:
        item = self._detail_item or self.selected()
        if item is not None:
            self.mutate("room-subscribe", item.get("roomID"), ok_text="subscribed to %s" % (item.get("name") or "room"))

    def action_unsubscribe(self) -> None:
        item = self._detail_item or self.selected()
        if item is not None:
            self.mutate("room-unsubscribe", item.get("roomID"), ok_text="unsubscribed from %s" % (item.get("name") or "room"))

    def action_open_in_inbox(self) -> None:
        item = self._detail_item or self.selected()
        if item is not None:
            self.app.open_in_section("rooms", str(item.get("roomID")))  # type: ignore[attr-defined]

    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)
        if fetched.ok:
            self.refresh_data(force=True)
