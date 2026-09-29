"""Shared widgets. `Panel` is the card every overview screen is built from:
an orange title on a subtle frame, a muted subtitle, and a body that is a
keyboard-navigable list — every row can carry a target the screen opens."""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import OptionList
from textual.widgets.option_list import Option


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
    Panel > OptionList > .option-list--option-highlighted { background: $primary; color: #FFFFFF; text-style: bold; }
    Panel > OptionList:focus > .option-list--option-highlighted { background: $primary; color: #FFFFFF; text-style: bold; }
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
        yield OptionList()

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
