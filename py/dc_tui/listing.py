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
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Input, Static, Tab, Tabs

from .data import Fetched
from .format import display_width, trunc
from .widgets import HoverTable
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
    LIST_FILTERS: Sequence[Tuple[str, str]] = ()   # chips under the tabs (e.g. All / Unread)
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
    ListDetailScreen #list-hint { color: $text-muted; height: auto; padding: 0 1; margin-bottom: 1; }  /* a blank line before the table */
    ListDetailScreen Tabs { height: 2; margin: 0 0 0 0; }
    ListDetailScreen #list-tabs { margin-bottom: 1; }             /* blank line: tabs → content */
    ListDetailScreen.has-filters #list-tabs { margin-bottom: 0; }  /* …unless the filter tabs follow */
    ListDetailScreen #list-filters { margin-bottom: 1; }
    ListDetailScreen Tab.-active { color: $primary; text-style: bold; background: transparent; }
    ListDetailScreen Tabs:focus Tab.-active { color: #FFB000; background: transparent; text-style: bold; }
    ListDetailScreen Tabs .underline--bar { color: $primary; background: $panel; }
    ListDetailScreen Tabs:focus .underline--bar { color: $primary; }
    ListDetailScreen .detail-title { color: $primary; text-style: bold; height: auto; padding: 0 1; }  /* text in column 2, like the tabs */
    ListDetailScreen .detail-actions { height: auto; margin: 0 0 1 0; }
    ListDetailScreen .detail-actions .action-row { height: 1; }
    ListDetailScreen .detail-actions Button.action {
        height: 1; min-width: 0; border: none; padding: 0 1; margin: 0 1 0 0;
        background: $panel; color: $text; text-style: none;
    }
    ListDetailScreen .detail-actions Button.action:hover { background: $block-cursor-background; color: $block-cursor-foreground; border: none; }
    ListDetailScreen .detail-actions Button.action.-active { border: none; tint: transparent; }
    ListDetailScreen .detail-actions Button.action:focus { background: $block-cursor-background; color: $block-cursor-foreground; text-style: bold; border: none; }
    ListDetailScreen .detail-actions Button.action.back { background: $surface; color: $primary; }
    ListDetailScreen #list-filters { height: 2; }
    ListDetailScreen Button.chip { height: 1; min-width: 0; border: none; padding: 0; margin: 0 1 0 0;  /* Button line-pad (1) is the only inset: label starts in column 2 */
                                   background: transparent; color: $text-muted; text-style: none; }
    ListDetailScreen Button.chip:hover { background: transparent; color: #FF8C5C; border: none; }
    ListDetailScreen Button.chip.-active { background: transparent; border: none; tint: transparent; }
    ListDetailScreen Button.chip.-on { color: $primary; text-style: bold; }
    ListDetailScreen Button.chip:focus { background: transparent; color: #FFB000; text-style: bold; border: none; }
    ListDetailScreen .detail-body { height: auto; padding: 0 1; }
    ListDetailScreen .detail-scroll { height: 1fr; }
    ListDetailScreen .detail-scroll.-hidden { display: none; }
    ListDetailScreen .detail-scroll.-fit { height: auto; }
    ListDetailScreen #detail-inline { height: 1fr; }
    ListDetailScreen .detail-table { height: 1fr; }
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
        self.list_filter: str = self.LIST_FILTERS[0][0] if self.LIST_FILTERS else ""
        self.detail_tab: str = ""
        self.flex_width = 30
        self._syncing_tabs = False

    # ── build ─────────────────────────────────────────────────────────
    def populate(self) -> None:
        # The scroll panes must NOT take focus: the list table owns the arrow keys.
        self.main_pane().can_focus = False
        self.detail_pane().can_focus = False
        widgets: List[Any] = []
        # a tab row right under the bars: no blank line between tab rows
        self.set_class(bool(self.LIST_TABS) and not self.TOP_INPUT, "tabs-first")
        self.set_class(bool(self.LIST_FILTERS), "has-filters")
        if self.LIST_TABS:
            widgets.append(Tabs(*[Tab(label, id=tid) for tid, label in self.LIST_TABS], id="list-tabs"))
        if self.LIST_FILTERS:
            # the filters are a tab row of their own, right under the type tabs
            widgets.append(Tabs(*[Tab(label, id="chip-" + fid) for fid, label in self.LIST_FILTERS],
                                id="list-filters", active="chip-" + self.list_filter))
        widgets += [Static("", id="list-hint"), HoverTable(id="list", cursor_type="row", zebra_stripes=True),
                    Vertical(*self._detail_widgets_for("inline"), id="detail-inline", classes="-hidden")]
        self.set_main(*widgets)
        self.detail_pane().mount(*self._detail_widgets_for("pane"))
        self._setup_columns()
        self.set_hint(self.HINT)
        self.refresh_data(force=False)

    def _detail_widgets_for(self, suffix: str) -> List[Any]:
        return [Tabs(id="detail-tabs-" + suffix, classes="-hidden"),
                Static("", id="detail-title-" + suffix, classes="detail-title"),
                Vertical(id="detail-actions-" + suffix, classes="detail-actions"),
                # only the text scrolls: tabs, title and buttons stay put above it
                VerticalScroll(Static("", id="detail-body-" + suffix, classes="detail-body"),
                               id="detail-scroll-" + suffix, classes="detail-scroll"),
                HoverTable(id="detail-table-" + suffix, cursor_type="row", zebra_stripes=True, classes="detail-table")]

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
        rows = _wrap_buttons(labels, self.detail_width())
        keys = getattr(self, "_actions_key", {})
        self._actions_key = keys
        for suffix in ("pane", "inline"):
            try:
                box = self.query_one("#detail-actions-" + suffix, Vertical)
            except Exception:  # noqa: BLE001
                continue
            box.set_class(not actions, "-hidden")
            key = (tuple(labels), tuple(tuple(r) for r in rows))
            if keys.get(suffix) != key:
                keys[suffix] = key
                # removal is asynchronous in Textual — rebuild in one exclusive worker per box
                self.run_worker(self._rebuild_actions(box, suffix, labels, rows), group="actions-" + suffix, exclusive=True)

    async def _rebuild_actions(self, box: Vertical, suffix: str, labels: List[str], rows: List[List[int]]) -> None:
        """Buttons wrap onto extra rows instead of running off the pane."""
        await box.remove_children()
        await box.mount(*[Horizontal(*[Button(labels[i], id="act-%s-%d" % (suffix, i),
                                              classes="action back" if labels[i].startswith("←") else "action")
                                       for i in row], classes="action-row") for row in rows])

    def set_filter(self, fid: str) -> None:
        if fid == self.list_filter:
            return
        self.list_filter = fid
        try:
            tabs = self.query_one("#list-filters", Tabs)
            if tabs.active != "chip-" + fid:
                tabs.active = "chip-" + fid
        except Exception:  # noqa: BLE001
            pass
        self._detail_item = None
        self.refresh_data(force=False)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = str(event.button.id or "")
        if bid.startswith("chip-"):
            event.stop()
            self.set_filter(bid[5:])
            return
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

    #: True for screens that mount a text field above the list tabs (Search, Profiles).
    TOP_INPUT = False

    #: Middle columns to give up first when the pane is too narrow (default: right to left).
    COLUMN_DROP: Sequence[str] = ()
    FIRST_COLUMN_MIN = 16

    def base_columns(self) -> Sequence[str]:
        """Override for columns that depend on a tab or mode."""
        compact = self.app.layout_mode_name in ("compact", "single")  # type: ignore[attr-defined]
        return self.COLUMNS_COMPACT if (compact and self.COLUMNS_COMPACT) else self.COLUMNS

    def _columns(self) -> Sequence[str]:
        """The layout's columns, minus middle ones that would not fit: the first
        (name) and last (date) columns always stay, so the date is never clipped."""
        cols = list(self.base_columns())
        try:
            avail = max(30, (self.main_pane().size.width or self.app.size.width) - 2)
        except Exception:  # noqa: BLE001 — not composed yet
            return cols
        drop = [c for c in (self.COLUMN_DROP or reversed(cols[1:-1])) if c in cols[1:-1]]
        need = lambda cs: sum(self.COLUMN_WIDTHS.get(c, 10) for c in cs[1:]) + self.FIRST_COLUMN_MIN + 2 * len(cs)
        while drop and need(cols) > avail:
            cols.remove(drop.pop(0))
        return cols

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
        if self.is_mounted and self._detail_item is not None:
            self.call_after_refresh(self._sync_actions)     # re-wrap buttons to the new width

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
        if event.tabs.id == "list-filters":
            self.set_filter(tid[5:] if tid.startswith("chip-") else tid)
            return
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
        self._rebuild_detail_tabs(tabs, ids)

    @work(exclusive=True, group="detail-tabs", exit_on_error=False)
    async def _rebuild_detail_tabs(self, tabs: List[Tuple[str, str]], ids: List[str]) -> None:
        """Replace the tab set only when it changed, awaiting the removal before
        adding: an un-awaited clear() racing add_tab() leaves orphaned Tab widgets
        that never start (and never answer a message)."""
        self._syncing_tabs = True
        try:
            for suffix in ("pane", "inline"):
                try:
                    widget = self.query_one("#detail-tabs-" + suffix, Tabs)
                except Exception:  # noqa: BLE001 — not composed yet
                    continue
                current = [str(t.id) for t in widget.query(Tab)]
                if current != ids:
                    await widget.clear()
                    for tid, label in tabs:
                        await widget.add_tab(Tab(label, id=tid))
                widget.set_class(not tabs, "-hidden")
                if tabs and widget.active != self.detail_tab:
                    widget.active = self.detail_tab
        finally:
            self.call_after_refresh(setattr, self, "_syncing_tabs", False)

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
        self._load_gen = getattr(self, "_load_gen", 0) + 1
        self._load_rows(force, self._load_gen)

    @work(thread=True, exclusive=True, group="rows", exit_on_error=False)
    def _load_rows(self, force: bool, gen: int = 0) -> None:
        try:
            rows = self.fetch_rows(force)
            error = ""
        except Exception as exc:  # noqa: BLE001
            rows, error = [], str(exc)
        self.app.call_from_thread(self._rows_arrived, gen, rows, error)
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
                table.focus()                     # the deep-linked row, not whatever was auto-selected first
                self._detail_item = item
                self.action_open_detail()
                return

    def _rows_arrived(self, gen: int, rows: List[dict], error: str) -> None:
        """A thread worker cannot be cancelled: a slow load for the previous tab or
        filter can land after a newer one started. Only the latest load paints."""
        if gen != getattr(self, "_load_gen", 0):
            return
        self._rows_loaded(rows, error)

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
            scroll = body.parent
            if scroll is not None:            # the table fills the space; the text area just fits its title
                scroll.set_class(True, "-fit")
                scroll.set_class(not rendered.title, "-hidden")
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
            if body.parent is not None:
                body.parent.remove_class("-fit", "-hidden")
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

    def detail_width(self) -> int:
        """Usable columns inside the detail (pane in split/wide, main pane inline)."""
        pane = self.detail_pane() if self.two_pane else self.main_pane()
        return max(30, (pane.size.width or self.app.size.width) - 4)     # pane inset + text inset

    def detail_scroller(self):
        """What scrolls in the detail: the text area (messages, info), else the pane."""
        try:
            area = self.query_one("#detail-scroll-" + ("pane" if self.two_pane else "inline"), VerticalScroll)
            if area.display and not area.has_class("-hidden"):
                return area
        except Exception:  # noqa: BLE001
            pass
        return self.detail_pane() if self.two_pane else self.main_pane()

    def _detail_scroll(self, step: int, *, page: bool = False, edge: bool = False) -> None:
        pane = self.detail_scroller()
        if edge:
            (pane.scroll_home if step < 0 else pane.scroll_end)(animate=False)
        elif page:
            (pane.scroll_page_up if step < 0 else pane.scroll_page_down)()
        else:
            (pane.scroll_up if step < 0 else pane.scroll_down)()

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
        for sel in ("#list-tabs", "#list-filters"):
            try:
                self.query_one(sel).set_class(show, "-hidden")
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
            buttons = list(self.query_one("#detail-actions-" + suffix, Vertical).query(Button))
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
        if tabs.id in ("list-tabs", "list-filters"):
            return self.query_one("#list", DataTable)
        suffix = str(tabs.id or "").rsplit("-", 1)[-1]
        actions = self.query_one("#detail-actions-" + suffix, Vertical)
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
        if isinstance(focused, Button) or self._detail_open:
            self._detail_scroll(page_step, **page_kw)
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

    def _chips(self) -> Optional[Tabs]:
        """The filter tab row, if this screen has one."""
        try:
            tabs = self.query_one("#list-filters", Tabs)
            return None if tabs.has_class("-hidden") else tabs
        except Exception:  # noqa: BLE001
            return None
        chips: List[Any] = []
        if not chips:
            return None
        for b in chips:
            if b.has_class("-on"):
                return b
        return chips[0]

    def top_input(self) -> Optional[Input]:
        """A visible text field above the list (Search / People), if any."""
        for inp in self.query(Input):
            if not inp.has_class("-hidden") and inp.display:
                return inp
        return None

    def _bar(self) -> Tabs:
        return self.sub_tabs() or self.query_one("#nav-tabs", Tabs)

    def action_nav_up(self) -> None:
        """↑ : move in the table; from the top row, jump to the tab row above it,
        then the text field (if any), then the section bar."""
        focused = self.focused
        if self.bar_step(focused, -1):
            return
        if isinstance(focused, Input):
            self.focus_bar()
            return
        if isinstance(focused, DataTable):
            if focused.cursor_row is not None and focused.cursor_row > 0 and focused.row_count:
                focused.action_cursor_up()
                return
            if focused.id == "list":
                chip = self._chips()
                if chip is not None:
                    chip.focus()
                    return
            tabs = self._tabs_for(focused)
            if tabs is not None:
                tabs.focus()
            elif focused.id == "list":
                (self.top_input() or self._bar()).focus()
            return
        if isinstance(focused, Tabs):
            if focused.id == "list-filters":
                try:
                    self.query_one("#list-tabs", Tabs).focus()
                except Exception:  # noqa: BLE001
                    (self.top_input() or self._bar()).focus()
            elif focused.id == "list-tabs":
                (self.top_input() or self._bar()).focus()
            return
        if isinstance(focused, Button) and focused.has_class("chip"):
            tabs = None
            try:
                tabs = self.query_one("#list-tabs", Tabs)
            except Exception:  # noqa: BLE001
                pass
            (tabs if tabs is not None and not tabs.has_class("-hidden") else (self.top_input() or self.query_one("#nav-tabs", Tabs))).focus()
            return
        if isinstance(focused, Button) and self._button_row_step(focused, -1):
            return
        if isinstance(focused, Button):
            tabs = None
            try:
                tabs = self.query_one("#detail-tabs-" + ("pane" if self.two_pane else "inline"), Tabs)
            except Exception:  # noqa: BLE001
                pass
            if tabs is not None and not tabs.has_class("-hidden"):
                tabs.focus()                     # … then up into the detail tabs
            return
        self.query_one("#list", DataTable).focus()

    def action_nav_down(self) -> None:
        """↓ : from the section bar into the list tabs (or list); from a tab row
        into its table; otherwise move in the table."""
        focused = self.focused
        if self.bar_step(focused, 1):
            return
        if isinstance(focused, Tabs) and focused.id in ("nav-tabs", "sub-tabs"):
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
            chip = self._chips() if focused.id == "list-tabs" else None
            (chip if chip is not None else self._table_for(focused)).focus()
            return
        if isinstance(focused, DataTable):
            focused.action_cursor_down()
            return
        if isinstance(focused, Button) and focused.has_class("chip"):
            self.query_one("#list", DataTable).focus()
            return
        if isinstance(focused, Button) and self._button_row_step(focused, 1):
            return
        if isinstance(focused, Button):
            table = self.detail_table()
            if not table.has_class("-hidden") and table.row_count:
                table.focus()
            else:
                self._detail_scroll(1)           # text detail (messages): scroll it
            return
        self.query_one("#list", DataTable).focus()

    def _button_row_step(self, button: Button, step: int) -> bool:
        """↑/↓ between wrapped action-button rows; False at the first/last row."""
        row = button.parent
        if row is None or not row.has_class("action-row") or row.parent is None:
            return False
        rows = [r for r in row.parent.children if r.has_class("action-row")]
        i = rows.index(row) + step
        if not 0 <= i < len(rows):
            return False
        col = list(row.query(Button)).index(button)
        target = list(rows[i].query(Button))
        if not target:
            return False
        target[min(col, len(target) - 1)].focus()
        return True

    def _step_button(self, step: int) -> bool:
        focused = self.focused
        if not isinstance(focused, Button):
            return False
        box = focused.parent
        if box is not None and box.has_class("action-row"):
            box = box.parent                 # ←/→ run across wrapped rows
        buttons = list(box.query(Button)) if box is not None else []
        i = buttons.index(focused) if focused in buttons else -1
        if focused.has_class("chip"):
            if 0 <= i + step < len(buttons):
                buttons[i + step].focus()
            return True
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
        """True when focus is inside the detail (its table, tab row or action
        buttons — a mouse click focuses the button), or the inline detail is
        open in one-pane mode."""
        focused = self.focused
        fid = str(getattr(focused, "id", "") or "")
        return self._detail_open or fid.startswith("detail-") or fid.startswith("act-")

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


def _wrap_buttons(labels: List[str], width: int) -> List[List[int]]:
    """Split button indexes into rows that fit `width` columns (label + padding 2 + margin 1)."""
    rows: List[List[int]] = [[]]
    used = 0
    for i, label in enumerate(labels):
        w = display_width(label) + 4       # padding 2 + margin 1 + Textual's own cell
        if rows[-1] and used + w > width:
            rows.append([])
            used = 0
        rows[-1].append(i)
        used += w
    return [r for r in rows if r]


_DATE_CELL = re.compile(                         # "05 Oct 2026", "22–25 Oct 2026", "30 Sep – 02 Oct 2026",
    r"^(?:\d{2}(?:–\d{2})? [A-Z][a-z]{2}(?: \d{4})?(?: – \d{2} [A-Z][a-z]{2})?(?: \d{4})?"   # "Jul 2027" (month only),
    r"|[A-Z][a-z]{2} \d{4})(?: \d{2}:\d{2})?$")                                         # optional " 15:00"


def _fit(cell: Any, width: int) -> Any:
    """A table cell truncated to its column. Rich `Text` passes through styled
    (truncated in place); plain strings are escaped so data never renders as
    markup; a date cell is right-justified so digits line up."""
    if isinstance(cell, Text):
        cell.truncate(max(1, width), overflow="ellipsis")
        return cell
    text = str(cell or "")
    if _DATE_CELL.match(text):
        return Text(text, justify="right")
    return esc(trunc(cell, width))


def items_of(fetched: Fetched) -> List[dict]:
    data = fetched.data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [i for i in data["items"] if isinstance(i, dict)]
    return [i for i in data if isinstance(i, dict)] if isinstance(data, list) else []


def dict_of(fetched: Any) -> dict:
    data = getattr(fetched, "data", fetched)
    return data if isinstance(data, dict) else {}
