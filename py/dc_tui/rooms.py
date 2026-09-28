"""Rooms — your inbox by type, read-only messages, AI summaries, and the
idempotent room mutations. Conversations stay in the app (`o`)."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from textual.binding import Binding

from .data import Fetched
from .format import fmt_date, plural, trunc
from .listing import ListDetailScreen, dict_of, esc, items_of, plain
from .screens import SECTIONS, WEB_APP

TYPES = ["", "channel", "discussion", "dm", "group", "quick-question", "event"]
TYPE_LABEL = {"": "all", "dm": "DMs", "group": "groups", "quick-question": "quick questions"}


class RoomsScreen(ListDetailScreen):
    SECTION = "rooms"
    TITLE_TEXT = "Rooms"
    HINT = "f filter type · x mark read · m/M mute · p/P pin · a/A archive · s/S subscribe"
    URL = WEB_APP + "/inbox"
    LIST_COMMAND = "rooms"
    COLUMNS = ("Room", "Type", "Unread", "Activity")
    COLUMNS_COMPACT = ("Room", "Unread", "Activity")
    EMPTY_TEXT = "no rooms of this type"

    BINDINGS = [
        Binding("f", "cycle_filter", "Filter"),
        Binding("x", "mark_read", "Read"),
        Binding("m", "room('room-mute', 'muted')", "Mute"),
        Binding("M", "room('room-unmute', 'unmuted')", "Unmute", show=False),
        Binding("p", "room('room-pin', 'pinned')", "Pin"),
        Binding("P", "room('room-unpin', 'unpinned')", "Unpin", show=False),
        Binding("a", "room('room-archive', 'archived')", "Archive"),
        Binding("A", "room('room-unarchive', 'unarchived')", "Unarchive", show=False),
        Binding("s", "room('room-subscribe', 'subscribed')", "Subscribe", show=False),
        Binding("S", "room('room-unsubscribe', 'unsubscribed')", "Unsubscribe", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.room_type = ""
        self._unread = {}

    # ── rows ──────────────────────────────────────────────────────────
    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        unread = data.fetch("inbox", force=force)
        self._unread = {r.get("roomID"): int(r.get("badgeCount") or 0) for r in items_of(unread)}
        fetched = data.fetch("rooms", self.room_type, force=force) if self.room_type else data.fetch("rooms", force=force)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        rooms = items_of(fetched)
        rooms.sort(key=lambda r: (-self._unread.get(r.get("roomID"), 0), str(r.get("lastActivityAt") or "")), reverse=False)
        rooms.sort(key=lambda r: str(r.get("lastActivityAt") or ""), reverse=True)
        rooms.sort(key=lambda r: -self._unread.get(r.get("roomID"), 0))
        return rooms

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("roomID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        unread = self._unread.get(item.get("roomID"), 0)
        cells = {
            "Room":     trunc(item.get("name") or _dm_label(item), 26 if self.two_pane else 44),
            "Type":     str(item.get("type") or ""),
            "Unread":   str(unread) if unread else "",
            "Activity": fmt_date(item.get("lastActivityAt")),
        }
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        label = TYPE_LABEL.get(self.room_type, self.room_type or "all")
        total = sum(self._unread.values())
        return "%s · %s · %s  [dim]%s[/dim]" % (plural(len(self.items), "room"), label, plural(total, "unread"), self.HINT)

    def action_cycle_filter(self) -> None:
        self.room_type = TYPES[(TYPES.index(self.room_type) + 1) % len(TYPES)]
        self._detail_item = None
        self.refresh_data(force=False)

    # ── detail ────────────────────────────────────────────────────────
    def detail_title(self, item: dict) -> str:
        return "%s  [dim]%s · %s[/dim]" % (esc(item.get("name")), item.get("type", ""), item.get("scope", ""))

    def fetch_detail(self, item: dict, force: bool) -> Any:
        data = self.app.data  # type: ignore[attr-defined]
        room_id = item.get("roomID")
        return {
            "room":     data.fetch("room", room_id, force=force),
            "messages": data.fetch("room-messages", room_id, limit=15, force=force),
        }

    def render_detail(self, item: dict, data: Any) -> List[str]:
        if not isinstance(data, dict):
            return ["[dim]loading…[/dim]"]
        lines: List[str] = []
        desc = plain(item.get("description"))
        if desc:
            lines.append("[dim]%s[/dim]" % esc(trunc(desc, 240)))
        room = dict_of(data["room"])
        weekly = room.get("aiSummaryWeekly") if isinstance(room.get("aiSummaryWeekly"), dict) else None
        daily = room.get("aiSummaryDaily") if isinstance(room.get("aiSummaryDaily"), dict) else None
        summary = weekly or daily
        if summary:
            lines.append("")
            lines.append("[b]%s summary[/b]  [dim]%s · %s msgs · %s people[/dim]" % (
                summary.get("type", "").title(), fmt_date(summary.get("intervalEndAt")),
                summary.get("messageCount", "?"), summary.get("participantCount", "?")))
            text = plain(summary.get("html"), True)
            if text:
                lines.append(esc(trunc(text, 600)))
            topics = summary.get("topics") if isinstance(summary.get("topics"), list) else []
            names = [t.get("title") or t.get("name") or t.get("topic") if isinstance(t, dict) else str(t) for t in topics[:6]]
            names = [n for n in names if n]
            if names:
                lines.append("[dim]topics:[/dim] " + esc(" · ".join(names)))
        if data["room"].error:
            lines.append("[$warning]%s[/]" % esc(data["room"].error))
        messages = items_of(data["messages"])
        lines.append("")
        lines.append("[b]Latest messages[/b]  [dim]read-only — press o to reply in the app[/dim]")
        if data["messages"].error and not messages:
            lines.append("[$warning]%s[/]" % esc(data["messages"].error))
        for m in messages[:15]:
            author = m.get("author") if isinstance(m.get("author"), dict) else {}
            who = author.get("displayName") or author.get("userName") or "system"
            text = "[dim](deleted)[/dim]" if m.get("isDeleted") else esc(trunc(plain(m.get("text"), bool(m.get("isHTML"))), 220))
            lines.append("[b]%s[/b] [dim]%s[/dim]  %s" % (esc(who), fmt_date(m.get("sentAt")), text))
        if not messages and not data["messages"].error:
            lines.append("[dim]no messages[/dim]")
        return lines

    # ── actions ───────────────────────────────────────────────────────
    def action_room(self, command: str, done: str) -> None:
        item = self.selected()
        if item is None:
            return
        self.mutate(command, item.get("roomID"), ok_text="%s %s" % (item.get("name") or "room", done))

    def action_mark_read(self) -> None:
        item = self.selected()
        if item is None:
            return
        if not hasattr(self.app.data.dc, "room_read"):  # type: ignore[attr-defined]
            self.notify("Mark-as-read arrives with Member API 2.5 — press o to open the room instead.",
                        title="Not yet", severity="warning", timeout=6)
            return
        self.mutate("room-read", item.get("roomID"), ok_text="%s marked read" % (item.get("name") or "room"))

    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)
        if fetched.ok:
            self.refresh_data(force=True)


def _dm_label(room: dict) -> str:
    """Unnamed DMs come back as `dm_<a>_<b>`; label them by type instead of the raw id."""
    rid = str(room.get("roomID") or "")
    return "Direct message" if rid.startswith("dm_") else rid
