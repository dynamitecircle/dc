"""`ListDetailScreen` — the base for every section that is "a list of things
plus one selected thing": Rooms, Trips, Events, Live Calls, People.

Layout follows the app's mode: in `split`/`wide` the list sits left and the
selected item's detail right; in `compact`/`single` there is only the list,
and Enter swaps the pane to the detail (Esc comes back). Highlighting a row
loads its detail after a short debounce so scrolling through a list does not
spend API budget on every row.

Concrete screens implement:
  fetch_rows(force)            -> List[dict]           (worker thread)
  row_cells(item)              -> tuple of cell strings, matching COLUMNS
  fetch_detail(item, force)    -> Any                  (worker thread; may return None)
  render_detail(item, data)    -> List[str] | Table    (UI thread)
and add their own BINDINGS for actions on `self.selected()`.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from textual import work
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import DataTable, Static

from .data import Fetched
from .format import trunc
from .screens import DCScreen

_TAGS = re.compile(r"<[^>]+>")


def plain(text: Any, is_html: bool = False) -> str:
    """Message/summary text as one line of plain text."""
    s = str(text or "")
    if is_html or "<" in s and ">" in s:
        s = _html.unescape(_TAGS.sub(" ", s))
    return " ".join(s.split())


def esc(text: Any) -> str:
    return str(text if text is not None else "").replace("[", r"\[")


class Table:
    """A detail rendered as a second DataTable (e.g. an event schedule)."""

    def __init__(self, columns: Sequence[str], rows: Sequence[Tuple[str, Sequence[str]]], *, title: str = ""):
        self.columns = list(columns)
        self.rows = list(rows)          # (row key, cells)
        self.title = title


class ListDetailScreen(DCScreen):
    COLUMNS: Sequence[str] = ()
    COLUMNS_COMPACT: Sequence[str] = ()   # subset used under 100 cols; empty = same as COLUMNS
    EMPTY_TEXT = "nothing here yet"
    DETAIL_DEBOUNCE = 0.45
    LIST_COMMAND = ""                     # cache command name, for invalidation on refresh

    BINDINGS = [
        Binding("enter", "open_detail", "Detail", show=False),
        Binding("escape", "close_detail", "Back", show=False),
        Binding("tab", "focus_next_pane", "Next pane", show=False),
    ]

    DEFAULT_CSS = """
    ListDetailScreen #list { height: auto; max-height: 100%; }
    ListDetailScreen #list-hint { color: $text-muted; height: auto; padding: 0 1; }
    ListDetailScreen #detail-title { color: $primary; text-style: bold; height: auto; }
    ListDetailScreen #detail-body { height: auto; }
    ListDetailScreen #detail-table { height: auto; max-height: 100%; }
    ListDetailScreen .-hidden { display: none; }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.items: List[dict] = []
        self._keys: Dict[str, dict] = {}
        self._detail_timer = None
        self._detail_open = False          # one-pane mode: detail shown in #main
        self._detail_item: Optional[dict] = None
        self._detail_data: Any = None
        self._hint = ""

    # ── build ─────────────────────────────────────────────────────────
    def populate(self) -> None:
        table = DataTable(id="list", cursor_type="row", zebra_stripes=True)
        self.set_main(Static("", id="list-hint"), table,
                      Vertical(Static("", id="detail-title"), Static("", id="detail-body"),
                               DataTable(id="detail-table", cursor_type="row", zebra_stripes=True),
                               id="detail-inline", classes="-hidden"))
        self.detail_pane().mount(Static("", id="detail-title-pane"), Static("", id="detail-body-pane"),
                                 DataTable(id="detail-table-pane", cursor_type="row", zebra_stripes=True))
        self._setup_columns()
        self.set_hint(self.HINT)
        self.refresh_data(force=False)

    def _setup_columns(self) -> None:
        table = self.query_one("#list", DataTable)
        table.clear(columns=True)
        for col in self._columns():
            table.add_column(col, key=col)

    def _columns(self) -> Sequence[str]:
        compact = self.app.layout_mode_name in ("compact", "single")  # type: ignore[attr-defined]
        return self.COLUMNS_COMPACT if (compact and self.COLUMNS_COMPACT) else self.COLUMNS

    def set_layout_mode(self, mode: str) -> None:
        before = self._columns() if self.is_mounted else None
        super().set_layout_mode(mode)
        if not self.is_mounted or not self.items:
            return
        if self._columns() != before:
            self._setup_columns()
            self._fill_table()
        if self.two_pane and self._detail_open:
            self._show_inline_detail(False)
        self._paint_detail()

    @property
    def two_pane(self) -> bool:
        return bool(self.HAS_DETAIL and self.app.layout_mode_name in ("split", "wide"))  # type: ignore[attr-defined]

    def set_hint(self, text: str) -> None:
        self._hint = text
        try:
            self.query_one("#list-hint", Static).update(text)
        except Exception:  # noqa: BLE001
            pass

    # ── data ──────────────────────────────────────────────────────────
    def refresh_data(self, force: bool = False) -> None:
        self.set_hint("loading…")
        self._load_rows(force)

    @work(thread=True, exclusive=True, group="rows", exit_on_error=False)
    def _load_rows(self, force: bool) -> None:
        try:
            rows = self.fetch_rows(force)
            error = ""
        except Exception as exc:  # noqa: BLE001
            rows, error = [], str(exc)
        self.app.call_from_thread(self._rows_loaded, rows, error)
        self.app.call_from_thread(self.app.refresh_status)  # type: ignore[attr-defined]

    def _rows_loaded(self, rows: List[dict], error: str) -> None:
        self.items = rows
        self._fill_table()
        if error:
            self.set_hint("[$warning]%s[/]" % esc(error))
        else:
            self.set_hint(self.hint_text())
        if rows and self.two_pane and self._detail_item is None:
            self._select_row(0)

    def hint_text(self) -> str:
        return "%d · %s" % (len(self.items), self.HINT) if self.items else self.EMPTY_TEXT

    def _fill_table(self) -> None:
        table = self.query_one("#list", DataTable)
        table.clear()
        self._keys = {}
        for i, item in enumerate(self.items):
            key = self.row_key(item, i)
            self._keys[key] = item
            table.add_row(*[esc(c) for c in self.row_cells(item)], key=key)

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("id") or index)

    def selected(self) -> Optional[dict]:
        table = self.query_one("#list", DataTable)
        if not self.items or table.cursor_row is None or table.cursor_row < 0:
            return None
        try:
            key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        except Exception:  # noqa: BLE001
            return None
        return self._keys.get(str(key))

    def _select_row(self, index: int) -> None:
        table = self.query_one("#list", DataTable)
        if table.row_count:
            table.move_cursor(row=index)
            item = self.selected()
            if item is not None:
                self._queue_detail(item)

    # ── detail ────────────────────────────────────────────────────────
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "list":
            return
        item = self._keys.get(str(event.row_key.value)) if event.row_key is not None else None
        if item is not None and self.two_pane:
            self._queue_detail(item)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "list":
            self.action_open_detail()

    def _queue_detail(self, item: dict) -> None:
        if self._detail_timer is not None:
            self._detail_timer.stop()
        self._detail_timer = self.set_timer(self.DETAIL_DEBOUNCE, lambda: self.load_detail(item))

    def load_detail(self, item: dict, force: bool = False) -> None:
        self._detail_item = item
        self._detail_data = None
        self._set_detail_title(self.detail_title(item) + "  [dim]loading…[/dim]")
        self._load_detail(item, force)

    @work(thread=True, exclusive=True, group="detail", exit_on_error=False)
    def _load_detail(self, item: dict, force: bool) -> None:
        try:
            data = self.fetch_detail(item, force)
        except Exception as exc:  # noqa: BLE001
            data = Fetched("detail", None, from_cache=False, stale=False, age=0.0, error=str(exc), fetched_at=0.0)
        self.app.call_from_thread(self._detail_loaded, item, data)
        self.app.call_from_thread(self.app.refresh_status)  # type: ignore[attr-defined]

    def _detail_loaded(self, item: dict, data: Any) -> None:
        if item is not self._detail_item:
            return
        self._detail_data = data
        self._paint_detail()

    def _paint_detail(self) -> None:
        item = self._detail_item
        if item is None:
            return
        self._set_detail_title(self.detail_title(item))
        try:
            rendered = self.render_detail(item, self._detail_data)
        except Exception as exc:  # noqa: BLE001
            rendered = ["[$error]%s[/]" % esc(exc)]
        body, table = self._detail_widgets()
        if isinstance(rendered, Table):
            body.update(rendered.title)
            table.remove_class("-hidden")
            table.clear(columns=True)
            for col in rendered.columns:
                table.add_column(col, key=col)
            for key, cells in rendered.rows:
                table.add_row(*[esc(c) for c in cells], key=key)
        else:
            table.add_class("-hidden")
            body.update("\n".join(rendered) if rendered else "[dim]nothing to show[/dim]")

    def _detail_widgets(self) -> Tuple[Static, DataTable]:
        if self.two_pane:
            return (self.query_one("#detail-body-pane", Static), self.query_one("#detail-table-pane", DataTable))
        return (self.query_one("#detail-body", Static), self.query_one("#detail-table", DataTable))

    def _set_detail_title(self, text: str) -> None:
        for wid in ("#detail-title", "#detail-title-pane"):
            try:
                self.query_one(wid, Static).update(text)
            except Exception:  # noqa: BLE001
                pass

    def detail_table(self) -> DataTable:
        return self.query_one("#detail-table-pane" if self.two_pane else "#detail-table", DataTable)

    def detail_row_key(self) -> Optional[str]:
        """Key of the highlighted row in the detail table, if any."""
        table = self.detail_table()
        if table.has_class("-hidden") or not table.row_count or table.cursor_row is None:
            return None
        try:
            return str(table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value)
        except Exception:  # noqa: BLE001
            return None

    # ── one-pane detail toggle ────────────────────────────────────────
    def _show_inline_detail(self, show: bool) -> None:
        self._detail_open = show
        self.query_one("#list", DataTable).set_class(show, "-hidden")
        self.query_one("#list-hint", Static).set_class(show, "-hidden")
        self.query_one("#detail-inline", Vertical).set_class(not show, "-hidden")

    def action_open_detail(self) -> None:
        item = self.selected()
        if item is None:
            return
        if self.two_pane:
            self.load_detail(item)
            return
        self._show_inline_detail(True)
        self.load_detail(item)

    def action_close_detail(self) -> None:
        if self._detail_open:
            self._show_inline_detail(False)
            self.query_one("#list", DataTable).focus()

    def action_focus_next_pane(self) -> None:
        table = self.detail_table()
        lst = self.query_one("#list", DataTable)
        if table.has_class("-hidden"):
            lst.focus()
        elif lst.has_focus:
            table.focus()
        else:
            lst.focus()

    # ── after a mutation ──────────────────────────────────────────────
    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        if fetched.ok:
            self.notify(ok_text, timeout=3)
            if self._detail_item is not None:
                self.load_detail(self._detail_item, force=True)
        else:
            self.notify(fetched.error or "failed", title="DC API", severity="error", timeout=6)

    @work(thread=True, group="mutate", exit_on_error=False)
    def mutate(self, command: str, *args: Any, ok_text: str = "done", **kwargs: Any) -> None:
        fetched = self.app.data.mutate(command, *args, **kwargs)  # type: ignore[attr-defined]
        self.app.call_from_thread(self.after_mutation, fetched, ok_text)
        self.app.call_from_thread(self.app.refresh_status)  # type: ignore[attr-defined]

    # ── hooks ─────────────────────────────────────────────────────────
    def fetch_rows(self, force: bool) -> List[dict]:
        return []

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        return (trunc(item.get("name", ""), 40),)

    def detail_title(self, item: dict) -> str:
        return esc(item.get("name") or "")

    def fetch_detail(self, item: dict, force: bool) -> Any:
        return None

    def render_detail(self, item: dict, data: Any) -> Any:
        return [esc(item)]

    def current_url(self) -> str:
        item = self.selected()
        if item:
            for key in ("shortURL", "roomURL", "eventURL", "profileURL", "chapterURL", "url"):
                if item.get(key):
                    return str(item[key])
        return self.URL


def items_of(fetched: Fetched) -> List[dict]:
    data = fetched.data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [i for i in data["items"] if isinstance(i, dict)]
    return [i for i in data if isinstance(i, dict)] if isinstance(data, list) else []


def dict_of(fetched: Any) -> dict:
    data = getattr(fetched, "data", fetched)
    return data if isinstance(data, dict) else {}
