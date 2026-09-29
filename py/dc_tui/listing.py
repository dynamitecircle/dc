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
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Static, Tab, Tabs

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
    AUTO_FOCUS = "#list"                  # arrows work the moment the screen opens
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
        Binding("up", "nav_up", "Up", show=False, priority=True),
        Binding("down", "nav_down", "Down", show=False, priority=True),
        Binding("f", "next_list_tab", "Filter", show=False),
        Binding("bracketright", "next_detail_tab", "Next tab", show=False),
        Binding("bracketleft", "prev_detail_tab", "Prev tab", show=False),
    ]

    DEFAULT_CSS = """
    ListDetailScreen DataTable { scrollbar-size: 0 0; }
    ListDetailScreen #list { height: auto; max-height: 100%; }
    ListDetailScreen #list-hint { color: $text-muted; height: auto; padding: 0 1; }
    ListDetailScreen Tabs { height: 2; margin: 0 0 0 0; }
    ListDetailScreen Tab.-active { color: $primary; text-style: bold; }
    ListDetailScreen Tabs:focus Tab.-active { background: $primary; color: #FFFFFF; text-style: bold; }
    ListDetailScreen Tabs .underline--bar { color: $primary; background: $panel; }
    ListDetailScreen Tabs:focus .underline--bar { color: #FFFFFF; }
    ListDetailScreen .detail-title { color: $primary; text-style: bold; height: auto; }
    ListDetailScreen .detail-actions { height: auto; margin: 0 0 1 0; }
    ListDetailScreen .detail-actions Button.action {
        height: 1; min-width: 0; border: none; padding: 0 1; margin: 0 1 0 0;
        background: $panel; color: $text; text-style: none;
    }
    ListDetailScreen .detail-actions Button.action:hover { background: $primary; color: #FFFFFF; }
    ListDetailScreen .detail-actions Button.action:focus { background: $primary; color: #FFFFFF; text-style: bold; }
    ListDetailScreen .detail-actions Button.action.back { background: $surface; color: $primary; }
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
                Horizontal(id="detail-actions-" + suffix, classes="detail-actions"),
                Static("", id="detail-body-" + suffix, classes="detail-body"),
                DataTable(id="detail-table-" + suffix, cursor_type="row", zebra_stripes=True, classes="detail-table")]

    # ── action buttons (mouse-first; Tab/Enter on the keyboard) ───────
    def detail_actions(self) -> Sequence[Tuple[str, str]]:
        """Override: [(label, action name)] shown as buttons above the detail."""
        return ()

    def _sync_actions(self) -> None:
        actions = list(self.detail_actions())
        if not self.two_pane:
            actions.insert(0, ("← Back", "close_detail"))      # nested view: always a visible way up
        self._action_map = {i: action for i, (_, action) in enumerate(actions)}
        labels = [label for label, _ in actions]
        for suffix in ("pane", "inline"):
            try:
                row = self.query_one("#detail-actions-" + suffix, Horizontal)
            except Exception:  # noqa: BLE001
                continue
            row.set_class(not actions, "-hidden")
            if [str(b.label) for b in row.query(Button)] != labels:
                # removal is asynchronous in Textual — rebuild in one exclusive worker per row
                self.run_worker(self._rebuild_actions(row, suffix, labels), group="actions-" + suffix, exclusive=True)

    async def _rebuild_actions(self, row: Horizontal, suffix: str, labels: List[str]) -> None:
        await row.remove_children()
        await row.mount(*[Button(label, id="act-%s-%d" % (suffix, i), classes="action back" if label.startswith("←") else "action")
                          for i, label in enumerate(labels)])

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = str(event.button.id or "")
        if bid.startswith("act-"):
            event.stop()
            action = getattr(self, "_action_map", {}).get(int(bid.rsplit("-", 1)[-1]))
            if action:
                await self.run_action(action)

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
        if self._detail_item is not None:
            self._sync_actions()
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

    def focus_content(self) -> None:
        self.query_one("#list", DataTable).focus()

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

    def select_key(self, key: str) -> None:
        """Open the row with this key (e.g. a roomID) — now, or as soon as rows load."""
        if not self.items:
            self._pending_key = key
            return
        table = self.query_one("#list", DataTable)
        for i, item in enumerate(self.items):
            if self.row_key(item, i) == key:
                table.move_cursor(row=i)
                self.action_open_detail()
                return

    def _rows_loaded(self, rows: List[dict], error: str) -> None:
        self.items = rows
        self._setup_columns()
        self._fill_table()
        pending = getattr(self, "_pending_key", None)
        if pending and rows:
            self._pending_key = None
            self.select_key(pending)
            return
        if self.focused is None or self.focused is self.main_pane():
            self.query_one("#list", DataTable).focus()     # first load only — never steal focus
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
            if key in self._keys:
                key = "%s#%d" % (key, i)
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
        self._sync_actions()
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
            self.call_after_refresh(self.focus_detail)
            return
        self._show_inline_detail(True)
        self.load_detail(item)
        self.call_after_refresh(self.focus_detail)

    def focus_detail(self) -> None:
        """Put the keyboard on the detail: its first action button, else its table."""
        suffix = "pane" if self.two_pane else "inline"
        try:
            buttons = list(self.query_one("#detail-actions-" + suffix, Horizontal).query(Button))
        except Exception:  # noqa: BLE001
            buttons = []
        if buttons:
            buttons[0].focus()
            return
        table = self.detail_table()
        if not table.has_class("-hidden") and table.row_count:
            table.focus()

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

    # ── arrows: tabs ⇅ tables ─────────────────────────────────────────
    def _tabs_for(self, table: DataTable) -> Optional[Tabs]:
        """The visible tab row that sits above a table, if any."""
        tid = "list-tabs" if table.id == "list" else "detail-tabs-" + str(table.id or "").rsplit("-", 1)[-1]
        try:
            tabs = self.query_one("#" + tid, Tabs)
        except Exception:  # noqa: BLE001
            return None
        return tabs if not tabs.has_class("-hidden") and tabs.tab_count else None

    def _table_for(self, tabs: Tabs):
        if tabs.id == "list-tabs":
            return self.query_one("#list", DataTable)
        suffix = str(tabs.id or "").rsplit("-", 1)[-1]
        actions = self.query_one("#detail-actions-" + suffix, Horizontal)
        buttons = list(actions.query(Button))
        if buttons and not actions.has_class("-hidden"):
            return buttons[0]
        table = self.query_one("#detail-table-" + suffix, DataTable)
        return table if (not table.has_class("-hidden") and table.row_count) else self.query_one("#list", DataTable)

    # PageUp/PageDown/Home/End go to the focused table (never wrap); otherwise the page
    def _table_key(self, table_action: str, page_step: int, **page_kw) -> None:
        focused = self.focused
        if isinstance(focused, DataTable) and focused.row_count:
            getattr(focused, table_action)()
            return
        self._page(page_step, **page_kw)

    def action_page_up_page(self) -> None:
        self._table_key("action_page_up", -1, page=True)

    def action_page_down_page(self) -> None:
        self._table_key("action_page_down", 1, page=True)

    def action_page_home(self) -> None:
        self._table_key("action_scroll_top", -1, edge=True)

    def action_page_end(self) -> None:
        self._table_key("action_scroll_bottom", 1, edge=True)

    def top_input(self) -> Optional[Input]:
        """A visible text field above the list (Search / People), if any."""
        for inp in self.query(Input):
            if not inp.has_class("-hidden") and inp.display:
                return inp
        return None

    def action_nav_up(self) -> None:
        """↑ : move in the table; from the top row, jump to the tab row above it,
        then the text field (if any), then the section bar."""
        focused = self.focused
        if isinstance(focused, Input):
            self.query_one("#nav-tabs", Tabs).focus()
            return
        if isinstance(focused, DataTable):
            if focused.cursor_row is not None and focused.cursor_row > 0 and focused.row_count:
                focused.action_cursor_up()
                return
            tabs = self._tabs_for(focused)
            if tabs is not None:
                tabs.focus()
            elif focused.id == "list":
                (self.top_input() or self.query_one("#nav-tabs", Tabs)).focus()
            return
        if isinstance(focused, Tabs):
            if focused.id == "list-tabs":
                (self.top_input() or self.query_one("#nav-tabs", Tabs)).focus()
            return
        if isinstance(focused, Button):
            tabs = None
            try:
                tabs = self.query_one("#detail-tabs-" + ("pane" if self.two_pane else "inline"), Tabs)
            except Exception:  # noqa: BLE001
                pass
            if tabs is not None and not tabs.has_class("-hidden"):
                tabs.focus()
            return
        self.query_one("#list", DataTable).focus()

    def action_nav_down(self) -> None:
        """↓ : from the section bar into the list tabs (or list); from a tab row
        into its table; otherwise move in the table."""
        focused = self.focused
        if isinstance(focused, Tabs) and focused.id == "nav-tabs":
            inp = self.top_input()
            if inp is not None:
                inp.focus()                  # bar → search field
                return
            focused = None                   # fall through to the list tabs / list
        if isinstance(focused, Input) or focused is None:
            try:
                tabs = self.query_one("#list-tabs", Tabs)
                if not tabs.has_class("-hidden"):
                    tabs.focus()
                    return
            except Exception:  # noqa: BLE001
                pass
            self.query_one("#list", DataTable).focus()
            return
        if isinstance(focused, Tabs):
            self._table_for(focused).focus()
            return
        if isinstance(focused, DataTable):
            focused.action_cursor_down()
            return
        self.query_one("#list", DataTable).focus()

    def _step_button(self, step: int) -> bool:
        focused = self.focused
        if not isinstance(focused, Button):
            return False
        buttons = list(focused.parent.query(Button)) if focused.parent is not None else []
        i = buttons.index(focused) if focused in buttons else -1
        if 0 <= i + step < len(buttons):
            buttons[i + step].focus()
        elif step > 0:
            table = self.detail_table()
            if not table.has_class("-hidden") and table.row_count:
                table.focus()
        elif self._detail_open:
            self.action_close_detail()
        else:
            self.query_one("#list", DataTable).focus()
        return True

    def action_pane_right(self) -> None:
        """→ : next tab when a tab row is focused; next button in an action row; else into the detail."""
        focused = self.focused
        if isinstance(focused, Tabs):
            focused.action_next_tab()
            return
        if self._step_button(1):
            return
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
        """← : previous tab when a tab row is focused; else back to the list."""
        focused = self.focused
        if isinstance(focused, Tabs):
            focused.action_previous_tab()
            return
        if self._step_button(-1):
            return
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

    def detail_focused(self) -> bool:
        """True when keyboard focus is inside the detail (its table or tab row),
        or the inline detail is open in one-pane mode."""
        focused = self.focused
        fid = str(getattr(focused, "id", "") or "")
        return self._detail_open or fid.startswith("detail-")

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
