"""Shared widgets. `Panel` is the card every overview screen is built from:
an orange title on a subtle frame, a muted subtitle, and a body that is a
keyboard-navigable list — every row can carry a target the screen opens."""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Input, OptionList
from textual.widgets.option_list import Option


def _focus_unless_typing(widget) -> None:
    """Pointing at a list takes the keyboard too — unless you are typing in a field."""
    focused = widget.screen.focused if widget.is_attached else None
    if not isinstance(focused, Input) and focused is not widget:
        widget.focus()


class HoverTable(DataTable):
    """A row table where the mouse and the keyboard share ONE highlight: pointing
    at a row moves the cursor there, so there is never a hover row and a cursor
    row coloured at the same time."""

    def watch_hover_coordinate(self, old, value) -> None:
        super().watch_hover_coordinate(old, value)
        if not self.is_mounted or value == old or not self.row_count:
            return
        if not getattr(self, "_mouse_inside", False):
            return                      # a programmatic reset (clear / refill), not the mouse
        if 0 <= value.row < self.row_count and value.row != self.cursor_row:
            self.move_cursor(row=value.row, animate=False)
        _focus_unless_typing(self)

    def on_enter(self, event) -> None:
        self._mouse_inside = True

    def on_leave(self, event) -> None:
        self._mouse_inside = False


class HoverOptionList(OptionList):
    """Same single-highlight rule for the card lists (Home, Locator, Me)."""

    def watch__mouse_hovering_over(self, value) -> None:
        if value is None or value == self.highlighted:
            return
        try:
            if self.get_option_at_index(value).disabled:
                return                  # headings are not rows you can pick
        except Exception:  # noqa: BLE001
            return
        self.highlighted = value
        _focus_unless_typing(self)


class Panel(Vertical):
    DEFAULT_CSS = """
    Panel {
        border: round $panel;
        border-title-color: $primary;
        border-title-style: bold;
        border-subtitle-color: $text-muted;
        padding: 0 1;
        margin: 0 0 1 0;
        height: auto;
        min-height: 3;
        background: $background;
    }
    Panel > OptionList {
        height: auto; border: none; padding: 0; background: $background; scrollbar-size: 0 0;
    }
    Panel > OptionList:focus { border: none; }
    Panel > OptionList > .option-list--option-highlighted { background: $block-cursor-background; color: $block-cursor-foreground; text-style: bold; }
    Panel > OptionList:focus > .option-list--option-highlighted { background: $block-cursor-background; color: $block-cursor-foreground; text-style: bold; }
    Panel > OptionList > .option-list--option-hover { background: transparent; }
    Panel > OptionList:blur > .option-list--option-highlighted { background: $background; color: $text; text-style: none; }
    Panel > OptionList > .option-list--option-disabled { color: $text-muted; }
    Panel.-loading { border-subtitle-color: $warning; }
    Panel.-error   { border: round $error; }
    """

    def __init__(self, title: str, *, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self.border_title = title
        self.targets: List[Any] = []

    def compose(self) -> ComposeResult:
        yield HoverOptionList()

    def row_width(self) -> int:
        """Columns a row can use once laid out (0 before layout) — measured, not
        estimated, so the last item (the date) lands one space from the border."""
        try:
            return int(self.list.content_region.width)
        except Exception:  # noqa: BLE001
            return 0

    @property
    def list(self) -> OptionList:
        return self.query_one(OptionList)

    def set_rows(self, rows: Sequence[Tuple[str, Any]], *, subtitle: str = "") -> None:
        """`rows` = [(markup line, target-or-None)]. Rows without a target are
        headings: shown dimmed and skipped by the arrows."""
        options: List[Option] = []
        self.targets = []
        for i, (line, target) in enumerate(rows):
            options.append(Option(line, id="r%d" % i, disabled=target is None))
            self.targets.append(target)
        lst = self.list
        keep = lst.highlighted
        lst.clear_options()
        if options:
            lst.add_options(options)
            if keep is not None and keep < len(options) and self.targets[keep] is not None:
                lst.highlighted = keep
        else:
            lst.add_option(Option("[dim]nothing here[/dim]", disabled=True))
        self.border_subtitle = subtitle
        self.remove_class("-loading", "-error")

    def set_lines(self, lines: Iterable[str], *, subtitle: str = "") -> None:
        self.set_rows([(ln, None) for ln in lines if ln is not None], subtitle=subtitle)

    def set_loading(self) -> None:
        self.add_class("-loading")
        if not self.border_subtitle:
            self.border_subtitle = "loading…"

    def set_error(self, message: str) -> None:
        self.remove_class("-loading")
        self.add_class("-error")
        self.set_rows([("[$error]%s[/]" % str(message).replace("[", r"\["), None)], subtitle="error")

    def target(self) -> Any:
        i = self.list.highlighted
        return self.targets[i] if i is not None and i < len(self.targets) else None

    def selectable(self) -> bool:
        return any(t is not None for t in self.targets)

    def first(self) -> None:
        for i, t in enumerate(self.targets):
            if t is not None:
                self.list.highlighted = i
                return

    def last(self) -> None:
        for i in range(len(self.targets) - 1, -1, -1):
            if self.targets[i] is not None:
                self.list.highlighted = i
                return

    def at_first(self) -> bool:
        i = self.list.highlighted
        return i is None or all(t is None for t in self.targets[:i])

    def at_last(self) -> bool:
        i = self.list.highlighted
        return i is None or all(t is None for t in self.targets[i + 1:])
