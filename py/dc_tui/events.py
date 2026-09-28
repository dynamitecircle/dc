"""Events — in-person events with the schedule and your agenda first-class:
a day-grouped sessions table, ★ on bookmarked sessions, meetups with your
RSVP, and one-key bookmark / join / RSVP actions."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from textual.binding import Binding

from .data import Fetched
from .format import date_range, fmt_date, plural, trunc
from .listing import ListDetailScreen, Table, dict_of, esc, items_of, plain
from .screens import WEB_APP


def _hhmm(value: Any) -> str:
    s = str(value or "")
    if "T" in s and len(s) >= 16:
        return s[11:16]
    return s[:5] if ":" in s[:5] else ""


class EventsScreen(ListDetailScreen):
    SECTION = "events"
    TITLE_TEXT = "Events"
    HINT = "Enter/Tab schedule · b bookmark · j join meetup · y/N RSVP · g my agenda · o open"
    URL = WEB_APP + "/events"
    LIST_COMMAND = "events"
    COLUMNS = ("Event", "Dates", "City", "Type", "Ticket")
    COLUMNS_COMPACT = ("Event", "Dates", "Ticket")
    EMPTY_TEXT = "no upcoming events"

    BINDINGS = [
        Binding("b", "bookmark", "Bookmark"),
        Binding("j", "join_meetup", "Join"),
        Binding("y", "rsvp('yes')", "RSVP yes"),
        Binding("N", "rsvp('no')", "RSVP no", show=False),
        Binding("g", "toggle_agenda", "My agenda"),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._tickets: Dict[str, str] = {}
        self.agenda_only = False
        self._rows_by_key: Dict[str, dict] = {}

    # ── rows ──────────────────────────────────────────────────────────
    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        tickets = data.fetch("tickets", force=force)
        self._tickets = {t.get("eventID"): t.get("ticketName") or "ticket" for t in items_of(tickets)
                         if t.get("status") in ("valid", "maybe")}
        fetched = data.fetch("events", limit=50, force=force)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        events = items_of(fetched)
        events.sort(key=lambda e: str(e.get("startDate") or ""))
        return events

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("eventID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        cells = {
            "Event":  trunc(item.get("name") or "", 34 if self.two_pane else 44),
            "Dates":  date_range(item.get("startDate"), item.get("endDate")),
            "City":   trunc(_city(item), 16),
            "Type":   str(item.get("eventType") or ""),
            "Ticket": "🎟" if item.get("eventID") in self._tickets else "",
        }
        return tuple(cells[c] for c in self._columns())

    # ── detail: schedule + agenda + meetups ───────────────────────────
    def detail_title(self, item: dict) -> str:
        ticket = self._tickets.get(item.get("eventID"))
        venue = item.get("venue") if isinstance(item.get("venue"), dict) else {}
        where = " · ".join(x for x in (venue.get("name"), _city(item)) if x)
        return "%s  [dim]%s · %s%s[/dim]" % (esc(item.get("name")), date_range(item.get("startDate"), item.get("endDate")),
                                             esc(where), "  · 🎟 " + esc(ticket) if ticket else "")

    def fetch_detail(self, item: dict, force: bool) -> Any:
        data = self.app.data  # type: ignore[attr-defined]
        event_id = item.get("eventID")
        out = {"schedule": data.fetch("event-schedule", event_id, force=force),
               "meetups":  data.fetch("event-meetups", event_id, force=force)}
        if event_id in self._tickets:
            out["agenda"] = data.fetch("event-agenda", event_id, force=force)
        return out

    def render_detail(self, item: dict, data: Any) -> Any:
        if not isinstance(data, dict):
            return ["[dim]loading…[/dim]"]
        sessions = _sessions(data["schedule"])
        agenda = dict_of(data.get("agenda")) if data.get("agenda") is not None else {}
        bookmarked = {s.get("sessionID") for s in agenda.get("sessions") or [] if isinstance(s, dict)}
        joined = {m.get("meetupID") for m in agenda.get("meetups") or [] if isinstance(m, dict)}
        meetups = [m for m in (dict_of(data["meetups"]).get("meetups") or []) if isinstance(m, dict)]
        rows: List[Tuple[str, List[str]]] = []
        self._rows_by_key = {}
        entries: List[Tuple[str, str, str, dict]] = []   # (sort key, kind, id, obj)
        for s in sessions:
            entries.append((str(s.get("startAt") or s.get("date") or ""), "session", str(s.get("sessionID")), s))
        for m in meetups:
            entries.append(("%sT%s" % (m.get("date") or "", m.get("startTime") or ""), "meetup", str(m.get("meetupID")), m))
        entries.sort(key=lambda e: e[0])
        if self.agenda_only:
            entries = [e for e in entries if (e[1] == "session" and e[2] in bookmarked) or (e[1] == "meetup" and e[2] in joined)]
        last_day = None
        compact = not self.two_pane and self.app.layout_mode_name == "compact"  # type: ignore[attr-defined]
        for sort_key, kind, ident, obj in entries:
            day = sort_key[:10]
            if day != last_day:
                last_day = day
                rows.append(("day:" + day, ["", "[b]%s[/b]" % _day_label(day), "", ""]))
            if kind == "session":
                mark = "★" if ident in bookmarked else ""
                time = "%s–%s" % (_hhmm(obj.get("startAt")), _hhmm(obj.get("endAt")))
                who = ", ".join(sp.get("displayName") or sp.get("name") or "" for sp in obj.get("speakers") or [] if isinstance(sp, dict))
                what = "%s [dim]%s[/dim]" % (esc(trunc(obj.get("title") or "", 34 if compact else 56)), esc(trunc(who, 30)) if who else "")
                where = obj.get("locationNote") or (obj.get("place") or {}).get("name") if isinstance(obj.get("place"), dict) else obj.get("locationNote")
                rows.append(("session:" + ident, [mark, time, what, esc(trunc(str(obj.get("type") or ""), 10)) + ("  " + esc(trunc(where or "", 18)) if where else "")]))
            else:
                mark = "✓" if ident in joined else ""
                time = "%s–%s" % (_hhmm(obj.get("startTime")), _hhmm(obj.get("endTime")))
                host = obj.get("host") if isinstance(obj.get("host"), dict) else {}
                seats = "%s/%s" % (obj.get("rsvpCount", "?"), obj.get("maxSeats", "?"))
                what = "%s [dim]meetup · %s[/dim]" % (esc(trunc(obj.get("title") or "", 34 if compact else 50)), esc(host.get("displayName") or ""))
                rows.append(("meetup:" + ident, [mark, time, what, "meetup " + seats]))
            self._rows_by_key[rows[-1][0]] = obj
        title_bits = [plural(len(sessions), "session"), plural(len(meetups), "meetup")]
        if agenda:
            title_bits.append("%d bookmarked · %d joined" % (len(bookmarked), len(joined)))
        elif item.get("eventID") not in self._tickets:
            title_bits.append("no ticket — schedule is read-only")
        for key in ("schedule", "meetups", "agenda"):
            f = data.get(key)
            if isinstance(f, Fetched) and f.error:
                title_bits.append("[$warning]%s: %s[/]" % (key, esc(trunc(f.error, 40))))
        desc = plain(item.get("descriptionShort") or "")
        title = ("[dim]%s[/dim]\n" % esc(trunc(desc, 200)) if desc else "") + " · ".join(title_bits)
        if self.agenda_only:
            title += "  [b]my agenda[/b]"
        if not rows:
            return [title, "", "[dim]no schedule published yet[/dim]"]
        return Table(("", "Time", "What", "Where"), rows, title=title)

    # ── actions ───────────────────────────────────────────────────────
    def _current(self) -> Tuple[Optional[dict], Optional[str], Optional[dict]]:
        event = self._detail_item or self.selected()
        key = self.detail_row_key()
        return event, key, (self._rows_by_key.get(key) if key else None)

    def action_bookmark(self) -> None:
        event, key, obj = self._current()
        if event is None or not key or not key.startswith("session:"):
            self.notify("Highlight a session in the schedule first (Tab to move there).", timeout=4)
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
        if event is None or not key or not key.startswith("meetup:"):
            self.notify("Highlight a meetup in the schedule first (Tab to move there).", timeout=4)
            return
        agenda = dict_of(self._detail_data.get("agenda")) if isinstance(self._detail_data, dict) else {}
        already = any(m.get("meetupID") == obj.get("meetupID") for m in agenda.get("meetups") or [] if isinstance(m, dict))
        self.mutate("meetup-rsvp", event.get("eventID"), obj.get("meetupID"), joined="false" if already else "true",
                    ok_text=("left: " if already else "joined: ") + str(obj.get("title") or ""))

    def action_rsvp(self, status: str) -> None:
        event = self.selected()
        if event is None:
            return
        if not event.get("rsvpEnabled"):
            self.notify("This event sells tickets — press o to get one in the app.", severity="warning", timeout=5)
            return
        self.mutate("event-rsvp", event.get("eventID"), status=status, ok_text="RSVP %s: %s" % (status, event.get("name")))

    def action_toggle_agenda(self) -> None:
        self.agenda_only = not self.agenda_only
        self._paint_detail()

    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)


def _sessions(fetched: Any) -> List[dict]:
    body = dict_of(fetched)
    return [s for s in (body.get("sessions") or []) if isinstance(s, dict)]


def _day_label(day: str) -> str:
    try:
        d = date.fromisoformat(day[:10])
        return d.strftime("%A %b %-d")
    except ValueError:
        return day or "undated"


def _city(event: dict) -> str:
    """City name with fallbacks — the list endpoint often leaves `city.name` null."""
    city = event.get("city") if isinstance(event.get("city"), dict) else {}
    venue = event.get("venue") if isinstance(event.get("venue"), dict) else {}
    return str(city.get("name") or venue.get("city") or city.get("country") or "")
