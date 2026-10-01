"""Locator — the Friday locator digest as a full page: who is coming to your
city, what is happening in the cities you follow, where the people you follow
are going, and your own trips. Same data as the email (`GET /locator/digest`),
compacted: a person who shows up several times is one row with all their
plans; an event that several followed people attend is one row listing them.

Every row is selectable: Enter opens the person, trip, event or city."""
from __future__ import annotations

import webbrowser
from typing import Any, Dict, List, Optional, Set, Tuple

from textual import work
from textual.binding import Binding
from textual.widgets import OptionList, Static, Tabs

from .data import Fetched
from .format import align_row, date_range, event_dates, flag, fmt_date, guard_flags, pad, plural, say_count_title, trunc
from .labels import event_type_label
from .screens import DCScreen, WEB_APP
from .widgets import Panel


def _esc(text: Any) -> str:
    return str(text if text is not None else "").replace("[", r"\[")


def _member(row: dict) -> dict:
    m = row.get("member")
    return m if isinstance(m, dict) else {}


def _place(row: dict) -> str:
    loc = row.get("location") if isinstance(row.get("location"), dict) else {}
    name = str(loc.get("city") or loc.get("name") or "")
    fl = flag(loc.get("countryCode"))
    return ("%s %s" % (fl, name)) if (fl and name) else name


def _name(m: dict) -> str:
    return str(m.get("displayName") or m.get("userName") or "someone")


def _person_target(m: dict):
    return ("person", m) if m else ("people", None)


class LocatorScreen(DCScreen):
    """The web Locator tab (LocatorDigest.vue), card per block in the web's order:
    your home chapter, each chapter you follow, DCers you follow, then one card
    per trip of yours. Titles use the web's SayCount wording ("Five new trips")."""

    SECTION = "locator"
    TITLE_TEXT = "Locator"
    HINT = "your chapter · chapters you follow · DCers you follow · your trips"
    URL = WEB_APP + "/locator"
    HAS_DETAIL = False
    AUTO_FOCUS = "#main"
    SUB_TABS = True

    BINDINGS = [
        Binding("up", "card_up", "Up", show=False, priority=True),
        Binding("down", "card_down", "Down", show=False, priority=True),
        Binding("pageup", "card_page_up", "Page up", show=False, priority=True),
        Binding("pagedown", "card_page_down", "Page down", show=False, priority=True),
        Binding("home", "card_home", "Top", show=False, priority=True),
        Binding("end", "card_end", "Bottom", show=False, priority=True),
        Binding("enter", "open_row", "Open", show=False),
    ]

    #: web caps: trip lists show 10, a member's nested trips 5 (LocatorTripList / LocatorGroupedTripList)
    TRIP_CAP = 10
    NESTED_CAP = 5

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self._expanded: Set[str] = set()
        self._last_fetched: Optional[Fetched] = None
        self._card_ids: List[str] = []

    def populate(self) -> None:
        self.set_main(Panel("Locator", id="l-loading"))
        self.refresh_data(force=False)

    def refresh_data(self, force: bool = False) -> None:
        for panel in self.query(Panel):
            panel.set_loading()
        self._load(force)

    @work(thread=True, exclusive=True, group="locator", exit_on_error=False)
    def _load(self, force: bool) -> None:
        fetched = self.app.data.fetch("locator", force=force)  # type: ignore[attr-defined]
        # The digest's event and ticket dates carry no isDateConfirmed, and ticket
        # dates are a copy taken at purchase. The events list is the truth for both.
        events = self.app.data.fetch("events", limit=100)  # type: ignore[attr-defined]
        _EVENTS.clear()
        _EVENTS.update({str(e.get("eventID")): e for e in _list(dict_of_items(events)) if e.get("eventID")})
        self.app.call_from_thread(self._render_digest, fetched)
        self.app.call_from_thread(self.app.refresh_status)  # type: ignore[attr-defined]

    def _card_width(self) -> int:
        pane = self.main_pane().size.width or self.app.size.width
        width = pane - 6                                   # pane padding + card border + card padding
        measured = [p.row_width() for p in self.query(Panel) if p.row_width() > 10]
        if measured:
            return min(measured)
        return max(20, width - 1)

    def on_resize(self, event) -> None:
        super().on_resize(event)
        if self._last_fetched is not None:
            self._render_digest(self._last_fetched)            # rows re-fit to the new width

    # ── rendering ────────────────────────────────────────────────────
    def _render_digest(self, f: Fetched) -> None:
        self._last_fetched = f
        digest = f.data if isinstance(f.data, dict) else {}
        width = self._card_width()
        exp = self._expanded
        cards: List[Tuple[str, str, List[Tuple[str, Any]], str]] = []     # (id, title, rows, subtitle)
        if f.error and not digest:
            cards.append(("l-error", "Locator", [("[$warning]Couldn't load the Locator.[/] %s — press r to try again." % _esc(f.error), None)], ""))
        elif not _digest_has_content(digest):
            cards.append(("l-empty", "Locator", [("Your Locator is empty.", None),
                                                 ("[dim]Set your home city in your profile, follow some DCers, or plan a trip and your Locator will start filling up here.[/dim]", None)], ""))
        else:
            home = digest.get("homeCity") if isinstance(digest.get("homeCity"), dict) else None
            if home:
                cards.append(_city_card("l-home", home, True, width, exp))
            for i, c in enumerate(c for c in digest.get("favoriteCities") or [] if isinstance(c, dict)):
                cards.append(_city_card("l-city-%d" % i, c, False, width, exp))
            people = digest.get("favoritePeople") if isinstance(digest.get("favoritePeople"), dict) else {}
            if any(people.get(k) for k in ("newTrips", "comingTrips", "purchased", "attending")):
                cards.append(("l-people", "DCers you follow", _people_rows(people, width, exp), ""))
            for i, t in enumerate(sorted((t for t in digest.get("myTrips") or [] if isinstance(t, dict)),
                                         key=lambda t: str(_trip_of(t).get("startDate") or ""))):
                cards.append(_my_trip_card("l-trip-%d" % i, t, width, exp))
        if cards:
            refreshed = "just now" if not (f.from_cache and f.age >= 60) else _ago(f.age)
            note = (" · ⚠ " + trunc(f.error, 30)) if f.error else " · Last refreshed %s" % refreshed
            cid, title, rows, sub = cards[0]
            cards[0] = (cid, title, rows, (sub + note).lstrip(" ·"))
        ids = [c[0] for c in cards]
        if ids != self._card_ids:
            self._card_ids = ids
            self._remount(cards)
        else:
            for cid, title, rows, sub in cards:
                self._paint(cid, title, rows, sub)

    @work(exclusive=True, group="locator-cards", exit_on_error=False)
    async def _remount(self, cards) -> None:
        pane = self.main_pane()
        await pane.remove_children()
        await pane.mount(*[Panel(guard_flags(title), id=cid) for cid, title, _, _ in cards])
        for cid, title, rows, sub in cards:
            self._paint(cid, title, rows, sub)
        # the first paint was sized before layout; re-fit once the cards have a width
        self.call_after_refresh(lambda: self._last_fetched is not None and self._render_digest(self._last_fetched))
        if self.focused is None or self.focused is self.main_pane():
            self.call_after_refresh(self.focus_content)

    def _paint(self, pid: str, title: str, rows: List[Tuple[str, Any]], subtitle: str) -> None:
        try:
            panel = self.query_one("#%s" % pid, Panel)
        except Exception:  # noqa: BLE001
            return
        panel.border_title = guard_flags(title)
        panel.set_rows(rows, subtitle=guard_flags(subtitle))

    # ── navigation (same model as Home) ───────────────────────────────
    def _cards(self) -> List[Panel]:
        return [p for p in self.query(Panel) if p.selectable()]

    def _focused_card(self) -> Optional[Panel]:
        f = self.focused
        return f.parent if isinstance(f, OptionList) and isinstance(f.parent, Panel) else None

    def focus_content(self) -> None:
        cards = self._cards()
        if cards:
            cards[0].first()
            cards[0].list.focus()
        else:
            self.main_pane().focus()

    def _jump(self, card: Panel, *, last: bool = False) -> None:
        card.list.focus()
        (card.last if last else card.first)()
        card.scroll_visible()

    def _move(self, step: int) -> None:
        card, cards = self._focused_card(), self._cards()
        if card is None:
            if isinstance(self.focused, Tabs):
                if self.bar_step(self.focused, step):
                    return
                if step > 0 and cards:
                    self._jump(cards[0])
                return
            if cards:
                self._jump(cards[0] if step > 0 else cards[-1], last=step < 0)
            else:
                self._page(step)
            return
        if step < 0 and not card.at_first():
            card.list.action_cursor_up()
            return
        if step > 0 and not card.at_last():
            card.list.action_cursor_down()
            return
        i = cards.index(card) if card in cards else -1
        nxt = i + step
        if 0 <= nxt < len(cards):
            self._jump(cards[nxt], last=step < 0)
        elif nxt < 0:
            self.focus_bar()

    def action_card_up(self) -> None:
        self._move(-1)

    def action_card_down(self) -> None:
        self._move(1)

    def _card_step(self, step: int) -> None:
        cards, card = self._cards(), self._focused_card()
        if not cards:
            return
        i = cards.index(card) if card in cards else (-1 if step > 0 else len(cards))
        self._jump(cards[max(0, min(len(cards) - 1, i + step))])

    def action_card_page_up(self) -> None:
        self._card_step(-1)

    def action_card_page_down(self) -> None:
        self._card_step(1)

    def action_card_home(self) -> None:
        if self._cards():
            self._jump(self._cards()[0])

    def action_card_end(self) -> None:
        if self._cards():
            self._jump(self._cards()[-1], last=True)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        card = event.option_list.parent
        if isinstance(card, Panel):
            self._open(card.target())

    def action_open_row(self) -> None:
        card = self._focused_card()
        if card is not None:
            self._open(card.target())

    def _open(self, target) -> None:
        if not target:
            return
        kind, key = target
        if kind == "expand":                              # "Show N more" / "Show less"
            self._expanded.symmetric_difference_update({key})
            if self._last_fetched is not None:
                self._render_digest(self._last_fetched)
            return
        if kind == "url":
            webbrowser.open(str(key))
            self.app.notify("Opened in browser", timeout=2)
        elif kind == "person":
            self.app.open_person(key)  # type: ignore[attr-defined]
        else:
            self.app.open_in_section(kind, key)  # type: ignore[attr-defined]




#: eventID → event from GET /events (dates + isDateConfirmed), refreshed with the digest.
_EVENTS: Dict[str, dict] = {}


def dict_of_items(f: Any) -> List[dict]:
    data = getattr(f, "data", None)
    return list(data.get("items") or []) if isinstance(data, dict) else []


def _dates_for(event_id: Any, start: Any, end: Any) -> str:
    """The event's own dates (month only while unconfirmed, as dc-web's formatDates),
    falling back to the digest's copy only for events the list does not carry."""
    truth = _EVENTS.get(str(event_id)) if event_id else None
    return event_dates(truth) if truth else date_range(start, end)


# ── builders — one per web component ─────────────────────────────────
def _head(title: str, indent: str = "") -> Tuple[str, Any]:
    return ("%s[dim]%s[/dim]" % (indent, _esc(title)), None)


def _say(n: int, one: str, many: str, tail: str = "") -> str:
    """`${SayCount(n)} ${n === 1 ? one : many} tail` — the web's title formula."""
    return ("%s %s %s" % (say_count_title(n), one if n == 1 else many, tail)).strip()


def _ago(seconds: float) -> str:
    m = int(seconds // 60)
    if m < 60:
        return "%d min%s ago" % (m, "" if m == 1 else "s")
    h = m // 60
    if h < 24:
        return "%d hour%s ago" % (h, "" if h == 1 else "s")
    d = h // 24
    return "%d day%s ago" % (d, "" if d == 1 else "s")


def _list(items: Any) -> List[dict]:
    return [x for x in (items or []) if isinstance(x, dict)]


def _more_row(key: str, hidden: int, expanded: bool, indent: str = "") -> Tuple[str, Any]:
    text = "Show less" if expanded else "Show %d more" % hidden
    return ("%s[dim]%s[/dim]" % (indent, text), ("expand", key))


def _capped(rows_per_item: List[List[Tuple[str, Any]]], cap: int, key: str, exp: Set[str], indent: str = "") -> List[Tuple[str, Any]]:
    """First `cap` items, then a Show N more / Show less toggle (LocatorTripList)."""
    open_ = key in exp
    shown = rows_per_item if (open_ or len(rows_per_item) <= cap) else rows_per_item[:cap]
    out = [r for rows in shown for r in rows]
    if len(rows_per_item) > cap:
        out.append(_more_row(key, len(rows_per_item) - cap, open_, indent))
    return out


def _city_card(cid: str, c: dict, is_home: bool, width: int, exp: Set[str]):
    """LocatorCityBlock.vue — heading "DC {city} Chapter" (+ Home), sub-sections in web order."""
    city = c.get("cityName") or "your city"
    rows: List[Tuple[str, Any]] = []
    new_events = c.get("createdEvents") if is_home else c.get("newEvents")
    rows += _event_section(_say(len(_list(new_events)), "new event", "new events", "in %s" % city), new_events, width)
    rows += _event_section(_say(len(_list(c.get("comingEvents"))), "upcoming event", "upcoming events", "in %s" % city), c.get("comingEvents"), width)
    planning = _list(c.get("planningToCity") if is_home else c.get("newTrips"))
    if is_home:
        title = _say(len(planning), "DCer", "DCers", "planning trips to %s" % city)
    else:
        title = _say(len(planning), "new trip", "new trips", "to %s" % city)
    rows += _trip_section(title, planning, width, key=cid + ":planning", exp=exp)
    coming = _list(c.get("comingToCity") if is_home else c.get("comingTrips"))
    rows += _trip_section(_say(len(coming), "DCer", "DCers", "coming to %s" % city), coming, width, key=cid + ":coming", exp=exp)
    members = _list(c.get("newMembers"))
    fresh = [m for m in members if m.get("isNewToDC") is True]
    joined = [m for m in members if m.get("isNewToDC") is not True]
    rows += _member_section(_say(len(fresh), "new DCer", "new DCers", "just joined DC and the %s chapter" % city), fresh, width)
    rows += _member_section(_say(len(joined), "DCer", "DCers", "joined the %s chapter" % city), joined, width)
    heading = "%s DC %s Chapter%s" % (flag(c.get("countryCode")) or "📍", city, " · Home" if is_home else "")
    if not rows:
        rows = [("[dim]Nothing here yet.[/dim]", None)]
    return (cid, heading, rows, "")


def _member_section(title: str, members: List[dict], width: int) -> List[Tuple[str, Any]]:
    if not members:
        return []
    rows = [_head(title)]
    for m in members:
        rows.append((align_row(width, _name(m), fmt_date(m.get("joinedAt")) if m.get("joinedAt") else "", m.get("headline") or "",
                               prefix="👤 "), _person_target(m)))
    return rows


def _people_rows(people: dict, width: int, exp: Set[str]) -> List[Tuple[str, Any]]:
    """LocatorFavoritePeople.vue — counts from the flat arrays, rows from the grouped ones."""
    rows: List[Tuple[str, Any]] = []
    rows += _grouped_trip_section(_say(len(_list(people.get("newTrips"))), "new trip", "new trips", "from DCers you follow"),
                                  people.get("newTripsGrouped"), people.get("newTrips"), width, "people:new", exp)
    rows += _grouped_trip_section(_say(len(_list(people.get("comingTrips"))), "more upcoming trip", "more upcoming trips"),
                                  people.get("comingTripsGrouped"), people.get("comingTrips"), width, "people:coming", exp)
    rows += _event_group_section(_say(len(_list(people.get("purchased"))), "ticket", "tickets", "just purchased"),
                                 people.get("purchasedByEvent"), people.get("purchased"), "got a ticket to", "bought tickets to", width, icon="🎫 ")
    rows += _event_group_section(_say(len(_list(people.get("attending"))), "event", "events", "your follows are attending"),
                                 people.get("attendingByEvent"), people.get("attending"), "is attending", "are attending", width)
    return rows or [("[dim]Nothing here yet.[/dim]", None)]


def _trip_of(entry: dict) -> dict:
    t = entry.get("trip")
    return t if isinstance(t, dict) else entry


def _my_trip_card(cid: str, entry: dict, width: int, exp: Set[str]):
    """LocatorMyTripSection.vue — "Your trip to {city}", dates + overlap badge (digits)."""
    trip = _trip_of(entry)
    city = entry.get("cityName") or _place(trip) or "a city"
    overlap = _list(entry.get("plannedTrips"))
    leads = _list(entry.get("chapterLeads"))
    locals_ = _list(entry.get("localMembers"))
    badge = ", ".join(b for b in ("%d DCer%s overlap" % (len(overlap), "" if len(overlap) == 1 else "s") if overlap else "",
                                  "%d chapter lead%s" % (len(leads), "" if len(leads) == 1 else "s") if leads else "") if b)
    rows: List[Tuple[str, Any]] = []
    rows.append((align_row(width, "✈ " + (_place(trip) or city), date_range(trip.get("startDate"), trip.get("endDate")), badge, name_markup="%s"),
                 ("trips", trip.get("tripID")) if trip.get("tripID") else None))
    rows += _trip_section(_say(len(overlap), "DCer", "DCers", "also visiting"), overlap, width, key=cid + ":overlap", exp=exp)
    local = leads + locals_
    if local:
        rows.append(_head(_say(len(local), "local DCer", "local DCers")))
        per = []
        for m in local:
            per.append([(align_row(width, _name(m), "", "chapter lead" if m in leads else "", prefix="👤 "), _person_target(m))])
        rows += _capped(per, 10, cid + ":local", exp)
    return (cid, "Your trip to %s" % city, rows, "")


def _trip_section(title: str, trips: Any, width: int, *, key: str, exp: Set[str], show_place: bool = False) -> List[Tuple[str, Any]]:
    trips = _list(trips)
    if not trips:
        return []                      # empty sub-sections are hidden, like the web
    return [_head(title)] + _trip_group_rows(_group_by_member(trips), width, show_place=show_place, key=key, exp=exp)


def _grouped_trip_section(title: str, grouped: Any, flat: Any, width: int, key: str, exp: Set[str]) -> List[Tuple[str, Any]]:
    flat = _list(flat)
    groups = _list(grouped) if isinstance(grouped, list) else None
    if groups is None:
        groups = _group_by_member(flat)          # older payloads: group here
    if not groups:
        return []
    return [_head(title)] + _trip_group_rows(groups, width, show_place=True, key=key, exp=exp)


def _trip_target(t: dict, m: dict):
    url = t.get("shortURL") or t.get("tripURL")
    return ("url", url) if url else _person_target(m)


def _digest_has_content(digest: dict) -> bool:
    """useLocatorDigest.ts isEmpty: no home city, no followed chapters, nothing from follows, no trips."""
    if isinstance(digest.get("homeCity"), dict) or _list(digest.get("favoriteCities")) or _list(digest.get("myTrips")):
        return True
    people = digest.get("favoritePeople") if isinstance(digest.get("favoritePeople"), dict) else {}
    return any(people.get(k) for k in ("newTrips", "comingTrips", "purchased", "attending"))


def _group_by_member(trips: List[dict]) -> List[dict]:
    """groupTripsByMember: {member, trips[] soonest-first}, members by earliest trip."""
    by: Dict[str, Dict[str, Any]] = {}
    for t in trips:
        m = _member(t)
        key = str(m.get("userID") or _name(m))
        entry = by.setdefault(key, {"member": m, "trips": {}})
        entry["trips"][str(t.get("tripID") or id(t))] = t
    groups = [{"member": e["member"], "trips": sorted(e["trips"].values(), key=lambda x: str(x.get("startDate") or "9"))} for e in by.values()]
    groups.sort(key=lambda g: str(g["trips"][0].get("startDate") or "9") if g["trips"] else "9")
    return groups


def _trip_group_rows(groups: List[dict], width: int, *, show_place: bool, key: str, exp: Set[str]) -> List[Tuple[str, Any]]:
    """LocatorGroupedTripList.vue: one row per member; one trip → "planned a trip to X",
    several → "planned N trips" with the trips one column in (first 5, then +N more)."""
    per_member: List[List[Tuple[str, Any]]] = []
    for g in groups:
        m = g.get("member") if isinstance(g.get("member"), dict) else {}
        trips = _list(g.get("trips"))
        if not trips:
            continue
        if len(trips) == 1:
            t = trips[0]
            extra = ("planned a trip to " + (_place(t) or "Somewhere")) if show_place else (t.get("note") or "")
            per_member.append([(align_row(width, _name(m), date_range(t.get("startDate"), t.get("endDate")), extra, prefix="👤 "), _person_target(m))])
            continue
        rows = [(align_row(width, _name(m), "", "planned %d trips" % len(trips), prefix="👤 "), _person_target(m))]
        nested = [[(align_row(width, _place(t) or "Somewhere", date_range(t.get("startDate"), t.get("endDate")), prefix=" ", name_markup="%s"),
                    _trip_target(t, m))] for t in trips]
        rows += _capped(nested, LocatorScreen.NESTED_CAP, "%s:%s" % (key, m.get("userID") or _name(m)), exp, indent=" ")
        per_member.append(rows)
    return _capped(per_member, LocatorScreen.TRIP_CAP, key, exp)


def _group_by_event(tickets: List[dict]) -> List[dict]:
    """groupTicketsByEvent: {eventID, eventName, dates, members[] unique}, events soonest-first."""
    by: Dict[str, Dict[str, Any]] = {}
    for t in tickets:
        key = str(t.get("eventID") or t.get("eventName"))
        e = by.setdefault(key, {"eventID": t.get("eventID"), "eventName": t.get("eventName") or "Untitled event",
                                "startDate": t.get("startDate"), "endDate": t.get("endDate"), "shortURL": t.get("shortURL") or t.get("eventURL"),
                                "members": [], "_seen": set()})
        m = _member(t)
        uid = str(m.get("userID") or _name(m))
        if uid not in e["_seen"]:
            e["_seen"].add(uid)
            e["members"].append(m)
    groups = sorted(by.values(), key=lambda g: str(g.get("startDate") or "9"))
    for g in groups:
        g["count"] = len(g["members"])
    return groups


def _name_list(names: List[str], cap: int = 5) -> str:
    """formatNameList: 'A', 'A and B', 'A, B and C', 'A, B, C, D, E and 3 others'."""
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) <= cap:
        return names[0] if len(names) == 1 else "%s and %s" % (", ".join(names[:-1]), names[-1])
    extra = len(names) - cap
    return "%s and %d other%s" % (", ".join(names[:cap]), extra, "" if extra == 1 else "s")


def _event_group_section(title: str, grouped: Any, flat: Any, verb_one: str, verb_many: str, width: int,
                         icon: str = "📅 ") -> List[Tuple[str, Any]]:
    flat = [t for t in (flat or []) if isinstance(t, dict)]
    groups = [g for g in (grouped or []) if isinstance(g, dict)] if isinstance(grouped, list) else None
    if groups is None:
        groups = _group_by_event(flat)
    if not groups:
        return []
    rows: List[Tuple[str, Any]] = [_head(title)]
    for g in groups:
        members = [m for m in g.get("members") or [] if isinstance(m, dict)]
        names = [_name(m) for m in members] or [str(x) for x in g.get("memberNames") or []]
        count = int(g.get("count") or len(names))
        verb = verb_many if count > 1 else verb_one
        sentence = "%s %s %s" % (_name_list(names), verb, trunc(g.get("eventName") or "Untitled event", 40))
        when = _dates_for(g.get("eventID"), g.get("startDate") or (g.get("eventDates") or {}).get("startDate"),
                          g.get("endDate") or (g.get("eventDates") or {}).get("endDate"))
        target = ("events", g.get("eventID")) if g.get("eventID") else (("url", g.get("shortURL")) if g.get("shortURL") else None)
        rows.append((align_row(width, sentence, when, prefix=icon, name_markup="%s"), target))
    return rows


def _dedupe_events(events: List[dict]) -> List[dict]:
    seen, out = set(), []
    for e in sorted(events, key=lambda x: str(x.get("startDate") or "")):
        key = e.get("eventID") or e.get("name")
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _event_row(e: dict, width: int, indent: str = "") -> Tuple[str, Any]:
    city = e.get("city") if isinstance(e.get("city"), dict) else {}
    name = e.get("name") or e.get("eventName") or "Untitled event"
    kind = event_type_label(e.get("eventType"))
    extra = city.get("name") or ("" if kind.lower() in str(name).lower() else kind)   # no "Junto Junto"
    truth = _EVENTS.get(str(e.get("eventID")))
    return (align_row(width, name, event_dates(truth if truth else e), extra, prefix=indent + "📅 ", name_markup="%s"),
            ("events", e.get("eventID")) if e.get("eventID") else None)


def _event_section(title: str, events: Any, width: int) -> List[Tuple[str, Any]]:
    events = _dedupe_events(_list(events))
    if not events:
        return []
    return [_head(title)] + [_event_row(e, width) for e in events]
