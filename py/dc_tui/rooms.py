"""Rooms — your inbox by type, read-only messages, AI summaries, and the
idempotent room mutations. Conversations stay in the app (`o`)."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from textual.binding import Binding

from .data import Fetched
import re

from .format import fmt_date, pad, plural, trunc
from .listing import ListDetailScreen, dict_of, esc, items_of, plain
from .screens import SECTIONS, WEB_APP

class RoomsScreen(ListDetailScreen):
    SECTION = "rooms"
    TITLE_TEXT = "Inbox"
    HINT = "↑↓ pick a room · Enter opens its messages · buttons in the detail do the rest"
    URL = WEB_APP + "/inbox"
    # same filters as the web inbox (SidebarInbox.vue) plus Unread; discovery lives in Browse
    LIST_TABS = (("all", "All"), ("unread", "Unread"), ("dm", "DMs"), ("group", "Groups"), ("channel", "Channels"),
                 ("discussion", "Discussions"), ("quick-question", "Quick Questions"))
    COLUMNS = ("Room", "Type", "Unread", "Activity")
    COLUMNS_COMPACT = ("Room", "Unread", "Activity")
    COLUMN_WIDTHS = {"Type": 14, "Unread": 6, "Activity": 8}
    EMPTY_TEXT = "nothing here — Browse finds channels, discussions and quick questions to join"

    BINDINGS = [
        Binding("v", "read_messages", "Read msgs", show=False),
        Binding("x", "mark_read", "Mark read", show=False),
        Binding("m", "room('room-mute', 'muted')", "Mute", show=False),
        Binding("M", "room('room-unmute', 'unmuted')", "Unmute", show=False),
        Binding("p", "room('room-pin', 'pinned')", "Pin", show=False),
        Binding("P", "room('room-unpin', 'unpinned')", "Unpin", show=False),
        Binding("a", "room('room-archive', 'archived')", "Archive", show=False),
        Binding("A", "room('room-unarchive', 'unarchived')", "Unarchive", show=False),
        Binding("s", "room('room-subscribe', 'subscribed')", "Subscribe", show=False),
        Binding("S", "room('room-unsubscribe', 'unsubscribed')", "Unsubscribe", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._unread = {}
        self._opened = set()       # rooms whose messages the user explicitly asked to read

    @property
    def room_type(self) -> str:
        return "" if self.list_tab in ("all", "unread") else self.list_tab

    # ── rows ──────────────────────────────────────────────────────────
    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        unread = data.fetch("inbox", force=force)
        self._unread = {r.get("roomID"): int(r.get("badgeCount") or 0) for r in items_of(unread)}
        fetched = data.fetch("rooms", self.room_type, force=force) if self.room_type else data.fetch("rooms", force=force)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        rooms = items_of(fetched)
        if self.list_tab == "unread":
            rooms = [r for r in rooms if self._unread.get(r.get("roomID"), 0) > 0]
        rooms.sort(key=lambda r: str(r.get("lastActivityAt") or ""), reverse=True)
        rooms.sort(key=lambda r: -self._unread.get(r.get("roomID"), 0))
        return rooms

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("roomID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        unread = self._unread.get(item.get("roomID"), 0)
        cells = {
            "Room":     item.get("name") or _dm_label(item),
            "Type":     str(item.get("type") or ""),
            "Unread":   str(unread) if unread else "",
            "Activity": fmt_date(item.get("lastActivityAt")),
        }
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        total = sum(self._unread.values())
        return "%s · %s  [dim]%s[/dim]" % (plural(len(self.items), "room"), plural(total, "unread"), self.HINT)

    # ── detail ────────────────────────────────────────────────────────
    def detail_actions(self):
        item = self._detail_item or {}
        acts = [("Mark read", "mark_read"),
                ("Mute", "room('room-mute', 'muted')"), ("Unmute", "room('room-unmute', 'unmuted')"),
                ("Pin", "room('room-pin', 'pinned')"), ("Unpin", "room('room-unpin', 'unpinned')"),
                ("Archive", "room('room-archive', 'archived')"), ("Unarchive", "room('room-unarchive', 'unarchived')")]
        if item.get("type") not in ("dm", "group"):
            acts.append(("Unsubscribe", "room('room-unsubscribe', 'unsubscribed')"))
        acts.append(("Open in app", "app.open_in_browser"))
        return acts

    def detail_title(self, item: dict) -> str:
        return "%s  [dim]%s · %s[/dim]" % (esc(item.get("name")), item.get("type", ""), item.get("scope", ""))

    def detail_tabs(self):
        return (("messages", "Messages"), ("summary", "AI summary"), ("info", "Info"))

    def fetch_detail(self, item: dict, force: bool) -> Any:
        """Highlighting a room costs one cheap `room` call (info + summaries).
        Messages are fetched only when the room was explicitly OPENED (Enter, →,
        click, or the Read messages button) and the Messages tab is showing."""
        data = self.app.data  # type: ignore[attr-defined]
        room_id = item.get("roomID")
        out = {"room": data.fetch("room", room_id, force=force)}
        if room_id in self._opened and (self.detail_tab or "messages") == "messages":
            out["messages"] = data.fetch("room-messages", room_id, limit=25, force=force)
        return out

    def render_detail(self, item: dict, data: Any) -> List[str]:
        if not isinstance(data, dict):
            return ["[dim]loading…[/dim]"]
        tab = self.detail_tab or "messages"
        room = dict_of(data["room"])
        if tab == "info":
            return self._render_info(item, room, data["room"])
        if tab == "summary":
            return self._render_summary(room, data["room"])
        return self._render_messages(item, data)

    def _render_info(self, item: dict, room: dict, f: Fetched) -> List[str]:
        lines: List[str] = []
        desc = plain(item.get("description"))
        if desc:
            lines.append(esc(trunc(desc, 400)))
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        bits = [item.get("type") or "", item.get("scope") or ""]
        if stats.get("subscribers"):
            bits.append(plural(int(stats["subscribers"]), "member"))
        if stats.get("comments"):
            bits.append(plural(int(stats["comments"]), "message"))
        if item.get("lastActivityAt"):
            bits.append("last activity %s" % fmt_date(item.get("lastActivityAt")))
        lines.append("[dim]%s[/dim]" % " · ".join(b for b in bits if b))
        if f.error:
            lines.append("[$warning]%s[/]" % esc(f.error))
        lines.append("")
        lines.append("[dim]Enter or → opens the messages · Open in app to reply[/dim]")
        return lines

    def _render_summary(self, room: dict, f: Fetched) -> List[str]:
        lines: List[str] = []
        for key in ("aiSummaryWeekly", "aiSummaryDaily"):
            summary = room.get(key) if isinstance(room.get(key), dict) else None
            if not summary:
                continue
            lines.append("[b]%s summary[/b]  [dim]%s · %s msgs · %s people[/dim]" % (
                str(summary.get("type", "")).title(), fmt_date(summary.get("intervalEndAt")),
                summary.get("messageCount", "?"), summary.get("participantCount", "?")))
            text = plain(summary.get("html"), True)
            if text:
                lines.append(esc(trunc(text, 1200)))
            topics = summary.get("topics") if isinstance(summary.get("topics"), list) else []
            names = [t.get("title") or t.get("name") or t.get("topic") if isinstance(t, dict) else str(t) for t in topics[:8]]
            names = [n for n in names if n]
            if names:
                lines.append("[dim]topics:[/dim] " + esc(" · ".join(names)))
            lines.append("")
        if f.error:
            lines.append("[$warning]%s[/]" % esc(f.error))
        return lines or ["[dim]no AI summary for this room yet[/dim]"]

    def _render_messages(self, item: dict, data: dict) -> List[str]:
        if "messages" not in data:
            return ["[dim]Enter, → or the Read messages button loads the latest messages (read-only).[/dim]"]
        messages = items_of(data["messages"])
        width = self.detail_width()
        lines: List[str] = []
        if data["messages"].error and not messages:
            lines.append("[$warning]%s[/]" % esc(data["messages"].error))
        # chat order: oldest first, the newest message last (the "last page")
        for m in reversed(messages[:25]):
            author = m.get("author") if isinstance(m.get("author"), dict) else {}
            who = author.get("displayName") or author.get("userName") or "system"
            when = fmt_date(m.get("sentAt"))
            lines.append("[b]%s[/b]%s[dim]%s[/dim]" % (esc(pad(who, width - 8)), " ", when))
            if m.get("isDeleted"):
                lines.append("[dim](deleted)[/dim]")
            else:
                text, reply_to = _split_reply(plain(m.get("text"), bool(m.get("isHTML"))))
                if reply_to:
                    lines.append("[dim]↳ replying to %s[/dim]" % esc(reply_to))
                lines.append(esc(trunc(text, 1200)) if text else "[dim](attachment)[/dim]")
            lines.append("")
        if not messages and not data["messages"].error:
            lines.append("[dim]no messages yet[/dim]")
        lines.append("[dim]read-only — Open in app to reply[/dim]")
        return lines

    # ── actions ───────────────────────────────────────────────────────
    def action_room(self, command: str, done: str) -> None:
        item = self.selected()
        if item is None:
            return
        self.mutate(command, item.get("roomID"), ok_text="%s %s" % (item.get("name") or "room", done))

    def action_read_messages(self) -> None:
        item = self._detail_item if (self._detail_open or self.two_pane) and self._detail_item else self.selected()
        if item is None:
            return
        self._opened.add(item.get("roomID"))
        self.detail_tab = "messages"
        if not self.two_pane and not self._detail_open:
            self._show_inline_detail(True)
        self.load_detail(item)
        self.call_after_refresh(self.focus_detail)

    def action_open_detail(self) -> None:
        """Opening a room (Enter / → / click) = its last page of messages."""
        self.action_read_messages()

    def _paint_detail(self) -> None:
        super()._paint_detail()
        if (self.detail_tab or "messages") == "messages" and isinstance(self._detail_data, dict) and "messages" in self._detail_data:
            pane = self.detail_pane() if self.two_pane else self.main_pane()
            self.call_after_refresh(lambda: pane.scroll_end(animate=False))   # land on the newest message

    def _queue_detail(self, item: dict) -> None:
        """Highlighting shows Info (cheap) unless this room was already opened."""
        if item.get("roomID") not in self._opened:
            self.detail_tab = "info"
        super()._queue_detail(item)

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


_REPLY = re.compile(r"^[^\w]*Replying to (.+?) in (?:.+?)\s+(.*)$", re.DOTALL)   # any glyph/bar prefix


def _split_reply(text: str):
    """The app prefixes quoted replies with 'Replying to <name> in <room>' — lift
    that into its own line and return (body, replied_to_name)."""
    m = _REPLY.match(text or "")
    if not m:
        return text, None
    return m.group(2).strip(), m.group(1).strip()
