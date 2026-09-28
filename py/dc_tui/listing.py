"""`ListDetailScreen` — the base for every section that is "a list of things
plus one selected thing": Rooms, Trips, Events, People.

Layout follows the app's mode: in `split`/`wide` the list sits left and the
selected item's detail right; in `compact`/`single` there is only the list,
and Enter / → swaps the pane to the detail (Esc / ← comes back).

Optional tab rows: `LIST_TABS` above the list (e.g. Global · Local · Live
Calls) and `detail_tabs()` above the detail (e.g. Info · Schedule · Agenda).
`f` cycles list tabs, `[` / `]` cycle detail tabs, and the mouse works too.

Columns are sized to the pane: every column but the first gets the fixed
width in `COLUMN_WIDTHS`, the first column takes what is left, and cells are
truncated to fit — so there is never a horizontal scrollbar.

Concrete screens implement:
  fetch_rows(force)            -> List[dict]           (worker thread)
  row_cells(item)              -> tuple of cell strings, matching _columns()
  fetch_detail(item, force)    -> Any                  (worker thread; may read self.detail_tab)
  render_detail(item, data)    -> List[str] | Table    (UI thread)
and add their own BINDINGS for actions on `self.selected()`.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static, Tab, Tabs

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
    """A detail rendered as a DataTable (e.g. an event schedule)."""

    def __init__(self, columns: Sequence[str], rows: Sequence[Tuple[str, Sequence[str]]], *,
                 title: str = "", widths: Optional[Dict[str, int]] = None):
        self.columns = list(columns)
        self.rows = list(rows)          # (row key, cells)
        self.title = title
        self.widths = dict(widths or {})


class ListDetailScreen(DCScreen):
    COLUMNS: Sequence[str] = ()
    COLUMNS_COMPACT: Sequence[str] = ()   # subset used under 100 cols; empty = same as COLUMNS
    COLUMN_WIDTHS: Dict[str, int] = {}    # fixed widths; the first column is flexible
    LIST_TABS: Sequence[Tuple[str, str]] = ()
    EMPTY_TEXT = "nothing here yet"
    DETAIL_DEBOUNCE = 0.45

    BINDINGS = [
        Binding("enter", "open_detail", "Detail", show=False),
        Binding("escape", "close_detail", "Back", show=False),
        Binding("tab", "focus_next_pane", "Next pane", show=False),
        Binding("right", "pane_right", "Detail", show=False, priority=True),
        Binding("left", "pane_left", "List", show=False, priority=True),
        Binding("f", "next_list_tab", "Filter", show=False),
        Binding("bracketright", "next_detail_tab", "Next tab", show=False),
        Binding("bracketleft", "prev_detail_tab", "Prev tab", show=False),
    ]

    DEFAULT_CSS = """
    ListDetailScreen DataTable { scrollbar-size: 0 0; }
    ListDetailScreen #list { height: auto; max-height: 100%; }
    ListDetailScreen #list-hint { color: $text-muted; height: auto; padding: 0 1; }
    ListDetailScreen Tabs { height: 2; margin: 0 0 0 0; }
    ListDetailScreen .detail-title { color: $primary; text-style: bold; height: auto; }
    ListDetailScreen .detail-body { height: auto; }
    ListDetailScreen .detail-table { height: auto; max-height: 100%; }
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
        self.list_tab: str = self.LIST_TABS[0][0] if self.LIST_TABS else ""
        self.detail_tab: str = ""
        self.flex_width = 30
        self._syncing_tabs = False

    # ── build ─────────────────────────────────────────────────────────
    def populate(self) -> None:
        # The scroll panes must NOT take focus: the list table owns the arrow keys.
        self.main_pane().can_focus = False
        self.detail_pane().can_focus = False
        widgets: List[Any] = []
        if self.LIST_TABS:
            widgets.append(Tabs(*[Tab(label, id=tid) for tid, label in self.LIST_TABS], id="list-tabs"))
        widgets += [Static("", id="list-hint"), DataTable(id="list", cursor_type="row", zebra_stripes=True),
                    Vertical(*self._detail_widgets_for("inline"), id="detail-inline", classes="-hidden")]
        self.set_main(*widgets)
        self.detail_pane().mount(*self._detail_widgets_for("pane"))
        self._setup_columns()
        self.set_hint(self.HINT)
        self.refresh_data(force=False)

    def _detail_widgets_for(self, suffix: str) -> List[Any]:
        return [Tabs(id="detail-tabs-" + suffix, classes="-hidden"),
                Static("", id="detail-title-" + suffix, classes="detail-title"),
                Static("", id="detail-body-" + suffix, classes="detail-body"),
                DataTable(id="detail-table-" + suffix, cursor_type="row", zebra_stripes=True, classes="detail-table")]

    def _setup_columns(self) -> None:
        table = self.query_one("#list", DataTable)
        table.clear(columns=True)
        cols = list(self._columns())
        avail = max(30, (self.main_pane().size.width or self.app.size.width) - 2)
        fixed = sum(self.COLUMN_WIDTHS.get(c, 10) for c in cols[1:])
        self.flex_width = max(12, avail - fixed - 2 * len(cols))
        for i, col in enumerate(cols):
            width = self.flex_width if i == 0 else self.COLUMN_WIDTHS.get(col, 10)
            table.add_column(col, key=col, width=width)

    def _columns(self) -> Sequence[str]:
        compact = self.app.layout_mode_name in ("compact", "single")  # type: ignore[attr-defined]
        return self.COLUMNS_COMPACT if (compact and self.COLUMNS_COMPACT) else self.COLUMNS

    def set_layout_mode(self, mode: str) -> None:
        super().set_layout_mode(mode)
        if not self.is_mounted or not self.items:
            return
        self._setup_columns()
        self._fill_table()
        if self.two_pane and self._detail_open:
            self._show_inline_detail(False)
        self._paint_detail()

    def on_resize(self, event) -> None:
        super().on_resize(event)
        if self.is_mounted and self.items:
            self._setup_columns()
            self._fill_table()

    @property
    def two_pane(self) -> bool:
        return bool(self.HAS_DETAIL and self.app.layout_mode_name in ("split", "wide"))  # type: ignore[attr-defined]

    def set_hint(self, text: str) -> None:
        try:
            self.query_one("#list-hint", Static).update(text)
        except Exception:  # noqa: BLE001
            pass

    # ── tabs ──────────────────────────────────────────────────────────
    def detail_tabs(self) -> Sequence[Tuple[str, str]]:
        """Override to offer tabs above the detail (may depend on list_tab / item)."""
        return ()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        if self._syncing_tabs or event.tab is None:
            return
        tid = str(event.tab.id or "")
        if event.tabs.id == "list-tabs":
            if tid != self.list_tab:
                self.list_tab = tid
                self._detail_item = None
                self._setup_columns()
                self.refresh_data(force=False)
        elif str(event.tabs.id or "").startswith("detail-tabs-"):
            if tid != self.detail_tab:
                self.detail_tab = tid
                self._sync_detail_tabs()
                if self._detail_item is not None:
                    self.load_detail(self._detail_item)

    def _sync_detail_tabs(self) -> None:
        """Both copies of the detail tab row (pane + inline) show the same tabs/active."""
        tabs = list(self.detail_tabs())
        ids = [tid for tid, _ in tabs]
        if tabs and self.detail_tab not in ids:
            self.detail_tab = ids[0]
        self._syncing_tabs = True
        try:
            for suffix in ("pane", "inline"):
                widget = self.query_one("#detail-tabs-" + suffix, Tabs)
                current = [str(t.id) for t in widget.query(Tab)]
                if current != ids:
                    widget.clear()
                    for tid, label in tabs:
                        widget.add_tab(Tab(label, id=tid))
                widget.set_class(not tabs, "-hidden")
                if tabs and widget.active != self.detail_tab:
                    widget.active = self.detail_tab
        except Exception:  # noqa: BLE001 — not composed yet
            pass
        finally:
            self._syncing_tabs = False

    def action_next_list_tab(self) -> None:
        if not self.LIST_TABS:
            return
        ids = [tid for tid, _ in self.LIST_TABS]
        nxt = ids[(ids.index(self.list_tab) + 1) % len(ids)] if self.list_tab in ids else ids[0]
        self.query_one("#list-tabs", Tabs).active = nxt     # fires TabActivated → refresh

    def _cycle_detail_tab(self, step: int) -> None:
        ids = [tid for tid, _ in self.detail_tabs()]
        if not ids:
            return
        i = ids.index(self.detail_tab) if self.detail_tab in ids else 0
        self.detail_tab = ids[(i + step) % len(ids)]
        self._sync_detail_tabs()
        if self._detail_item is not None:
            self.load_detail(self._detail_item)

    def action_next_detail_tab(self) -> None:
        self._cycle_detail_tab(1)

    def action_prev_detail_tab(self) -> None:
        self._cycle_detail_tab(-1)

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
        self._setup_columns()
        self._fill_table()
        lst = self.query_one("#list", DataTable)
        if not isinstance(self.focused, Input) and not self._detail_open:
            lst.focus()
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
        cols = list(self._columns())
        for i, item in enumerate(self.items):
            key = self.row_key(item, i)
            self._keys[key] = item
            cells = list(self.row_cells(item))
            fitted = []
            for j, cell in enumerate(cells):
                width = self.flex_width if j == 0 else self.COLUMN_WIDTHS.get(cols[j] if j < len(cols) else "", 10)
                fitted.append(_fit(cell, width))
            table.add_row(*fitted, key=key)

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
        self._sync_detail_tabs()
        self._set_detail_title(self.detail_title(item) + "  [dim]loading…[/dim]")
        self._load_detail(item, force, self.detail_tab)

    @work(thread=True, exclusive=True, group="detail", exit_on_error=False)
    def _load_detail(self, item: dict, force: bool, tab: str) -> None:
        try:
            data = self.fetch_detail(item, force)
        except Exception as exc:  # noqa: BLE001
            data = Fetched("detail", None, from_cache=False, stale=False, age=0.0, error=str(exc), fetched_at=0.0)
        self.app.call_from_thread(self._detail_loaded, item, data, tab)
        self.app.call_from_thread(self.app.refresh_status)  # type: ignore[attr-defined]

    def _detail_loaded(self, item: dict, data: Any, tab: str) -> None:
        if item is not self._detail_item or tab != self.detail_tab:
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
            body.set_class(not rendered.title, "-hidden")
            table.remove_class("-hidden")
            table.clear(columns=True)
            avail = max(30, (self.detail_pane().size.width if self.two_pane else self.main_pane().size.width) - 2)
            fixed = sum(rendered.widths.get(c, 10) for c in rendered.columns[1:])
            flex = max(12, avail - fixed - 2 * len(rendered.columns))
            for i, col in enumerate(rendered.columns):
                table.add_column(col, key=col, width=flex if i == 0 else rendered.widths.get(col, 10))
            for key, cells in rendered.rows:
                fitted = [_fit(c, flex if i == 0 else rendered.widths.get(rendered.columns[i], 10))
                          if i < len(rendered.columns) else _fit(c, 10) for i, c in enumerate(cells)]
                table.add_row(*fitted, key=key)
        else:
            table.add_class("-hidden")
            body.remove_class("-hidden")
            body.update("\n".join(rendered) if rendered else "[dim]nothing to show[/dim]")

    def _detail_widgets(self) -> Tuple[Static, DataTable]:
        suffix = "pane" if self.two_pane else "inline"
        return (self.query_one("#detail-body-" + suffix, Static), self.query_one("#detail-table-" + suffix, DataTable))

    def _set_detail_title(self, text: str) -> None:
        for suffix in ("pane", "inline"):
            try:
                self.query_one("#detail-title-" + suffix, Static).update(text)
            except Exception:  # noqa: BLE001
                pass

    def detail_table(self) -> DataTable:
        return self.query_one("#detail-table-" + ("pane" if self.two_pane else "inline"), DataTable)

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
        try:
            self.query_one("#list-tabs", Tabs).set_class(show, "-hidden")
        except Exception:  # noqa: BLE001
            pass
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
            return
        if isinstance(self.focused, Input):
            self.focused.add_class("-hidden")
            self.query_one("#list", DataTable).focus()
            return
        self.app.action_back()  # type: ignore[attr-defined]

    def action_pane_right(self) -> None:
        """→ : into the detail (open it in one-pane mode, focus its table when it has rows)."""
        focused = self.focused
        if isinstance(focused, Input):
            focused.action_cursor_right()
            return
        if not self.two_pane and not self._detail_open:
            self.action_open_detail()
            return
        table = self.detail_table()
        if not table.has_class("-hidden") and table.row_count:
            table.focus()

    def action_pane_left(self) -> None:
        """← : back to the list (close the inline detail in one-pane mode)."""
        focused = self.focused
        if isinstance(focused, Input):
            focused.action_cursor_left()
            return
        if self._detail_open:
            self.action_close_detail()
            return
        self.query_one("#list", DataTable).focus()

    def action_focus_next_pane(self) -> None:
        table = self.detail_table()
        lst = self.query_one("#list", DataTable)
        if table.has_class("-hidden") or not table.row_count:
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
        return (str(item.get("name", "")),)

    def detail_title(self, item: dict) -> str:
        return esc(item.get("name") or "")

    def fetch_detail(self, item: dict, force: bool) -> Any:
        return None

    def render_detail(self, item: dict, data: Any) -> Any:
        return [esc(item)]

    def current_url(self) -> str:
        item = self.selected()
        if item:
            for key in ("shortURL", "roomURL", "eventURL", "profileURL", "chapterURL", "meetUrl", "url"):
                if item.get(key):
                    return str(item[key])
        return self.URL


def _fit(cell: Any, width: int) -> Any:
    """A table cell truncated to its column. Rich `Text` passes through styled
    (truncated in place); plain strings are escaped so data never renders as markup."""
    if isinstance(cell, Text):
        cell.truncate(max(1, width), overflow="ellipsis")
        return cell
    return esc(trunc(cell, width))


def items_of(fetched: Fetched) -> List[dict]:
    data = fetched.data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [i for i in data["items"] if isinstance(i, dict)]
    return [i for i in data if isinstance(i, dict)] if isinstance(data, list) else []


def dict_of(fetched: Any) -> dict:
    data = getattr(fetched, "data", fetched)
    return data if isinstance(data, dict) else {}
