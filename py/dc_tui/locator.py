"""Locator — the Friday locator digest as a full page: who is coming to your
city, what is happening in the cities you follow, where the people you follow
are going, and your own trips. Same data as the email (`GET /locator/digest`),
compacted: a person who shows up several times is one row with all their
plans; an event that several followed people attend is one row listing them.

Every row is selectable: Enter opens the person, trip, event or city."""
from __future__ import annotations

import webbrowser
from typing import Any, Dict, List, Optional, Tuple

from textual import work
from textual.binding import Binding
from textual.widgets import OptionList, Static, Tabs

from .data import Fetched
from .format import align_row, date_range, fmt_date, pad, plural, trunc
from .screens import DCScreen, WEB_APP
from .widgets import Panel


def _esc(text: Any) -> str:
    return str(text if text is not None else "").replace("[", r"\[")


def _member(row: dict) -> dict:
    m = row.get("member")
    return m if isinstance(m, dict) else {}


def _place(row: dict) -> str:
    loc = row.get("location") if isinstance(row.get("location"), dict) else {}
    return str(loc.get("city") or loc.get("name") or "")


def _name(m: dict) -> str:
    return str(m.get("displayName") or m.get("userName") or "someone")


def _person_target(m: dict):
    return ("person", m) if m else ("people", None)


class LocatorScreen(DCScreen):
    SECTION = "locator"
    TITLE_TEXT = "Locator"
    HINT = "your Friday digest, live"
    URL = WEB_APP + "/locator"
    HAS_DETAIL = False

    BINDINGS = [
        Binding("up", "card_up", "Up", show=False, priority=True),
        Binding("down", "card_down", "Down", show=False, priority=True),
        Binding("pageup", "card_page_up", "Page up", show=False, priority=True),
        Binding("pagedown", "card_page_down", "Page down", show=False, priority=True),
        Binding("home", "card_home", "Top", show=False, priority=True),
        Binding("end", "card_end", "Bottom", show=False, priority=True),
        Binding("enter", "open_row", "Open", show=False),
    ]

    CARDS = [("l-home", "Your city"), ("l-cities", "Cities you follow"),
             ("l-people", "People you follow"), ("l-trips", "Your trips")]

    def populate(self) -> None:
        self.set_main(*[Panel(title, id=pid) for pid, title in self.CARDS])
        self.refresh_data(force=False)

    def refresh_data(self, force: bool = False) -> None:
        for panel in self.query(Panel):
            panel.set_loading()
        self._load(force)

    @work(thread=True, exclusive=True, group="locator", exit_on_error=False)
    def _load(self, force: bool) -> None:
        fetched = self.app.data.fetch("locator", force=force)  # type: ignore[attr-defined]
        self.app.call_from_thread(self._render_digest, fetched)
        self.app.call_from_thread(self.app.refresh_status)  # type: ignore[attr-defined]

    def _card_width(self) -> int:
        try:
            width = self.query_one("#l-home", Panel).size.width - 4     # border + padding
        except Exception:  # noqa: BLE001
            width = self.main_pane().size.width - 6
        return max(24, width - 1)

    # ── rendering — mirrors the web digest (LocatorDigest.vue) ─────────
    def _render_digest(self, f: Fetched) -> None:
        digest = f.data if isinstance(f.data, dict) else {}
        flag = (" · ⚠ " + trunc(f.error, 30)) if f.error else (" · stale" if f.stale else "")
        width = self._card_width()
        self._paint("l-home", *self._home(digest, width), flag)
        self._paint("l-cities", *self._cities(digest, width), flag)
        self._paint("l-people", *self._people(digest, width), flag)
        self._paint("l-trips", *self._trips(digest, width), flag)
        if not any(p.selectable() for p in self.query(Panel)) and not f.error:
            self._paint("l-home", [("Your digest is empty. Set your home city in your profile, follow some DCers, "
                                    "or plan a trip and it will start filling up here.", None)], "", "")
        if self.focused is None or self.focused is self.main_pane():
            self.call_after_refresh(self.focus_content)

    def _paint(self, pid: str, rows: List[Tuple[str, Any]], subtitle: str, flag: str) -> None:
        try:
            self.query_one("#%s" % pid, Panel).set_rows(rows, subtitle=subtitle + flag)
        except Exception:  # noqa: BLE001
            pass

    def _home(self, digest: dict, width: int) -> Tuple[List[Tuple[str, Any]], str]:
        home = digest.get("homeCity") if isinstance(digest.get("homeCity"), dict) else {}
        city = home.get("cityName") or "your city"
        rows: List[Tuple[str, Any]] = []
        new = [m for m in home.get("newMembers") or [] if isinstance(m, dict)]
        if new:
            rows.append(_head("New DCers in %s" % city, len(new)))
            for m in new:
                mm = _member(m) or m
                rows.append(("  👋 [b]%s[/b]  [dim]%s[/dim]" % (_esc(_name(mm)), _esc(trunc(mm.get("headline") or "", width - 30))), _person_target(mm)))
        rows += _trip_section("Planning trips to %s" % city, home.get("planningToCity"), width, show_place=False)
        rows += _trip_section("Coming to %s soon" % city, home.get("comingToCity"), width, show_place=False)
        rows += _event_section("New events in %s" % city, home.get("createdEvents"), width)
        rows += _event_section("Upcoming events in %s" % city, home.get("comingEvents"), width)
        n = sum(len(home.get(k) or []) for k in ("newMembers", "planningToCity", "comingToCity", "createdEvents", "comingEvents"))
        title = "DC %s Chapter · Home" % city if home.get("cityName") else "set your home city in your profile"
        return rows or [("[dim]quiet week in %s[/dim]" % _esc(city), None)], "%s · %s" % (_esc(title), plural(n, "item"))

    def _cities(self, digest: dict, width: int) -> Tuple[List[Tuple[str, Any]], str]:
        cities = [c for c in digest.get("favoriteCities") or [] if isinstance(c, dict)]
        rows: List[Tuple[str, Any]] = []
        for c in cities:
            name = c.get("cityName") or "a city"
            n = sum(len(c.get(k) or []) for k in ("newTrips", "comingTrips", "newEvents", "comingEvents"))
            link = c.get("shortURL") or c.get("chapterURL")
            rows.append(("★ [b]DC %s Chapter[/b]  [dim]%s[/dim]" % (_esc(name), plural(n, "item")), ("url", link) if link else None))
            rows += _trip_section("New trips to %s" % name, c.get("newTrips"), width, show_place=False, indent="  ")
            rows += _trip_section("Coming to %s soon" % name, c.get("comingTrips"), width, show_place=False, indent="  ")
            rows += _event_section("New events in %s" % name, c.get("newEvents"), width, indent="  ")
            rows += _event_section("Upcoming events in %s" % name, c.get("comingEvents"), width, indent="  ")
        return rows or [("[dim]follow a chapter and its comings and goings show up here[/dim]", None)], plural(len(cities), "city")

    def _people(self, digest: dict, width: int) -> Tuple[List[Tuple[str, Any]], str]:
        people = digest.get("favoritePeople") if isinstance(digest.get("favoritePeople"), dict) else {}
        rows: List[Tuple[str, Any]] = []
        rows += _grouped_trip_section("New trips", people.get("newTripsGrouped"), people.get("newTrips"), width)
        rows += _grouped_trip_section("Coming up", people.get("comingTripsGrouped"), people.get("comingTrips"), width)
        rows += _event_group_section("Recently purchased tickets", people.get("purchasedByEvent"), people.get("purchased"), "got a ticket to", "bought tickets to", width)
        rows += _event_group_section("Attending events you're going to", people.get("attendingByEvent"), people.get("attending"), "is attending", "are attending", width)
        n = sum(len(people.get(k) or []) for k in ("newTrips", "comingTrips", "purchased", "attending"))
        return rows or [("[dim]follow DCers and their plans show up here[/dim]", None)], "%s you follow · %s" % ("DCers", plural(n, "item"))

    def _trips(self, digest: dict, width: int) -> Tuple[List[Tuple[str, Any]], str]:
        trips = [t for t in digest.get("myTrips") or [] if isinstance(t, dict)]
        rows: List[Tuple[str, Any]] = []
        for t in sorted(trips, key=lambda t: str(t.get("startDate") or "")):
            city = t.get("cityName") or _place(t) or "somewhere"
            overlap = [x for x in t.get("plannedTrips") or [] if isinstance(x, dict)]
            leads = [x for x in t.get("chapterLeads") or [] if isinstance(x, dict)]
            locals_ = [x for x in t.get("localMembers") or [] if isinstance(x, dict)]
            pill = " · ".join(b for b in (plural(len(overlap), "DCer") + " overlap" if overlap else "", plural(len(leads), "chapter lead") if leads else "") if b)
            rows.append((align_row(width, "Your trip to " + city, date_range(t.get("startDate"), t.get("endDate")), pill, prefix="✈  "),
                         ("trips", t.get("tripID")) if t.get("tripID") else None))
            rows += _trip_section("DCers also visiting", overlap, width, show_place=False, indent="  ")
            if leads or locals_:
                rows.append(_head("Local DCers", len(leads) + len(locals_), indent="  "))
                for m in (leads + locals_)[:10]:
                    mm = _member(m) or m
                    rows.append(("    [b]%s[/b]  [dim]%s[/dim]" % (_esc(_name(mm)), "chapter lead" if m in leads else ""), _person_target(mm)))
        return rows or [("[dim]no upcoming trips[/dim] — Enter to plan one", ("trips", None))], plural(len(trips), "trip")

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
            self.query_one("#nav-tabs", Tabs).focus()

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
        if kind == "url":
            webbrowser.open(str(key))
            self.app.notify("Opened in browser", timeout=2)
        elif kind == "person":
            self.app.open_person(key)  # type: ignore[attr-defined]
        else:
            self.app.open_in_section(kind, key)  # type: ignore[attr-defined]


# ── compaction helpers (mirror server groupLocator.ts + web renderers) ──

def _head(title: str, count: int, indent: str = "") -> Tuple[str, Any]:
    return ("%s[dim]%s · %d[/dim]" % (indent, _esc(title), count), None)


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


def _trip_group_rows(groups: List[dict], width: int, *, show_place: bool, indent: str) -> List[Tuple[str, Any]]:
    rows: List[Tuple[str, Any]] = []
    for g in groups:
        m = g.get("member") if isinstance(g.get("member"), dict) else {}
        trips = [t for t in g.get("trips") or [] if isinstance(t, dict)]
        if not trips:
            continue
        if len(trips) == 1:
            t = trips[0]
            extra = ("→ " + (_place(t) or "somewhere")) if show_place else (t.get("note") or "")
            rows.append((align_row(width, _name(m), date_range(t.get("startDate"), t.get("endDate")), extra, prefix=indent), _person_target(m)))
        else:
            rows.append((align_row(width, _name(m), "", "planned %s" % plural(len(trips), "trip"), prefix=indent), _person_target(m)))
            for t in trips:
                rows.append((align_row(width, _place(t) or "somewhere", date_range(t.get("startDate"), t.get("endDate")), prefix=indent + "    ", name_markup="%s"),
                             ("url", t.get("shortURL") or t.get("tripURL")) if (t.get("shortURL") or t.get("tripURL")) else _person_target(m)))
    return rows


def _trip_section(title: str, trips: Any, width: int, *, show_place: bool, indent: str = "") -> List[Tuple[str, Any]]:
    trips = [t for t in (trips or []) if isinstance(t, dict)]
    if not trips:
        return []                      # empty sub-sections are hidden, like the web
    return [_head(title, len(trips), indent)] + _trip_group_rows(_group_by_member(trips), width, show_place=show_place, indent=indent + "  ")


def _grouped_trip_section(title: str, grouped: Any, flat: Any, width: int) -> List[Tuple[str, Any]]:
    flat = [t for t in (flat or []) if isinstance(t, dict)]
    groups = [g for g in (grouped or []) if isinstance(g, dict)] if isinstance(grouped, list) else None
    if groups is None:
        groups = _group_by_member(flat)          # older payloads: group here
    if not groups:
        return []
    return [_head(title, len(flat) or len(groups))] + _trip_group_rows(groups, width, show_place=True, indent="  ")


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


def _event_group_section(title: str, grouped: Any, flat: Any, verb_one: str, verb_many: str, width: int) -> List[Tuple[str, Any]]:
    flat = [t for t in (flat or []) if isinstance(t, dict)]
    groups = [g for g in (grouped or []) if isinstance(g, dict)] if isinstance(grouped, list) else None
    if groups is None:
        groups = _group_by_event(flat)
    if not groups:
        return []
    rows: List[Tuple[str, Any]] = [_head(title, len(flat) or len(groups))]
    for g in groups:
        members = [m for m in g.get("members") or [] if isinstance(m, dict)]
        names = [_name(m) for m in members] or [str(x) for x in g.get("memberNames") or []]
        count = int(g.get("count") or len(names))
        verb = verb_many if count > 1 else verb_one
        sentence = "%s %s %s" % (_name_list(names), verb, trunc(g.get("eventName") or "Untitled event", 40))
        when = date_range(g.get("startDate") or (g.get("eventDates") or {}).get("startDate"), g.get("endDate") or (g.get("eventDates") or {}).get("endDate"))
        target = ("events", g.get("eventID")) if g.get("eventID") else (("url", g.get("shortURL")) if g.get("shortURL") else None)
        rows.append(("  %s  [dim]%s[/dim]" % (sentence, when), target))
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


def _event_row(e: dict, width: int, indent: str = "  ") -> Tuple[str, Any]:
    city = e.get("city") if isinstance(e.get("city"), dict) else {}
    return (align_row(width, e.get("name") or e.get("eventName") or "Untitled event", date_range(e.get("startDate"), e.get("endDate")),
                      city.get("name") or e.get("eventType") or "", prefix=indent + "📅 ", name_markup="%s"),
            ("events", e.get("eventID")) if e.get("eventID") else None)


def _event_section(title: str, events: Any, width: int, indent: str = "") -> List[Tuple[str, Any]]:
    events = _dedupe_events([e for e in (events or []) if isinstance(e, dict)])
    if not events:
        return []
    return [_head(title, len(events), indent)] + [_event_row(e, width, indent + "  ") for e in events]
