"""Trips — your upcoming trips and, for each, the discovery block: who to
meet (AI-ranked picks with why), everyone around, and events in town."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from textual.binding import Binding

from .data import Fetched
from .format import date_range, plural, trunc
from .forms import ConfirmModal, TripForm
from .listing import ListDetailScreen, dict_of, esc, items_of, plain
from .screens import WEB_APP


def _place(trip: dict) -> dict:
    loc = trip.get("location")
    return loc if isinstance(loc, dict) else {}


class TripsScreen(ListDetailScreen):
    SECTION = "trips"
    TITLE_TEXT = "Trips"
    HINT = "↑↓ pick a trip · → open it · Edit / Delete are buttons in the detail"
    LIST_ACTIONS = (("＋ New trip", "new_trip"),)
    URL = WEB_APP + "/trips"
    LIST_COMMAND = "trips"
    COLUMNS = ("Where", "Note", "Dates")             # dates always last, flush right
    COLUMNS_COMPACT = ("Where", "Dates")
    COLUMN_WIDTHS = {"Note": 24, "Dates": 25}      # cross-year ranges carry both years
    COLUMN_DROP = ("Note",)
    EMPTY_TEXT = "no upcoming trips yet — click New trip above to plan one"

    BINDINGS = [
        Binding("n", "new_trip", "New", show=False),
        Binding("e", "edit_trip", "Edit", show=False),
        Binding("d", "delete_trip", "Delete", show=False),
        Binding("R", "refresh_discovery", "Re-match", show=False),
    ]

    def fetch_rows(self, force: bool) -> List[dict]:
        fetched = self.app.data.fetch("trips", force=force)  # type: ignore[attr-defined]
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        trips = items_of(fetched)
        trips.sort(key=lambda t: str(t.get("startDate") or ""))
        return trips

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("tripID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        p = _place(item)
        where = ", ".join(x for x in (p.get("name") or p.get("city"), p.get("countryCode")) if x) or "?"
        cells = {"Where": trunc(where, 28), "Dates": date_range(item.get("startDate"), item.get("endDate")),
                 "Note": trunc(plain(item.get("note")), 40)}
        return tuple(cells[c] for c in self._columns())

    def detail_actions(self):
        return [("New trip", "new_trip"), ("Edit", "edit_trip"), ("Delete", "delete_trip"),
                ("Re-match", "refresh_discovery"), ("Open on web", "app.open_in_browser")]

    def action_open_detail(self) -> None:
        if not self.items:
            self.action_new_trip()      # empty list: Enter starts a trip
            return
        super().action_open_detail()

    # ── detail: discovery ─────────────────────────────────────────────
    def detail_title(self, item: dict) -> str:
        p = _place(item)
        return "%s  [dim]%s[/dim]" % (esc(p.get("name") or p.get("city") or "trip"),
                                      date_range(item.get("startDate"), item.get("endDate")))

    def fetch_detail(self, item: dict, force: bool) -> Any:
        return self.app.data.fetch("trip", item.get("tripID"), force=force)  # type: ignore[attr-defined]

    def render_detail(self, item: dict, data: Any) -> List[str]:
        if data is None:
            return ["[dim]loading…[/dim]"]
        lines: List[str] = []
        if item.get("note"):
            lines.append("[dim]%s[/dim]" % esc(plain(item.get("note"))))
        body = dict_of(data)
        trip = body.get("trip") if isinstance(body.get("trip"), dict) else body
        disc = trip.get("discovery") if isinstance(trip.get("discovery"), dict) else {}
        if data.error:
            lines.append("[$warning]%s[/]" % esc(data.error))
        picks = _list(disc, "people", "picks", "topPicks", "recommended")
        pool = _list(disc, "fullPool", "pool", "around")
        events = _list(disc, "events", "eventsInTown")
        if picks:
            lines.append("")
            lines.append("[b]Who to meet[/b]  [dim]%s[/dim]" % plural(len(picks), "pick"))
            for p in picks[:10]:
                prof = p.get("profile") if isinstance(p.get("profile"), dict) else p
                name = prof.get("displayName") or prof.get("userName") or "?"
                head = prof.get("headline") or prof.get("businessName") or ""
                why = p.get("whyToMeet") or p.get("why") or p.get("reason") or ""
                lines.append("👤 [b]%s[/b]  [dim]%s[/dim]" % (esc(name), esc(trunc(plain(head), 60))))
                if why:
                    lines.append("   %s" % esc(trunc(plain(why), 260)))
        if pool:
            lines.append("")
            names = [(p.get("profile") if isinstance(p.get("profile"), dict) else p) for p in pool]
            names = [n.get("displayName") or n.get("userName") or "" for n in names if isinstance(n, dict)]
            lines.append("[b]Around[/b]  [dim]%s[/dim]" % plural(len(pool), "DCer"))
            lines.append(esc(trunc(", ".join(n for n in names if n), 400)))
        if events:
            lines.append("")
            lines.append("[b]Events in town[/b]")
            for e in events[:6]:
                lines.append("  %s  [dim]%s[/dim]" % (esc(trunc(e.get("name") or e.get("eventName") or "", 44)),
                                                      date_range(e.get("startDate"), e.get("endDate"))))
        if not (picks or pool or events):
            lines.append("")
            lines.append("[dim]discovery is still being computed — press R to refresh[/dim]")
        return lines

    # ── actions ───────────────────────────────────────────────────────
    def action_new_trip(self) -> None:
        self.app.push_screen(TripForm(), self._save_trip)

    def action_edit_trip(self) -> None:
        item = self.selected()
        if item is None:
            return
        p = _place(item)
        self.app.push_screen(TripForm({"trip_id": item.get("tripID"), "place_id": p.get("placeID"),
                                       "place_name": p.get("name") or p.get("city"),
                                       "start_date": str(item.get("startDate") or "")[:10],
                                       "end_date": str(item.get("endDate") or "")[:10],
                                       "note": item.get("note") or ""}), self._save_trip)

    def _save_trip(self, form: Optional[Dict[str, Any]]) -> None:
        if not form:
            return
        kwargs = {"start_date": form["start_date"], "end_date": form["end_date"],
                  "place_id": form["place_id"], "note": form.get("note") or ""}
        if form.get("trip_id"):
            self.mutate("trip-update", form["trip_id"], ok_text="trip to %s updated" % form["place_name"], **kwargs)
        else:
            self.mutate("trip-create", ok_text="trip to %s created" % form["place_name"], **kwargs)

    def action_delete_trip(self) -> None:
        item = self.selected()
        if item is None:
            return
        p = _place(item)
        where = p.get("name") or p.get("city") or "this trip"
        def _go(yes: bool) -> None:
            if yes:
                self.mutate("trip-delete", item.get("tripID"), ok_text="trip to %s deleted" % where)
        self.app.push_screen(ConfirmModal("Delete the trip to %s (%s)?" % (
            where, date_range(item.get("startDate"), item.get("endDate"))), yes="Delete"), _go)

    def action_refresh_discovery(self) -> None:
        item = self.selected()
        if item is None:
            return
        self.mutate("trip-refresh", item.get("tripID"), ok_text="discovery refresh queued")

    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)
        if fetched.ok:
            self._detail_item = None
            self.refresh_data(force=True)


def _list(d: dict, *keys: str) -> List[dict]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, list):
            return [i for i in v if isinstance(i, dict)]
        if isinstance(v, dict) and isinstance(v.get("items"), list):
            return [i for i in v["items"] if isinstance(i, dict)]
    return []
