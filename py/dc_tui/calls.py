"""Live Calls — upcoming virtual sessions and your RSVP."""
from __future__ import annotations

from typing import Any, List, Tuple

from textual.binding import Binding

from .format import fmt_date, plural, trunc
from .listing import ListDetailScreen, dict_of, esc, items_of, plain
from .screens import WEB_APP


def _when(value: Any) -> str:
    s = str(value or "")
    return "%s %s" % (fmt_date(s), s[11:16]) if "T" in s else fmt_date(s)


class LiveCallsScreen(ListDetailScreen):
    SECTION = "calls"
    TITLE_TEXT = "Live Calls"
    HINT = "y RSVP yes · N RSVP no · o open the call link"
    URL = WEB_APP + "/events"
    LIST_COMMAND = "virtual-events"
    COLUMNS = ("Call", "When", "Kind", "Going", "RSVP")
    COLUMNS_COMPACT = ("Call", "When", "RSVP")
    EMPTY_TEXT = "no upcoming live calls"

    BINDINGS = [
        Binding("y", "rsvp('yes')", "RSVP yes"),
        Binding("N", "rsvp('no')", "RSVP no", show=False),
    ]

    def fetch_rows(self, force: bool) -> List[dict]:
        fetched = self.app.data.fetch("virtual-events", force=force)  # type: ignore[attr-defined]
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        calls = items_of(fetched)
        calls.sort(key=lambda c: str(c.get("scheduledAt") or ""))
        return calls

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("sessionID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        cells = {
            "Call":  ("● " if item.get("isLive") else "") + trunc(item.get("name") or "", 36 if self.two_pane else 44),
            "When":  _when(item.get("scheduledAt")),
            "Kind":  str(item.get("kind") or ""),
            "Going": str(item.get("attendeeCount") or ""),
            "RSVP":  {"yes": "✓ yes", "no": "✗ no", "maybe": "? maybe"}.get(str(item.get("myRsvp") or ""), ""),
        }
        return tuple(cells[c] for c in self._columns())

    def detail_title(self, item: dict) -> str:
        return "%s  [dim]%s · %s min[/dim]" % (esc(item.get("name")), _when(item.get("scheduledAt")), item.get("duration") or "?")

    def fetch_detail(self, item: dict, force: bool) -> Any:
        return self.app.data.fetch("virtual-event", item.get("sessionID"), force=force)  # type: ignore[attr-defined]

    def render_detail(self, item: dict, data: Any) -> List[str]:
        ev = dict_of(data).get("event") if data is not None else None
        ev = ev if isinstance(ev, dict) else item
        lines = []
        if ev.get("isLive"):
            lines.append("[$success]● live now[/]")
        desc = plain(ev.get("description"))
        if desc:
            lines.append(esc(trunc(desc, 700)))
        lines.append("")
        lines.append("[dim]%s · %s going · your RSVP: %s[/dim]" % (
            esc(ev.get("kind") or ""), ev.get("attendeeCount") or 0, esc(ev.get("myRsvp") or "—")))
        if ev.get("meetUrl"):
            lines.append("[dim]link:[/dim] %s  [dim](o opens it)[/dim]" % esc(ev.get("meetUrl")))
        if data is not None and getattr(data, "error", None):
            lines.append("[$warning]%s[/]" % esc(data.error))
        return lines

    def action_rsvp(self, status: str) -> None:
        item = self.selected()
        if item is None:
            return
        self.mutate("virtual-event-rsvp", item.get("sessionID"), status=status,
                    ok_text="RSVP %s: %s" % (status, item.get("name")))

    def after_mutation(self, fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)
        if fetched.ok:
            self.refresh_data(force=True)

    def current_url(self) -> str:
        item = self.selected()
        if item and item.get("meetUrl"):
            return str(item["meetUrl"])
        return self.URL
