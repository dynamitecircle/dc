"""Search — one box, content-type tabs like the web app: All · Profiles · Rooms ·
Messages · Events · Chapters. Enter on a hit jumps to it."""
from __future__ import annotations

from typing import Any, List, Sequence, Tuple

from textual.widgets import Input

from .format import event_dates, flag, fmt_date, plural, strip_markdown, trunc
from .labels import event_type_label, room_type_label
from .profile import profile_lines
from .listing import ListDetailScreen, dict_of, esc, items_of, plain
from .screens import WEB_APP

KINDS = ("profiles", "rooms", "messages", "events", "chapters")


class SearchScreen(ListDetailScreen):
    SECTION = "search"
    TITLE_TEXT = "Search"
    HINT = "type and press Enter · tabs pick the content type · Enter on a hit opens it"
    URL = WEB_APP + "/search"
    LIST_TABS = (("all", "All"), ("profiles", "Profiles"), ("rooms", "Rooms"), ("messages", "Messages"),
                 ("events", "Events"), ("chapters", "Chapters"))
    COLUMNS = ("Result", "Type", "Where")
    COLUMN_DROP = ("Type",)
    COLUMNS_COMPACT = ("Result", "Type", "Where")
    COLUMN_WIDTHS = {"Type": 8, "Where": 26}
    EMPTY_TEXT = "type something above and press Enter"
    AUTO_FOCUS = "#search-query"

    DEFAULT_CSS = """
    SearchScreen #search-query { margin: 0 0 1 0; }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.query_text = ""

    def populate(self) -> None:
        super().populate()
        self.main_pane().mount(Input(placeholder="Search DC — people, rooms, messages, events, chapters…", id="search-query"), before=0)

    def focus_content(self) -> None:
        self.query_one("#search-query", Input).focus()

    def refresh_data(self, force: bool = False) -> None:
        if not self.query_text:
            self.items = []
            self._rows_loaded([], "")
            self.set_hint(self.EMPTY_TEXT)       # no "0 hits for ''" before a search
            return
        super().refresh_data(force)

    def hint_text(self) -> str:
        if not self.query_text:
            return self.EMPTY_TEXT
        return "%s for “%s”  [dim]%s[/dim]" % (plural(len(self.items), "hit"), self.query_text, self.HINT)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search-query":
            return
        self.query_text = event.value.strip()
        self._detail_item = None
        self.refresh_data(force=False)
        if self.query_text:
            self.query_one("#list").focus()

    # ── rows ──────────────────────────────────────────────────────────
    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        q = self.query_text
        rows: List[dict] = []
        if self.list_tab == "all":
            fetched = data.fetch("search", q, limit=8, force=force)
            if fetched.error and fetched.data is None:
                raise RuntimeError(fetched.error)
            body = dict_of(fetched)
            for kind in KINDS:
                block = body.get(kind)
                hits = block.get("hits") if isinstance(block, dict) else block
                for h in (hits or []) if isinstance(hits, list) else []:
                    if isinstance(h, dict):
                        rows.append(_tag(h, kind))
            return rows
        fetched = data.fetch("search-" + self.list_tab, q, limit=30, force=force)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        body = dict_of(fetched)
        hits = body.get("hits") if isinstance(body.get("hits"), list) else items_of(fetched)
        return [_tag(h, self.list_tab) for h in hits if isinstance(h, dict)]

    def row_key(self, item: dict, index: int) -> str:
        return "%s:%s" % (item.get("_kind"), _id(item) or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        icon = {"profiles": "👤 ", "events": "📅 ", "rooms": "# ", "messages": "💬 ",
                "chapters": (flag(item.get("countryCode")) or "📍") + " "}.get(str(item.get("_kind")), "")
        cells = {"Result": icon + _title(item), "Type": _kind_label(item.get("_kind")), "Where": _detail(item)}
        return tuple(cells[c] for c in self._columns())

    # ── detail ────────────────────────────────────────────────────────
    def detail_actions(self):
        return [("Open", "open_hit"), ("Open in app", "app.open_in_browser")]

    def detail_title(self, item: dict) -> str:
        return "%s  [dim]%s[/dim]" % (esc(_title(item)), _kind_label(item.get("_kind")))

    def render_detail(self, item: dict, data: Any) -> List[str]:
        """A readable preview per content type — Open (or Enter) goes to the full thing."""
        kind = item.get("_kind")
        width = self.detail_width()
        if kind == "profiles":
            lines = ([esc(item["headline"]), ""] if item.get("headline") else []) + profile_lines(item, width=width, header=False)
            return lines + ["", "[dim]Open shows the full profile[/dim]"]
        if kind == "messages":
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            who = author.get("displayName") or item.get("authorName") or ""
            head = " · ".join(esc(x) for x in (who, item.get("roomName") or "", fmt_date(item.get("sentAt") or item.get("createdAt"))) if x)
            body = plain(item.get("body") or item.get("text") or item.get("message") or "", True)
            return ["[dim]%s[/dim]" % head, "", esc(trunc(body, 1200))]
        if kind == "rooms":
            stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
            meta = [room_type_label(item.get("type")), plural(int(stats.get("subscribers") or 0), "member") if stats.get("subscribers") else ""]
            desc = plain(item.get("description") or item.get("topic") or "", True)
            return ["[dim]%s[/dim]" % " · ".join(m for m in meta if m)] + (["", esc(trunc(desc, 800))] if desc else [])
        if kind == "events":
            meta = [event_dates(item), item.get("cityName") or dict_of(item.get("city")).get("name") or "", event_type_label(item.get("eventType"))]
            desc = strip_markdown(item.get("description") or "")
            return ["[dim]%s[/dim]" % esc(" · ".join(m for m in meta if m))] + (["", esc(trunc(desc, 800))] if desc else [])
        if kind == "chapters":
            meta = [item.get("country") or "", plural(int(item.get("memberCount") or 0), "member") if item.get("memberCount") else ""]
            return ["%s [b]DC %s Chapter[/b]" % (flag(item.get("countryCode")) or "📍", esc(item.get("name") or "")),
                    "[dim]%s[/dim]" % esc(" · ".join(m for m in meta if m))]
        return ["[dim]no more detail[/dim]"]

    def action_open_hit(self) -> None:
        self.action_open_detail()
        item = self._detail_item or self.selected()
        if item is None:
            return
        kind = item.get("_kind")
        if kind == "profiles":
            self.app.open_person(item)  # type: ignore[attr-defined]
        elif kind == "rooms" and item.get("roomID"):
            self.app.open_in_section("rooms", str(item["roomID"]))  # type: ignore[attr-defined]
        elif kind == "events" and item.get("eventID"):
            self.app.open_in_section("events", str(item["eventID"]))  # type: ignore[attr-defined]
        else:
            self.app.action_open_in_browser()  # type: ignore[attr-defined]

    def on_data_table_row_selected(self, event) -> None:
        if event.data_table.id == "list":
            self.action_open_hit()

    def current_url(self) -> str:
        item = self.selected()
        if item:
            for key in ("shortURL", "roomURL", "eventURL", "profileURL", "chapterURL", "messageURL", "url"):
                if item.get(key):
                    return str(item[key])
            if item.get("_kind") == "profiles" and item.get("userName"):
                return WEB_APP + "/" + str(item["userName"])
        return self.URL


def _tag(hit: dict, kind: str) -> dict:
    out = dict(hit.get("profile") or hit) if isinstance(hit.get("profile"), dict) else dict(hit)
    out["_kind"] = kind
    return out


def _id(item: dict):
    for key in ("userID", "roomID", "messageID", "eventID", "cityID", "placeID", "objectID", "id"):
        if item.get(key):
            return item[key]
    return None


def _kind_label(kind) -> str:
    return {"profiles": "DCer", "rooms": "room", "messages": "message", "events": "event", "chapters": "chapter"}.get(str(kind), str(kind or ""))


def _title(item: dict) -> str:
    kind = item.get("_kind")
    if kind == "messages":
        body = str(item.get("body") or item.get("text") or item.get("content") or item.get("snippet") or "")
        # HTML → text, drop a quoted-reply prefix ("Replying to X in Y …"), then any markdown
        text = plain(body, True)
        if text.lower().startswith("replying to ") and " in " in text:
            text = text.split(" in ", 1)[1]
            text = text.split(" ", 1)[1] if " " in text else ""     # after the room name
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(">")]
        return strip_markdown(" ".join(lines) if lines else text) or "(attachment)"
    if kind == "chapters":
        return str(item.get("cityName") or item.get("name") or item.get("cityID") or "")
    if kind == "rooms":
        name = item.get("name") or item.get("roomName")
        if name:
            return str(name)
        kind_label = {"dm": "Direct message", "group": "Group chat"}.get(str(item.get("type") or ""), "Room")
        return "%s %s" % (kind_label, str(item.get("roomID") or "")[:8])
    return str(item.get("displayName") or item.get("name") or item.get("title") or item.get("roomName") or item.get("userName") or "")


def _detail(item: dict) -> str:
    kind = item.get("_kind")
    if kind == "profiles":
        return plain(item.get("headline") or item.get("businessName") or "")
    if kind == "rooms":
        return " · ".join(x for x in (room_type_label(item.get("type")), plain(item.get("description") or "")) if x)
    if kind == "messages":
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        return "%s · %s · %s" % (item.get("roomName") or "", author.get("displayName") or item.get("authorName") or "", fmt_date(item.get("sentAt") or item.get("createdAt")))
    if kind == "events":
        return "%s · %s" % (event_dates({"startDate": item.get("startDate") or item.get("startAt"), "endDate": item.get("endDate") or item.get("endAt"),
                                          "isDateConfirmed": item.get("isDateConfirmed")}), event_type_label(item.get("eventType")))
    if kind == "chapters":
        return " · ".join(p for p in (item.get("country") or "", "%s members" % (item.get("memberCount") or "?")) if p)
    return ""
