"""Events — three top tabs (Global · Local · Live Calls) and a tabbed detail:
Info · Schedule · My agenda · Meetups · Attendees for in-person events, Info
for live calls. Schedule and agenda are first-class: day-grouped, ★ on your
bookmarks, ✓ on meetups you joined, one-key bookmark / join / RSVP."""
from __future__ import annotations

import re

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.text import Text
from textual import work
from textual.binding import Binding

from .data import Fetched
from datetime import datetime, timezone as _tz

from .format import date_range, event_dates, flag, fmt_date, plural, strip_markdown, trunc
from .labels import call_kind_label, event_type_label, is_global_event
from .listing import ListDetailScreen, Table, dict_of, esc, items_of, plain, next_cursor
from .screens import WEB_APP

def _hhmm(value: Any) -> str:
    s = str(value or "")
    if "T" in s and len(s) >= 16:
        return s[11:16]
    return s[:5] if ":" in s[:5] else ""


def _when(value: Any) -> str:
    """Live calls are instants: show them in the viewer's local time."""
    s = str(value or "")
    if "T" not in s:
        return fmt_date(s)
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_tz.utc)
        local = d.astimezone()
        return "%s %s" % (fmt_date(local.strftime("%Y-%m-%d")), local.strftime("%H:%M"))
    except ValueError:
        return "%s %s" % (fmt_date(s), s[11:16])


def _city(event: dict) -> str:
    """City name with fallbacks — the list endpoint often leaves `city.name` null."""
    city = event.get("city") if isinstance(event.get("city"), dict) else {}
    venue = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    return str(city.get("name") or venue.get("city") or city.get("country") or "")


_URL = re.compile(r"https?://\S+")


def _map_url(event: dict) -> str:
    """A maps link in the venue info (the web shows it as a link)."""
    m = _URL.search(plain(event.get("venueInfo") or "") if event.get("venueInfo") else "")
    return m.group(0).rstrip(".,)") if m else ""


def event_flag(event: dict) -> str:
    """The event's country flag (two cells), or 📅 when it has no country."""
    city = event.get("city") if isinstance(event.get("city"), dict) else {}
    venue = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    return flag(city.get("countryCode") or venue.get("countryCode")) or "📅"


def _is_global(event: dict) -> bool:
    return is_global_event(event)


class EventsScreen(ListDetailScreen):
    SECTION = "events"
    TITLE_TEXT = "Events"
    HINT = "↑↓ pick an event · → open it · tabs and buttons in the detail"
    URL = WEB_APP + "/events"
    LIST_TABS = (("global", "Global"), ("local", "Local"), ("calls", "Live Calls"))
    COLUMNS = ("Event", "City", "Type", "🎫", "Dates")
    COLUMN_DROP = ("Type", "City", "Kind", "Going")
    COLUMNS_COMPACT = ("Event", "🎫", "Dates")
    COLUMN_WIDTHS = {"Dates": 20, "City": 14, "Type": 16, "🎫": 2, "When": 17, "Kind": 8, "Going": 5, "RSVP": 7}
    EMPTY_TEXT = "no upcoming events"

    BINDINGS = [
        Binding("b", "bookmark", "Bookmark", show=False),
        Binding("j", "join_meetup", "Join", show=False),
        Binding("y", "rsvp('yes')", "RSVP yes", show=False),
        Binding("N", "rsvp('no')", "RSVP no", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tickets: Dict[str, str] = {}
        self._rows_by_key: Dict[str, dict] = {}

    def check_action(self, action: str, parameters) -> bool:
        """Event operations live in the detail: they are disabled (and hidden from
        the footer) while the list has focus, so a stray key never acts on a row
        you were merely scrolling past."""
        if action in ("bookmark", "join_meetup", "rsvp"):
            return self.detail_focused()
        return True

    def on_descendant_focus(self, event) -> None:
        self.refresh_bindings()

    def on_descendant_blur(self, event) -> None:
        self.refresh_bindings()

    # ── columns per tab ───────────────────────────────────────────────
    def base_columns(self) -> Sequence[str]:
        compact = self.app.layout_mode_name in ("compact", "single")  # type: ignore[attr-defined]
        if self.list_tab == "calls":
            return ("Call", "RSVP", "When") if compact else ("Call", "Kind", "Going", "RSVP", "When")
        return super().base_columns()

    def detail_actions(self):
        item = self._detail_item or {}
        if self.list_tab == "calls":
            going = str(item.get("myRsvp") or "") == "yes"
            return [("Not going", "rsvp('no')") if going else ("Going", "rsvp('yes')"), ("Open call link", "app.open_in_browser")]
        acts = []
        if self.detail_tab == "info":
            if _map_url(item):
                acts.append(("Open map", "open_map"))
            if item.get("chatRoomID") and item.get("chatEnabled") is not False:
                acts.append(("Open chat", "open_chat"))
        if self.detail_tab in ("schedule", "agenda"):
            acts.append(("Bookmark session", "bookmark"))
        if self.detail_tab in ("schedule", "agenda", "meetups"):
            acts.append(("Join meetup", "join_meetup"))
        if item.get("rsvpEnabled"):
            acts += [("Going", "rsvp('yes')"), ("Not going", "rsvp('no')")]
        elif item.get("ticketsEnabled") and item.get("eventID") not in self._tickets:
            acts.append(("Get tickets", "app.open_in_browser"))
        acts.append(("Open on web", "app.open_in_browser"))
        return acts

    def detail_tabs(self) -> Sequence[Tuple[str, str]]:
        if self.list_tab == "calls":
            return ()
        item = self._detail_item or {}
        tabs = [("info", "Info"), ("schedule", "Schedule")]
        if item.get("eventID") in self._tickets:
            tabs.append(("agenda", "My agenda"))
        tabs += [("meetups", "Meetups"), ("attendees", "Attendees"), ("meet", "Who to meet"), ("sponsors", "Sponsors")]
        return tabs

    def select_key(self, key: str) -> None:
        """Deep-link to an event: switch to the tab that holds it first."""
        cached = self.app.data.cached("events", limit=50)  # type: ignore[attr-defined]
        if cached is not None:
            for e in items_of(cached):
                if str(e.get("eventID")) == key:
                    wanted = "global" if _is_global(e) else "local"
                    if wanted != self.list_tab:
                        self._pending_key = key
                        try:
                            self.query_one("#list-tabs").active = wanted    # → refresh → pending key
                        except Exception:  # noqa: BLE001
                            pass
                        return
                    break
        super().select_key(key)

    # ── rows ──────────────────────────────────────────────────────────
    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        if self.list_tab == "calls":
            fetched = data.fetch("virtual-events", limit=100, force=force)
            if fetched.error and fetched.data is None:
                raise RuntimeError(fetched.error)
            self._next_cursor = next_cursor(fetched)
            return self.order_rows(items_of(fetched))
        tickets = data.fetch("tickets", limit=100, force=force)
        self._tickets = {t.get("eventID"): t.get("ticketName") or "ticket" for t in items_of(tickets)
                         if t.get("status") in ("valid", "maybe")}
        fetched = data.fetch("events", limit=100, force=force)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        self._next_cursor = next_cursor(fetched)
        return self.order_rows(self._this_tab(items_of(fetched)))

    def _this_tab(self, events: List[dict]) -> List[dict]:
        return [e for e in events if _is_global(e) == (self.list_tab == "global")]

    def order_rows(self, rows: List[dict]) -> List[dict]:
        key = "scheduledAt" if self.list_tab == "calls" else "startDate"
        return sorted(rows, key=lambda r: str(r.get(key) or ""))

    def fetch_more(self, cursor):
        data = self.app.data  # type: ignore[attr-defined]
        if self.list_tab == "calls":
            fetched = data.fetch("virtual-events", limit=100, cursor=cursor)
            rows = items_of(fetched)
        else:
            fetched = data.fetch("events", limit=100, cursor=cursor)
            rows = self._this_tab(items_of(fetched))
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        return rows, next_cursor(fetched)

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("eventID") or item.get("sessionID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        if self.list_tab == "calls":
            cells = {
                "Call":  ("● " if item.get("isLive") else "") + str(item.get("name") or ""),
                "When":  _when(item.get("scheduledAt")),
                "Kind":  call_kind_label(item.get("kind")),
                "Going": str(item.get("attendeeCount") or ""),
                "RSVP":  {"yes": "Going", "no": "Not going", "maybe": "Maybe"}.get(str(item.get("myRsvp") or ""), ""),
            }
        else:
            cells = {
                "Event": event_flag(item) + " " + str(item.get("name") or ""),
                "Dates": event_dates(item),
                "City":  _city(item),
                "Type":  event_type_label(item.get("eventType")),
                "🎫":    "🎫" if item.get("eventID") in self._tickets else "",
            }
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        label = {"global": "global events", "local": "local events", "calls": "live calls"}[self.list_tab]
        return "%d %s  [dim]%s[/dim]" % (len(self.items), label, self.HINT)

    # ── detail ────────────────────────────────────────────────────────
    def detail_title(self, item: dict) -> str:
        if self.list_tab == "calls":
            return "%s  [dim]%s local · %s min · %s[/dim]" % (esc(item.get("name")), _when(item.get("scheduledAt")), item.get("duration") or "?", call_kind_label(item.get("kind")))
        ticket = self._tickets.get(item.get("eventID"))
        venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}
        where = " · ".join(x for x in (venue.get("name"), _city(item)) if x)
        return "%s  [dim]%s · %s%s[/dim]" % (esc(item.get("name")), event_dates(item) + ("" if item.get("isDateConfirmed") is not False else " (dates TBC)"),
                                             esc(where), "  · 🎫 You have a ticket (%s)" % esc(ticket) if ticket else "")

    def fetch_detail(self, item: dict, force: bool) -> Any:
        data = self.app.data  # type: ignore[attr-defined]
        if self.list_tab == "calls":
            return {"call": data.fetch("virtual-event", item.get("sessionID"), force=force)}
        event_id = item.get("eventID")
        tab = self.detail_tab or "info"
        out: Dict[str, Fetched] = {}
        if tab == "info":
            out["event"] = data.fetch("event", event_id, force=force)
        if tab in ("schedule", "agenda"):
            out["schedule"] = data.fetch("event-schedule", event_id, force=force)
        if tab in ("schedule", "agenda", "meetups"):
            out["meetups"] = data.fetch("event-meetups", event_id, force=force)
        if tab in ("schedule", "agenda", "meetups") and event_id in self._tickets:
            out["agenda"] = data.fetch("event-agenda", event_id, force=force)
        if tab == "agenda":
            me = str(dict_of(data.cached("profile")).get("userID") or "") if data.cached("profile") is not None else ""
            if me:
                out["free"] = data.fetch("event-free-slots", event_id, [me], force=force)
        if tab == "meet":
            # the RAG matcher, narrowed to this event's ticket holders, ranked against your profile
            out["meet"] = data.fetch("profile-match", event_id=event_id, limit=50, force=force)
        if tab == "sponsors":
            out["sponsors"] = data.fetch("event-sponsors", event_id, force=force)
        if tab == "attendees":
            out["attendees"] = data.fetch("event-attendees", event_id, limit=100, force=force)
            self.__dict__.setdefault("_more_attendees", {}).pop(event_id, None)      # a fresh first page
        return out

    def render_detail(self, item: dict, data: Any) -> Any:
        if not isinstance(data, dict):
            return ["[dim]loading…[/dim]"]
        if self.list_tab == "calls":
            return self._render_call(item, data.get("call"))
        tab = self.detail_tab or "info"
        if tab == "info":
            return self._render_info(item, data.get("event"))
        if tab == "attendees":
            return self._render_attendees(item, data.get("attendees"))
        if tab == "meet":
            return self._render_meet(item, data.get("meet"))
        if tab == "sponsors":
            return self._render_sponsors(data.get("sponsors"))
        rendered = self._render_schedule(item, data, tab)
        if tab == "agenda" and data.get("free") is not None:
            rendered = self._with_free_windows(rendered, data.get("free"))
        return rendered

    def _render_meet(self, item: dict, fetched: Optional[Fetched]) -> Any:
        body = dict_of(fetched)
        results = [r for r in (body.get("results") or items_of(fetched)) if isinstance(r, dict)] if fetched else []
        rows = []
        for r in results:
            prof = r.get("profile") if isinstance(r.get("profile"), dict) else r
            rows.append((str(prof.get("userID")), [prof.get("displayName") or prof.get("userName") or "",
                                                   plain(prof.get("headline") or ""), prof.get("businessIndustry") or ""]))
        title = "[b]Who to meet[/b]  [dim]attendees ranked against your profile · Enter opens a profile[/dim]"
        if fetched is not None and fetched.error:
            title += "  [$warning]%s[/]" % esc(fetched.error)
        if not rows:
            return [title, "", "[dim]no matches yet — the list fills as DCers get tickets[/dim]"]
        return Table(("Name", "Headline", "Industry"), rows, title=title, widths={"Headline": 34, "Industry": 16})

    def _render_sponsors(self, fetched: Optional[Fetched]) -> List[str]:
        body = dict_of(fetched)
        sponsors = [x for x in (body.get("sponsors") or items_of(fetched)) if isinstance(x, dict)] if fetched else []
        if fetched is not None and fetched.error:
            return ["[$warning]%s[/]" % esc(fetched.error)]
        if not sponsors:
            return ["[dim]no sponsors announced[/dim]"]
        lines: List[str] = []
        for sp in sponsors:
            name = esc(sp.get("name") or "Sponsor")
            tier = sp.get("tier") or sp.get("tierName") or ""
            url = sp.get("websiteURL") or ""
            head = "[b]%s[/b]%s" % (("[@click=app.open_url(%r)]%s ↗[/]" % (str(url), name)) if url else name, ("  [dim]%s[/dim]" % esc(tier)) if tier else "")
            lines += [head]
            if sp.get("description"):
                lines.append(esc(strip_markdown(sp.get("description"))))
            lines.append("")
        return lines

    def _with_free_windows(self, rendered: Any, fetched: Fetched) -> Any:
        body = dict_of(fetched)
        slots = [x for x in (body.get("slots") or items_of(fetched)) if isinstance(x, dict)]
        if not slots:
            return rendered
        lines = ["", "[b]Your free windows[/b]  [dim]no bookmarked session or meetup[/dim]"]
        for sl in sorted(slots, key=lambda x: str(x.get("startAt") or ""))[:12]:
            start, end = str(sl.get("startAt") or ""), str(sl.get("endAt") or "")
            lines.append("%s  %s–%s  [dim]%s min[/dim]" % (_day_label(start[:10]), _hhmm(start), _hhmm(end), sl.get("durationMinutes") or "?"))
        if isinstance(rendered, Table):
            rendered.title = (rendered.title or "") + "\n" + "\n".join(lines[1:])
            return rendered
        return list(rendered) + lines

    def _render_info(self, item: dict, fetched: Optional[Fetched]) -> List[str]:
        ev = dict_of(fetched).get("event") if fetched is not None else None
        ev = ev if isinstance(ev, dict) else item
        lines: List[str] = []
        # what you can do first: your ticket, or how to get in
        my = dict_of(fetched).get("myTickets") if fetched is not None else None
        ticket = self._tickets.get(item.get("eventID"))
        if (isinstance(my, list) and my) or ticket:
            lines.append("[$success]🎫 You're going[/]%s" % ("  [dim]%s[/dim]" % esc(ticket) if ticket and ticket != "ticket" else ""))
        elif ev.get("rsvpEnabled"):
            lines.append("[dim]Free event — RSVP with Going below[/dim]")
        elif ev.get("ticketsEnabled"):
            lines.append("[dim]Tickets on sale — Get tickets below[/dim]")
        venue = ev.get("venue") if isinstance(ev.get("venue"), dict) else {}
        place = ", ".join(x for x in (venue.get("name"), venue.get("city"), venue.get("country")) if x)
        if place:
            lines.append("📍 %s" % esc(place))
        info = plain(ev.get("venueInfo") or "")
        if info and not _map_url(ev) == info.strip():
            lines.append("[dim]%s[/dim]" % esc(info))
        if fetched is not None and fetched.error:
            lines.append("[$warning]%s[/]" % esc(fetched.error))
        desc = strip_markdown(ev.get("description") or ev.get("descriptionShort") or "")
        if desc:
            lines += ["", esc(desc)]                       # in full — the detail scrolls
        return lines

    def _render_attendees(self, item: dict, fetched: Optional[Fetched]) -> Any:
        body = dict_of(fetched)
        people = [a for a in (body.get("attendees") or items_of(fetched)) if isinstance(a, dict)] if fetched else []
        event_id = item.get("eventID")
        more = getattr(self, "_more_attendees", {}).get(event_id)
        if more is not None:
            people = people + more["people"]
        cursor = more["cursor"] if more is not None else (next_cursor(fetched) if fetched is not None else None)
        rows = [(str(a.get("userID")), [a.get("displayName") or a.get("userName") or "", plain(a.get("headline") or ""),
                                        a.get("businessIndustry") or ""]) for a in people]
        total = body.get("total")
        title = "%s attending%s" % (plural(len(people), "DCer"), (" of %s" % total) if isinstance(total, int) and total > len(people) else "")
        if cursor:
            title += "  [dim]·[/dim] [@click=screen.more_attendees]load more ↓[/]"
        if fetched is not None and fetched.error:
            title += "  [$warning]%s[/]" % esc(fetched.error)
        if not rows:
            return [title, "", "[dim]no attendee list yet[/dim]"]
        return Table(("Name", "Headline", "Industry"), rows, title=title, widths={"Headline": 34, "Industry": 16})

    def action_open_map(self) -> None:
        item = dict(self._detail_item or {})
        detail = self._detail_data.get("event") if isinstance(self._detail_data, dict) else None
        full = dict_of(detail).get("event") if detail is not None else None
        url = _map_url(full if isinstance(full, dict) else item) or _map_url(item)
        if url:
            self.app.open_url(url)  # type: ignore[attr-defined]

    def action_open_chat(self) -> None:
        room_id = (self._detail_item or {}).get("chatRoomID")
        if room_id:
            self.app.open_in_section("rooms", str(room_id))  # type: ignore[attr-defined]

    # people rows (Attendees, Who to meet): Enter opens the DCer's profile
    def on_data_table_row_selected(self, event) -> None:
        if str(event.data_table.id or "").startswith("detail-table") and self.detail_tab in ("attendees", "meet"):
            user_id = str(event.row_key.value or "")
            if user_id:
                self.app.open_person({"userID": user_id})  # type: ignore[attr-defined]
            return
        super().on_data_table_row_selected(event)

    # ── attendees: one page at a time (↓ onto the last row, or "load more") ──
    def on_data_table_row_highlighted(self, event) -> None:
        super().on_data_table_row_highlighted(event)
        table = event.data_table
        if str(table.id or "").startswith("detail-table") and (self.detail_tab == "attendees") \
                and table.row_count and event.cursor_row >= table.row_count - 1:
            self.action_more_attendees()

    def action_more_attendees(self) -> None:
        item = self._detail_item
        if item is None or self.list_tab == "calls" or getattr(self, "_attendees_loading", False):
            return
        event_id = item.get("eventID")
        store = self.__dict__.setdefault("_more_attendees", {})
        data = self._detail_data if isinstance(self._detail_data, dict) else {}
        cursor = store[event_id]["cursor"] if event_id in store else next_cursor(data.get("attendees")) if data.get("attendees") else None
        if not cursor:
            return
        self._attendees_loading = True
        self._fetch_attendees(event_id, cursor)

    @work(thread=True, exclusive=True, group="attendees-more", exit_on_error=False)
    def _fetch_attendees(self, event_id: str, cursor: str) -> None:
        fetched = self.app.data.fetch("event-attendees", event_id, limit=100, cursor=cursor)  # type: ignore[attr-defined]
        self.app.call_from_thread(self._attendees_arrived, event_id, fetched)

    def _attendees_arrived(self, event_id: str, fetched: Fetched) -> None:
        self._attendees_loading = False
        if fetched.error and fetched.data is None:
            self.notify(fetched.error, severity="warning", timeout=5)
            return
        store = self.__dict__.setdefault("_more_attendees", {})
        page = [a for a in (dict_of(fetched).get("attendees") or items_of(fetched)) if isinstance(a, dict)]
        prev = store.get(event_id, {"people": []})
        store[event_id] = {"people": prev["people"] + page, "cursor": next_cursor(fetched)}
        if self._detail_item is not None and self._detail_item.get("eventID") == event_id:
            self._paint_detail()

    def _render_schedule(self, item: dict, data: Dict[str, Fetched], tab: str) -> Any:
        sessions = [s for s in (dict_of(data.get("schedule")).get("sessions") or []) if isinstance(s, dict)] if tab != "meetups" else []
        agenda = dict_of(data.get("agenda")) if data.get("agenda") is not None else {}
        bookmarked = {s.get("sessionID") for s in agenda.get("sessions") or [] if isinstance(s, dict)}
        joined = {m.get("meetupID") for m in agenda.get("meetups") or [] if isinstance(m, dict)}
        meetups = [m for m in (dict_of(data.get("meetups")).get("meetups") or []) if isinstance(m, dict)]
        entries: List[Tuple[str, str, str, dict]] = []   # (sort key, kind, id, obj)
        for s in sessions:
            entries.append((str(s.get("startAt") or s.get("date") or ""), "session", str(s.get("sessionID")), s))
        for m in meetups:
            entries.append(("%sT%s" % (m.get("date") or "", m.get("startTime") or ""), "meetup", str(m.get("meetupID")), m))
        entries.sort(key=lambda e: e[0])
        if tab == "agenda":
            entries = [e for e in entries if (e[1] == "session" and e[2] in bookmarked) or (e[1] == "meetup" and e[2] in joined)]
        rows: List[Tuple[str, List[str]]] = []
        self._rows_by_key = {}
        last_day = None
        for sort_key, kind, ident, obj in entries:
            day = sort_key[:10]
            if day != last_day:
                last_day = day
                rows.append(("day:" + day, [Text(_day_label(day), style="bold #FF4921"), "", "", ""]))
            if kind == "session":
                mark = "★" if ident in bookmarked else ""
                time = "%s–%s" % (_hhmm(obj.get("startAt")), _hhmm(obj.get("endAt")))
                who = ", ".join(sp.get("displayName") or sp.get("name") or "" for sp in obj.get("speakers") or [] if isinstance(sp, dict))
                what = "%s%s" % (obj.get("title") or "", ("  · " + who) if who else "")
                place = obj.get("place") if isinstance(obj.get("place"), dict) else {}
                where = obj.get("locationNote") or place.get("name") or ""
                rows.append(("session:" + ident, [what, time, Text(mark, style="bold #FF4921"), "%s %s" % (str(obj.get("type") or "").title(), where)]))
            else:
                mark = "✓" if ident in joined else ""
                time = "%s–%s" % (_hhmm(obj.get("startTime")), _hhmm(obj.get("endTime")))
                host = obj.get("host") if isinstance(obj.get("host"), dict) else {}
                seats = "%s/%s" % (obj.get("rsvpCount", "?"), obj.get("maxSeats", "?"))
                what = "%s  · %s" % (obj.get("title") or "", host.get("displayName") or "meetup")
                rows.append(("meetup:" + ident, [what, time, Text(mark, style="bold #80B088"), "meetup %s" % seats]))
            self._rows_by_key[rows[-1][0]] = obj
        bits = []
        if tab != "meetups":
            bits.append(plural(len(sessions), "session"))
        bits.append(plural(len(meetups), "meetup"))
        if agenda:
            bits.append("★ %d · ✓ %d" % (len(bookmarked), len(joined)))
        elif item.get("eventID") not in self._tickets:
            bits.append("no ticket — read-only")
        for key in ("schedule", "meetups", "agenda"):
            f = data.get(key)
            if isinstance(f, Fetched) and f.error:
                bits.append("[$warning]%s: %s[/]" % (key, esc(trunc(f.error, 40))))
        tz = dict_of(data.get("schedule")).get("timezone") or dict_of(data.get("meetups")).get("timezone")
        if tz:
            bits.append("times in %s" % esc(str(tz)))
        title = " · ".join(bits)
        if not rows:
            return [title, "", "[dim]%s[/dim]" % ("nothing on your agenda yet — bookmark sessions in the Schedule tab"
                                                  if tab == "agenda" else "nothing published yet")]
        return Table(("What", "Time", "", "Where"), rows, title=title, widths={"Time": 11, "": 1, "Where": 22})

    def _render_call(self, item: dict, fetched: Optional[Fetched]) -> List[str]:
        ev = dict_of(fetched).get("event") if fetched is not None else None
        ev = ev if isinstance(ev, dict) else item
        lines = []
        if ev.get("isLive"):
            lines.append("[$success]● live now[/]")
        desc = plain(ev.get("description"))
        if desc:
            lines.append(esc(trunc(desc, 700)))
        lines.append("")
        lines.append("[dim]%s · %s going · you: %s[/dim]" % (call_kind_label(ev.get("kind")), ev.get("attendeeCount") or 0,
                                                            {"yes": "Going", "no": "Not going", "maybe": "Maybe"}.get(str(ev.get("myRsvp") or ""), "no answer")))
        if ev.get("meetUrl"):
            lines.append("[dim]link:[/dim] %s  [dim](o opens it)[/dim]" % esc(ev.get("meetUrl")))
        if fetched is not None and fetched.error:
            lines.append("[$warning]%s[/]" % esc(fetched.error))
        return lines

    # ── actions ───────────────────────────────────────────────────────
    def _current(self) -> Tuple[Optional[dict], Optional[str], Optional[dict]]:
        event = self._detail_item or self.selected()
        key = self.detail_row_key()
        return event, key, (self._rows_by_key.get(key) if key else None)

    def action_bookmark(self) -> None:
        event, key, obj = self._current()
        if event is None or not key or not key.startswith("session:") or obj is None:
            self.notify("Highlight a session in the Schedule tab first (→ to move there).", timeout=4)
            return
        if event.get("eventID") not in self._tickets:
            self.notify("Bookmarking needs a ticket for this event.", severity="warning", timeout=5)
            return
        agenda = dict_of(self._detail_data.get("agenda")) if isinstance(self._detail_data, dict) else {}
        already = any(s.get("sessionID") == obj.get("sessionID") for s in agenda.get("sessions") or [] if isinstance(s, dict))
        self.mutate("session-bookmark", event.get("eventID"), obj.get("sessionID"),
                    bookmarked="false" if already else "true",
                    ok_text=("removed bookmark: " if already else "bookmarked: ") + str(obj.get("title") or ""))

    def action_join_meetup(self) -> None:
        event, key, obj = self._current()
        if event is None or not key or not key.startswith("meetup:") or obj is None:
            self.notify("Highlight a meetup in the Schedule or Meetups tab first (→ to move there).", timeout=4)
            return
        agenda = dict_of(self._detail_data.get("agenda")) if isinstance(self._detail_data, dict) else {}
        already = any(m.get("meetupID") == obj.get("meetupID") for m in agenda.get("meetups") or [] if isinstance(m, dict))
        self.mutate("meetup-rsvp", event.get("eventID"), obj.get("meetupID"), joined="false" if already else "true",
                    ok_text=("left: " if already else "joined: ") + str(obj.get("title") or ""))

    def action_rsvp(self, status: str) -> None:
        item = self._detail_item if self.detail_focused() else None
        if item is None:
            self.notify("Open the event first (→), then RSVP from its detail.", timeout=4)
            return
        if self.list_tab == "calls":
            self.mutate("virtual-event-rsvp", item.get("sessionID"), status=status,
                        ok_text="RSVP %s: %s" % (status, item.get("name")))
            return
        if not item.get("rsvpEnabled"):
            self.notify("This event sells tickets — press o to get one on the web.", severity="warning", timeout=5)
            return
        self.mutate("event-rsvp", item.get("eventID"), status=status, ok_text="RSVP %s: %s" % (status, item.get("name")))

    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)
        if fetched.ok and self.list_tab == "calls":
            self.refresh_data(force=True)


def _day_label(day: str) -> str:
    try:
        d = date.fromisoformat(day[:10])
        return d.strftime("%A %b %-d")
    except ValueError:
        return day or "undated"
