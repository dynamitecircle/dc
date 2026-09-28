"""Shared widgets. `Panel` is the dashboard card every screen's overview uses."""
from __future__ import annotations

from typing import Iterable, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class Panel(Vertical):
    """A bordered, titled card whose body is a single Static we repaint.

    `set_lines(lines)` renders one row per line; Textual wraps long rows to
    the card width, so the same content works at 50 and 200 columns.
    """

    DEFAULT_CSS = """
    Panel { border: round $primary-darken-2; padding: 0 1; height: auto; min-height: 4; }
    Panel > .panel--body { height: auto; }
    Panel.-loading { border: round $warning; }
    Panel.-error   { border: round $error; }
    """

    def __init__(self, title: str, *, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self.border_title = title

    def compose(self) -> ComposeResult:
        yield Static("…", classes="panel--body")

    def set_lines(self, lines: Iterable[str], *, subtitle: str = "") -> None:
        rows = [ln for ln in lines if ln is not None]
        self.query_one(".panel--body", Static).update("\n".join(rows) if rows else "[dim]nothing here[/dim]")
        self.border_subtitle = subtitle
        self.remove_class("-loading", "-error")

    def set_loading(self) -> None:
        self.add_class("-loading")
        self.border_subtitle = "loading…"

    def set_error(self, message: str) -> None:
        self.remove_class("-loading")
        self.add_class("-error")
        self.query_one(".panel--body", Static).update("[red]%s[/red]" % str(message).replace("[", r"\["))
        self.border_subtitle = "error"
