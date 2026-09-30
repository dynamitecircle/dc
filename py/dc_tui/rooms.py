"""Rooms — your inbox by type, read-only messages, AI summaries, and the
idempotent room mutations. Conversations stay in the app (`o`)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from textual import work
from textual.binding import Binding

from .data import Fetched
import re

from .format import fmt_date, pad, plural, trunc, display_width
from .labels import room_title, room_type_label
from .listing import ListDetailScreen, dict_of, esc, items_of, plain
from .screens import SECTIONS, WEB_APP

class RoomsScreen(ListDetailScreen):
    SECTION = "rooms"
    TITLE_TEXT = "Inbox"
    HINT = "↑↓ pick a room · Enter opens its messages · buttons in the detail do the rest"
    URL = WEB_APP + "/inbox"
    # same filters as the web inbox (SidebarInbox.vue) plus Unread; discovery lives in Browse
    LIST_TABS = (("all", "All"), ("dm", "DMs"), ("group", "Groups"), ("channel", "Channels"),
                 ("discussion", "Discussions"), ("quick-question", "Quick Questions"))
    # the web's visibility filter (SidebarInbox.vue); Unsubscribed needs rooms you left, which the API does not list
    LIST_FILTERS = (("show-all", "All"), ("unread", "Unread"), ("pinned", "Pinned"), ("muted", "Muted"), ("archived", "Archived"))
    COLUMNS = ("Room", "Type", "Unread", "Activity")
    COLUMN_DROP = ("Type",)
    COLUMNS_COMPACT = ("Room", "Unread", "Activity")
    COLUMN_WIDTHS = {"Type": 14, "Unread": 6, "Activity": 11}
    EMPTY_TEXT = "No chats match your filters. Browse finds channels, discussions and quick questions to join."

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
        self._toggled: Dict[str, Dict[str, bool]] = {}   # roomID → seen flags changed this session
        # roomID → older pages loaded by scrolling up: {"items", "cursor", "loading", "done"}
        self._older: Dict[str, Dict[str, Any]] = {}
        self._keep_scroll: Optional[Tuple[float, float]] = None

    @property
    def room_type(self) -> str:
        return "" if self.list_tab == "all" else self.list_tab

    # ── rows ──────────────────────────────────────────────────────────
    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        unread = data.fetch("inbox", force=force)
        me = dict_of(data.fetch("profile"))
        self._me_name = str(me.get("displayName") or "")
        self._unread = {r.get("roomID"): int(r.get("badgeCount") or 0) for r in items_of(unread)}
        seen_filter = self.list_filter if self.list_filter in ("pinned", "muted", "archived") else None
        kwargs = {"filter": seen_filter} if seen_filter else {}
        fetched = data.fetch("rooms", self.room_type, force=force, **kwargs) if self.room_type else data.fetch("rooms", force=force, **kwargs)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        rooms = items_of(fetched)
        if seen_filter:                  # older servers ignore ?filter — apply it here too when flags are present
            key = {"pinned": "isPinned", "muted": "isMuted", "archived": "isArchived"}[seen_filter]
            if any(isinstance(r.get("seen"), dict) for r in rooms):
                rooms = [r for r in rooms if self._flags(r).get(key)]
        if self.list_filter == "unread":
            rooms = [r for r in rooms if self._unread.get(r.get("roomID"), 0) > 0 and not self._flags(r).get("isArchived")]
        # web order (SidebarInbox.vue): pinned tier, active tier, archived tier; unread floats up
        # inside the pinned and active tiers; then most recent activity
        rooms.sort(key=lambda r: str(r.get("lastActivityAt") or ""), reverse=True)
        rooms.sort(key=lambda r: (self._tier(r), 0 if (self._tier(r) <= 1 and self._unread.get(r.get("roomID"), 0) > 0) else 1))
        return rooms

    def _tier(self, room: dict) -> int:
        flags = self._flags(room)
        return 0 if flags.get("isPinned") else (2 if flags.get("isArchived") else 1)

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("roomID") or index)

    def base_columns(self):
        cols = super().base_columns()
        if self.list_tab not in ("all", ""):
            cols = tuple(c for c in cols if c != "Type")     # every row has the tab's type
        return cols

    def _marks(self, item: dict) -> str:
        flags = self._flags(item)
        return ("📌 " if flags.get("isPinned") else "") + ("🔕 " if flags.get("isMuted") else "")

    def title_of(self, item: dict) -> str:
        me = getattr(self, "_me_name", "")
        if not me:                     # rows can paint from cache before fetch_rows ran
            cached = self.app.data.cached("profile")  # type: ignore[attr-defined]
            me = str(dict_of(cached).get("displayName") or "") if cached is not None else ""
            self._me_name = me
        return room_title(item, me)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        unread = self._unread.get(item.get("roomID"), 0)
        cells = {
            "Room":     self._marks(item) + self.title_of(item),
            "Type":     room_type_label(item.get("type")),
            "Unread":   str(unread) if unread else "",
            "Activity": fmt_date(item.get("lastActivityAt")),
        }
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        if not self.items:
            return self.EMPTY_TEXT
        total = sum(self._unread.values())
        return "%s · %s  [dim]%s[/dim]" % (plural(len(self.items), "room"), plural(total, "unread"), self.HINT)

    # ── detail ────────────────────────────────────────────────────────
    def _flags(self, item: dict) -> dict:
        """Seen flags for a room: what the API says (`seen` on the room, when it
        ships) overlaid with what this session already toggled."""
        seen = item.get("seen") if isinstance(item.get("seen"), dict) else {}
        out = dict(seen)
        out.update(self._toggled.get(str(item.get("roomID")), {}))
        return out

    def detail_actions(self):
        item = self._detail_item or {}
        flags = self._flags(item)
        # one toggle, as the app's room menu: a read room offers Mark unread
        unread = self._unread.get(item.get("roomID"), 0) > 0
        acts = [("Mark read", "mark_read") if unread else ("Mark unread", "mark_unread")]
        if isinstance(item.get("participant"), dict) and item["participant"].get("userID"):
            acts.append(("View profile", "view_participant"))
        for flag, on, off in _TOGGLES:
            label, command, done = (off if flags.get(flag) else on)
            acts.append((label, "room('%s', '%s')" % (command, done)))
        if item.get("type") not in ("dm", "group"):
            acts.append(("Unsubscribe", "room('room-unsubscribe', 'unsubscribed')"))
        acts.append(("Open in app", "app.open_in_browser"))
        return acts

    def detail_title(self, item: dict) -> str:
        return "%s  [dim]%s%s[/dim]" % (esc(self.title_of(item)), room_type_label(item.get("type")), " · DC BLACK" if item.get("scope") == "dcb" else "")

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
            if force:
                self._older.pop(str(room_id), None)      # a refresh starts from the newest page again
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
        bits = [room_type_label(item.get("type")), "DC BLACK" if item.get("scope") == "dcb" else ""]
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
        self._links: List[str] = []
        first = items_of(data["messages"])
        older = self._older.get(str(item.get("roomID")), {})
        messages = first + list(older.get("items") or [])          # newest first, then older pages
        width = self.detail_width()
        lines: List[str] = []
        cursor = older.get("cursor") if older else dict_of(data["messages"]).get("cursor")
        if older.get("loading"):
            lines += ["[dim]loading older messages…[/dim]", ""]
        elif cursor and not older.get("done"):
            lines += ["[dim]↑ scroll up for older messages[/dim]", ""]
        elif messages:
            lines += ["[dim]beginning of the conversation[/dim]", ""]
        if data["messages"].error and not messages:
            lines.append("[$warning]%s[/]" % esc(data["messages"].error))
        # chat order: oldest first, the newest message last (the "last page")
        for m in reversed(messages):
            author = m.get("author") if isinstance(m.get("author"), dict) else {}
            who = author.get("displayName") or author.get("userName") or "system"
            when = fmt_date(m.get("sentAt"))
            lines.append("[b]%s[/b] [dim]%s[/dim]" % (esc(pad(who, max(4, width - display_width(when) - 1))), when))
            if m.get("isDeleted"):
                lines.append("[dim](deleted)[/dim]")
            else:
                raw = str(m.get("text") or "")
                text, reply_to = _split_reply(plain(raw, bool(m.get("isHTML"))))
                if reply_to:
                    lines.append("[dim]↳ replying to %s[/dim]" % esc(reply_to))
                kind = attachment_label(m.get("type"), raw)
                if kind:
                    url = attachment_url(m, raw)
                    if url:                                     # click to open it in the browser
                        self._links.append(url)
                        lines.append("[b][@click=screen.open_attachment(%d)]%s ↗[/][/b]" % (len(self._links) - 1, kind))
                    else:
                        att = m.get("attachment") if isinstance(m.get("attachment"), dict) else {}
                        pending = " [dim](still processing)[/dim]" if att.get("videoStatus") == "processing" else ""
                        lines.append("[b]%s[/b]%s" % (kind, pending))
                if text:
                    lines.append(esc(trunc(text, 1200)))
                elif not kind:
                    lines.append("[dim](empty message)[/dim]")
            lines.append("")
        if not messages and not data["messages"].error:
            lines.append("[dim]no messages yet[/dim]")
        lines.append("[dim]read-only — Open in app to reply[/dim]")
        return lines

    # ── actions ───────────────────────────────────────────────────────
    def action_room(self, command: str, done: str) -> None:
        item = self._detail_item or self.selected()
        if item is None:
            return
        self._pending_toggle = (str(item.get("roomID")), command)
        self.mutate(command, item.get("roomID"), ok_text="%s %s" % (self.title_of(item), done))

    def action_open_attachment(self, index: int) -> None:
        links = getattr(self, "_links", [])
        if 0 <= int(index) < len(links):
            self.app.open_url(links[int(index)])
            self.notify("Opened in your browser", timeout=2)

    def action_view_participant(self) -> None:
        """A DM's other person, in the terminal's People view."""
        item = self._detail_item or self.selected() or {}
        person = item.get("participant") if isinstance(item.get("participant"), dict) else None
        if person:
            self.app.open_person(dict(person))  # type: ignore[attr-defined]

    def action_read_messages(self) -> None:
        from_list = getattr(self.focused, "id", None) == "list"
        # From the list it is always the highlighted row — `_detail_item` may still be
        # the previous tab's room while the new highlight is debounced.
        item = self.selected() if from_list or not self._detail_item else self._detail_item
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
        keep, self._keep_scroll = self._keep_scroll, None
        super()._paint_detail()
        pane = self.detail_scroller()
        if (self.detail_tab or "messages") == "messages" and isinstance(self._detail_data, dict) and "messages" in self._detail_data:
            if keep is not None:
                # older messages were added above: stay on the message you were reading
                old_max, old_y = keep
                self.call_after_refresh(lambda: pane.scroll_to(y=pane.max_scroll_y - old_max + old_y, animate=False))
            else:
                self.call_after_refresh(lambda: pane.scroll_end(animate=False))   # land on the newest message

    # ── older messages: scroll up past the top to load the previous page ──
    def _at_messages_top(self) -> bool:
        if (self.detail_tab or "messages") != "messages" or not isinstance(self._detail_data, dict) or "messages" not in self._detail_data:
            return False
        return self.detail_scroller().scroll_y <= 0

    def load_older(self) -> None:
        item = self._detail_item
        if item is None or not isinstance(self._detail_data, dict) or "messages" not in self._detail_data:
            return
        room_id = str(item.get("roomID"))
        state = self._older.setdefault(room_id, {"items": [], "cursor": dict_of(self._detail_data["messages"]).get("cursor"),
                                                 "loading": False, "done": False})
        if state["loading"] or state["done"] or not state["cursor"]:
            return
        state["loading"] = True
        self._paint_detail_keeping()
        self._fetch_older(room_id, state["cursor"])

    @work(thread=True, exclusive=True, group="older", exit_on_error=False)
    def _fetch_older(self, room_id: str, cursor: str) -> None:
        fetched = self.app.data.fetch("room-messages", room_id, limit=25, before=cursor)  # type: ignore[attr-defined]
        self.app.call_from_thread(self._older_arrived, room_id, fetched)

    def _older_arrived(self, room_id: str, fetched: Fetched) -> None:
        state = self._older.get(room_id)
        if state is None:
            return
        state["loading"] = False
        if fetched.error:
            self.notify("Couldn't load older messages: %s" % fetched.error, severity="warning", timeout=5)
        else:
            page = items_of(fetched)
            seen = {m.get("messageID") for m in state["items"]}
            state["items"] += [m for m in page if m.get("messageID") not in seen]
            state["cursor"] = dict_of(fetched).get("cursor")
            state["done"] = not state["cursor"] or not page
        if self._detail_item is not None and str(self._detail_item.get("roomID")) == room_id:
            self._paint_detail_keeping()

    def _paint_detail_keeping(self) -> None:
        pane = self.detail_scroller()
        self._keep_scroll = (pane.max_scroll_y, pane.scroll_y)
        self._paint_detail()

    def _detail_scroll(self, step: int, *, page: bool = False, edge: bool = False) -> None:
        at_top = self._at_messages_top()
        super()._detail_scroll(step, page=page, edge=edge)
        if step < 0 and at_top:
            self.load_older()                 # ↑ / PageUp / Home at the top → the previous page

    def on_mouse_scroll_up(self, event) -> None:
        # the pane swallows wheel events while it can still scroll; one that reaches
        # the screen means the conversation is already at its top
        if self._at_messages_top():
            self.load_older()

    def _queue_detail(self, item: dict) -> None:
        """Highlighting shows Info (cheap) unless this room was already opened."""
        if item.get("roomID") not in self._opened:
            self.detail_tab = "info"
        elif self.detail_tab == "info":
            self.detail_tab = "messages"      # a room you opened comes back on its messages
        super()._queue_detail(item)

    def action_mark_read(self) -> None:
        item = self._detail_item or self.selected()
        if item is not None:
            self._unread[item.get("roomID")] = 0          # the button flips to Mark unread at once
            self._sync_actions()
            self.mutate("room-read", item.get("roomID"), ok_text="%s marked read" % self.title_of(item))

    def action_mark_unread(self) -> None:
        item = self._detail_item or self.selected()
        if item is not None:
            self._unread[item.get("roomID")] = max(1, self._unread.get(item.get("roomID"), 0))
            self._sync_actions()
            self.mutate("room-unread", item.get("roomID"), ok_text="%s marked unread" % self.title_of(item))

    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)
        pending, self._pending_toggle = getattr(self, "_pending_toggle", None), None
        if fetched.ok and pending:
            room_id, command = pending
            for flag, on, off in _TOGGLES:
                if command == on[1]:
                    self._toggled.setdefault(room_id, {})[flag] = True
                elif command == off[1]:
                    self._toggled.setdefault(room_id, {})[flag] = False
            seen = dict_of(fetched.data).get("seen")
            if isinstance(seen, dict):
                self._toggled.setdefault(room_id, {}).update({k: bool(v) for k, v in seen.items() if k in _FLAG_KEYS})
        if fetched.ok:
            self.refresh_data(force=True)


#: (seen flag, (label, command, past tense) when off, same when on)
_TOGGLES = (
    ("isMuted",    ("Mute", "room-mute", "muted"),          ("Unmute", "room-unmute", "unmuted")),
    ("isPinned",   ("Pin", "room-pin", "pinned"),           ("Unpin", "room-unpin", "unpinned")),
    ("isArchived", ("Archive", "room-archive", "archived"), ("Unarchive", "room-unarchive", "unarchived")),
)
_FLAG_KEYS = {t[0] for t in _TOGGLES}


# colour emoji only (📷 not 🖼: that one is a text-style symbol most terminals draw as a gray outline)
_ATTACHMENT_TYPES = {"image": "📷 Image", "video": "🎬 Video", "file": "📎 File", "custom": "🧩 Card"}
_VIDEO_LINK = re.compile(r"""https?://[^\s"'<>]+(?:\.(?:mp4|mov|webm|m3u8)\b[^\s"'<>]*|youtube\.com/(?:watch|embed|shorts)[^\s"'<>]*|youtu\.be/[^\s"'<>]+|vimeo\.com/[^\s"'<>]+)""",
                         re.IGNORECASE)
_EMBEDDED = ((re.compile(r"<img\b", re.IGNORECASE), "📷 Image"),
             (re.compile(r"<video\b|youtube\.com/(?:embed|watch|shorts)|youtu\.be/|vimeo\.com/|\.(?:mp4|mov|webm)\b", re.IGNORECASE), "🎬 Video"),
             (re.compile(r"<audio\b", re.IGNORECASE), "🔊 Audio"))


_SRC = re.compile(r"""<(?:img|video|source)\b[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)


def attachment_url(message: dict, raw: str) -> str:
    """The link to open: the API's attachment URL, else the first embedded image/video src."""
    att = message.get("attachment") if isinstance(message.get("attachment"), dict) else {}
    if att.get("url"):
        return str(att["url"])
    m = _SRC.search(raw or "")
    if m and m.group(1).startswith("http"):
        return m.group(1)
    v = _VIDEO_LINK.search(raw or "")            # a pasted video / YouTube / Vimeo link
    return v.group(0) if v else ""


def attachment_label(msg_type: Any, raw: str) -> str:
    """The message's attachment kind (the API's `type`), or media embedded in its HTML."""
    label = _ATTACHMENT_TYPES.get(str(msg_type or ""))
    if label:
        return label
    found = [name for rx, name in _EMBEDDED if rx.search(raw or "")]
    return " · ".join(found)


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
