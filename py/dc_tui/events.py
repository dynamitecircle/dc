"""Events — three top tabs (Global · Local · Live Calls) and a tabbed detail:
Info · Schedule · My agenda · Meetups · Attendees for in-person events, Info
for live calls. Schedule and agenda are first-class: day-grouped, ★ on your
bookmarks, ✓ on meetups you joined, one-key bookmark / join / RSVP."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.text import Text
from textual.binding import Binding

from .data import Fetched
from .format import date_range, event_dates, fmt_date, plural, strip_markdown, trunc
from .listing import ListDetailScreen, Table, dict_of, esc, items_of, plain
from .screens import WEB_APP

#: Flagship / global event types; everything else is a local chapter event.
GLOBAL_TYPES = {"dcbkk", "dcmex", "dcbcn", "dc-black", "dcb", "dc-week", "dcweek", "flagship", "global"}


def _hhmm(value: Any) -> str:
    s = str(value or "")
    if "T" in s and len(s) >= 16:
        return s[11:16]
    return s[:5] if ":" in s[:5] else ""


def _when(value: Any) -> str:
    s = str(value or "")
    return "%s %s" % (fmt_date(s), s[11:16]) if "T" in s else fmt_date(s)


def _city(event: dict) -> str:
    """City name with fallbacks — the list endpoint often leaves `city.name` null."""
    city = event.get("city") if isinstance(event.get("city"), dict) else {}
    venue = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    return str(city.get("name") or venue.get("city") or city.get("country") or "")


def _is_global(event: dict) -> bool:
    kind = str(event.get("eventType") or "").lower()
    return kind in GLOBAL_TYPES or (kind.startswith("dc") and not kind.startswith("dc-chapter"))


class EventsScreen(ListDetailScreen):
    SECTION = "events"
    TITLE_TEXT = "Events"
    HINT = "↑↓ pick an event · → open it · tabs and buttons in the detail"
    URL = WEB_APP + "/events"
    LIST_TABS = (("global", "Global"), ("local", "Local"), ("calls", "Live Calls"))
    COLUMNS = ("Event", "City", "Type", "🎟", "Dates")
    COLUMNS_COMPACT = ("Event", "🎟", "Dates")
    COLUMN_WIDTHS = {"Dates": 22, "City": 14, "Type": 16, "🎟": 2, "When": 17, "Kind": 8, "Going": 5, "RSVP": 7}
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
    def _columns(self) -> Sequence[str]:
        compact = self.app.layout_mode_name in ("compact", "single")  # type: ignore[attr-defined]
        if self.list_tab == "calls":
            return ("Call", "RSVP", "When") if compact else ("Call", "Kind", "Going", "RSVP", "When")
        return super()._columns()

    def detail_actions(self):
        item = self._detail_item or {}
        if self.list_tab == "calls":
            return [("RSVP yes", "rsvp('yes')"), ("RSVP no", "rsvp('no')"), ("Open call link", "app.open_in_browser")]
        acts = []
        if self.detail_tab in ("schedule", "agenda"):
            acts.append(("Bookmark session", "bookmark"))
        if self.detail_tab in ("schedule", "agenda", "meetups"):
            acts.append(("Join meetup", "join_meetup"))
        if item.get("rsvpEnabled"):
            acts += [("RSVP yes", "rsvp('yes')"), ("RSVP no", "rsvp('no')")]
        acts.append(("Open in app", "app.open_in_browser"))
        return acts

    def detail_tabs(self) -> Sequence[Tuple[str, str]]:
        if self.list_tab == "calls":
            return ()
        item = self._detail_item or {}
        tabs = [("info", "Info"), ("schedule", "Schedule")]
        if item.get("eventID") in self._tickets:
            tabs.append(("agenda", "My agenda"))
        tabs += [("meetups", "Meetups"), ("attendees", "Attendees")]
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
            fetched = data.fetch("virtual-events", force=force)
            if fetched.error and fetched.data is None:
                raise RuntimeError(fetched.error)
            calls = items_of(fetched)
            calls.sort(key=lambda c: str(c.get("scheduledAt") or ""))
            return calls
        tickets = data.fetch("tickets", force=force)
        self._tickets = {t.get("eventID"): t.get("ticketName") or "ticket" for t in items_of(tickets)
                         if t.get("status") in ("valid", "maybe")}
        fetched = data.fetch("events", limit=50, force=force)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        events = [e for e in items_of(fetched) if _is_global(e) == (self.list_tab == "global")]
        events.sort(key=lambda e: str(e.get("startDate") or ""))
        return events

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("eventID") or item.get("sessionID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        if self.list_tab == "calls":
            cells = {
                "Call":  ("● " if item.get("isLive") else "") + str(item.get("name") or ""),
                "When":  _when(item.get("scheduledAt")),
                "Kind":  str(item.get("kind") or ""),
                "Going": str(item.get("attendeeCount") or ""),
                "RSVP":  {"yes": "✓ yes", "no": "✗ no", "maybe": "? maybe"}.get(str(item.get("myRsvp") or ""), ""),
            }
        else:
            cells = {
                "Event": str(item.get("name") or ""),
                "Dates": event_dates(item),
                "City":  _city(item),
                "Type":  str(item.get("eventType") or ""),
                "🎟":    "🎟" if item.get("eventID") in self._tickets else "",
            }
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        label = {"global": "global events", "local": "local events", "calls": "live calls"}[self.list_tab]
        return "%d %s  [dim]%s[/dim]" % (len(self.items), label, self.HINT)

    # ── detail ────────────────────────────────────────────────────────
    def detail_title(self, item: dict) -> str:
        if self.list_tab == "calls":
            return "%s  [dim]%s · %s min[/dim]" % (esc(item.get("name")), _when(item.get("scheduledAt")), item.get("duration") or "?")
        ticket = self._tickets.get(item.get("eventID"))
        venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}
        where = " · ".join(x for x in (venue.get("name"), _city(item)) if x)
        return "%s  [dim]%s · %s%s[/dim]" % (esc(item.get("name")), event_dates(item) + ("" if item.get("isDateConfirmed") is not False else " (dates TBC)"),
                                             esc(where), "  · 🎟 " + esc(ticket) if ticket else "")

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
        if tab == "attendees":
            out["attendees"] = data.fetch("event-attendees", event_id, limit=100, force=force)
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
        return self._render_schedule(item, data, tab)

    def _render_info(self, item: dict, fetched: Optional[Fetched]) -> List[str]:
        ev = dict_of(fetched).get("event") if fetched is not None else None
        ev = ev if isinstance(ev, dict) else item
        lines: List[str] = []
        desc = strip_markdown(ev.get("description") or ev.get("descriptionShort") or "")
        if desc:
            lines.append(esc(trunc(desc, 900)))
        venue = ev.get("venue") if isinstance(ev.get("venue"), dict) else {}
        if venue.get("name"):
            lines.append("")
            lines.append("[dim]venue:[/dim] %s" % esc(", ".join(x for x in (venue.get("name"), venue.get("city"), venue.get("country")) if x)))
        if ev.get("venueInfo"):
            lines.append("[dim]%s[/dim]" % esc(trunc(plain(ev.get("venueInfo")), 300)))
        flags = []
        if ev.get("ticketsEnabled"):
            flags.append("tickets")
        if ev.get("rsvpEnabled"):
            flags.append("free RSVP")
        my = dict_of(fetched).get("myTickets") if fetched is not None else None
        if isinstance(my, list) and my:
            flags.append("you hold %s" % plural(len(my), "ticket"))
        if flags:
            lines.append("[dim]%s[/dim]" % " · ".join(flags))
        if fetched is not None and fetched.error:
            lines.append("[$warning]%s[/]" % esc(fetched.error))
        return lines

    def _render_attendees(self, item: dict, fetched: Optional[Fetched]) -> Any:
        body = dict_of(fetched)
        people = [a for a in (body.get("attendees") or items_of(fetched)) if isinstance(a, dict)] if fetched else []
        rows = [(str(a.get("userID")), [a.get("displayName") or a.get("userName") or "", plain(a.get("headline") or ""),
                                        a.get("businessIndustry") or ""]) for a in people]
        total = body.get("total")
        title = "%s attending%s" % (plural(len(people), "DCer"), (" of %s" % total) if isinstance(total, int) and total > len(people) else "")
        if fetched is not None and fetched.error:
            title += "  [$warning]%s[/]" % esc(fetched.error)
        if not rows:
            return [title, "", "[dim]no attendee list yet[/dim]"]
        return Table(("Name", "Headline", "Industry"), rows, title=title, widths={"Headline": 34, "Industry": 16})

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
                rows.append(("session:" + ident, [what, time, Text(mark, style="bold #FF4921"), "%s %s" % (obj.get("type") or "", where)]))
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
        lines.append("[dim]%s · %s going · your RSVP: %s[/dim]" % (esc(ev.get("kind") or ""), ev.get("attendeeCount") or 0, esc(ev.get("myRsvp") or "—")))
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
            self.notify("This event sells tickets — press o to get one in the app.", severity="warning", timeout=5)
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
