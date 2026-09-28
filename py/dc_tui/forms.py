"""Modal forms: a yes/no confirm and the trip editor."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [Binding("y", "yes", "Yes"), Binding("n,escape", "no", "No")]
    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    #confirm-box { width: 60; max-width: 96%; height: auto; border: round $primary; background: $surface; padding: 1 2; }
    #confirm-box Horizontal { height: auto; align-horizontal: right; }
    #confirm-box Button { margin: 1 0 0 1; }
    """

    def __init__(self, question: str, *, yes: str = "Yes", no: str = "No") -> None:
        super().__init__()
        self._question, self._yes, self._no = question, yes, no

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._question)
            with Horizontal():
                yield Button(self._no, id="no")
                yield Button(self._yes, id="yes", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class TripForm(ModalScreen[Optional[Dict[str, Any]]]):
    """Create / edit a trip: place (searched live), dates, note.

    Returns `{"place_id", "place_name", "start_date", "end_date", "note"}` or
    None when cancelled.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "save", "Save")]
    DEFAULT_CSS = """
    TripForm { align: center middle; }
    #trip-box { width: 72; max-width: 98%; height: auto; max-height: 95%; border: round $primary;
                background: $surface; padding: 1 2; }
    #trip-box Label { color: $text-muted; margin-top: 1; }
    #trip-box #title { color: $primary; text-style: bold; margin-top: 0; }
    #places { height: auto; max-height: 8; }
    #trip-box Horizontal { height: auto; align-horizontal: right; }
    #trip-box Button { margin: 1 0 0 1; }
    #trip-error { color: $error; height: auto; }
    """

    def __init__(self, initial: Optional[Dict[str, Any]] = None) -> None:
        super().__init__()
        self.initial = dict(initial or {})
        self.place_id: str = str(self.initial.get("place_id") or "")
        self.place_name: str = str(self.initial.get("place_name") or "")
        self._search_timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="trip-box"):
            yield Static("Edit trip" if self.initial.get("trip_id") else "New trip", id="title")
            yield Label("Where (type to search cities)")
            yield Input(value=self.place_name, placeholder="Lisbon", id="place")
            yield OptionList(id="places")
            yield Label("Start date (YYYY-MM-DD)")
            yield Input(value=str(self.initial.get("start_date") or ""), placeholder="2026-11-03", id="start")
            yield Label("End date (YYYY-MM-DD)")
            yield Input(value=str(self.initial.get("end_date") or ""), placeholder="2026-11-10", id="end")
            yield Label("Note (optional)")
            yield Input(value=str(self.initial.get("note") or ""), placeholder="Keen to meet SaaS founders", id="note")
            yield Static("", id="trip-error")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Save  ctrl+s", id="save", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#place", Input).focus()

    # ── place search (debounced, cached) ──────────────────────────────
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "place":
            return
        self.place_id = ""
        if self._search_timer is not None:
            self._search_timer.stop()
        query = event.value.strip()
        if len(query) >= 2:
            self._search_timer = self.set_timer(0.6, lambda: self._search(query))

    @work(thread=True, exclusive=True, group="places", exit_on_error=False)
    def _search(self, query: str) -> None:
        fetched = self.app.data.fetch("places-search", q=query, limit=8)  # type: ignore[attr-defined]
        data = fetched.data if isinstance(fetched.data, dict) else {}
        places = data.get("items") if isinstance(data.get("items"), list) else data.get("places") or []
        self.app.call_from_thread(self._show_places, [p for p in places if isinstance(p, dict)])

    def _show_places(self, places: List[dict]) -> None:
        options = self.query_one("#places", OptionList)
        options.clear_options()
        for p in places:
            label = ", ".join(x for x in (p.get("name"), p.get("region"), p.get("country")) if x)
            options.add_option(Option(label, id=str(p.get("placeID") or "")))
        self._place_labels = {str(p.get("placeID") or ""): p.get("name") or "" for p in places}

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.place_id = str(event.option.id or "")
        self.place_name = str(getattr(self, "_place_labels", {}).get(self.place_id) or event.option.prompt)
        self.query_one("#place", Input).value = self.place_name
        self.query_one("#start", Input).focus()

    # ── save / cancel ─────────────────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        start = self.query_one("#start", Input).value.strip()
        end = self.query_one("#end", Input).value.strip()
        note = self.query_one("#note", Input).value.strip()
        problems = []
        if not self.place_id:
            problems.append("pick a place from the search results")
        for label, value in (("start", start), ("end", end)):
            if len(value) != 10 or value[4] != "-" or value[7] != "-":
                problems.append("%s date must be YYYY-MM-DD" % label)
        if not problems and end < start:
            problems.append("end date is before start date")
        if problems:
            self.query_one("#trip-error", Static).update("· " + "\n· ".join(problems))
            return
        self.dismiss({"trip_id": self.initial.get("trip_id"), "place_id": self.place_id,
                      "place_name": self.place_name, "start_date": start, "end_date": end, "note": note})
