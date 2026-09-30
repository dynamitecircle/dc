"""The Textual application shell — status bar, section switcher, help,
command palette, open-in-browser, refresh, and the paced background tick.

Only this module (and ``screens.py``) imports Textual. Everything the
offline test-suite covers lives in the stdlib-only siblings.
"""
from __future__ import annotations

import time
import webbrowser
from typing import Callable, List, Optional, Tuple

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from .data import DataClient, Fetched
from .layout import layout_mode
from .browse import BrowseScreen
from .events import EventsScreen
from .following import FollowingScreen, NewTripsScreen
from .locator import LocatorScreen
from .me import MeScreen
from .people import PeopleScreen
from .rooms import RoomsScreen
from .screens import NAV_SECTIONS, SECTIONS, DCScreen, HomeScreen, PlaceholderScreen, StatusBar
from .search import SearchScreen
from .trips import TripsScreen
from .theme import DC_THEME

WEB_APP = "https://dc.dynamitecircle.com"

SCREEN_CLASSES = {"home": HomeScreen, "rooms": RoomsScreen, "browse": BrowseScreen, "trips": TripsScreen, "events": EventsScreen,
                  "locator": LocatorScreen, "following": FollowingScreen, "newtrips": NewTripsScreen, "people": PeopleScreen, "search": SearchScreen, "me": MeScreen}

HELP_TEXT = """\
[b]DC terminal[/b]

Everything works with the mouse: click a section in the bar at the top, a tab,
a row, or a button. On the keyboard you only need:

  [b]↑ ↓[/b]     move through a list (from the top row, up into the tabs and the section bar)
  [b]← →[/b]     switch tabs · walk the buttons · go into the detail and back
  [b]Enter[/b]   open the selected item
  [b]Esc[/b]     back: close the detail, then the previous section, then Home
  [b]Tab[/b]     jump to the next pane
  [b]/[/b]       command list (search every action by name)
  [b]?[/b] help  ·  [b]q[/b] quit

Actions (read messages, bookmark a session, RSVP, follow, new trip…) are buttons
inside the detail of the thing they act on — never a key on a list.

Data is cached on disk and refreshed on a timer paced by your API budget (status
bar). Nothing is sent as a message from here — conversations happen in the web
app, one click away ("Open in app").
"""


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,question_mark,q", "close_help", "Close", show=False)]

    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    #help-box { width: 72; max-width: 100%; height: auto; max-height: 90%;
                border: round $primary; background: $surface; padding: 1 2; }
    #help-back { height: 1; min-width: 0; border: none; padding: 0 1; margin: 0 0 1 0; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Button("← Back", id="help-back", variant="primary")
            yield Static(HELP_TEXT, id="help-body")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def action_close_help(self) -> None:
        self.dismiss()


class DCCommands(Provider):
    """Command-palette provider backed by :meth:`DCApp.palette_commands`."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, help_text, callback in self.app.palette_commands():  # type: ignore[attr-defined]
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)

    async def discover(self) -> Hits:
        for name, help_text, callback in self.app.palette_commands():  # type: ignore[attr-defined]
            yield DiscoveryHit(name, callback, help=help_text)


class DCApp(App):
    TITLE = "DC"
    SUB_TITLE = "Dynamite Circle"
    COMMANDS = {DCCommands}
    SCREENS = {section.id: SCREEN_CLASSES.get(section.id) or PlaceholderScreen.for_section(section)
               for section in SECTIONS}

    BINDINGS = [Binding(str(i + 1), "goto_section('%s')" % section.id, section.title, show=False)
                for i, section in enumerate(NAV_SECTIONS)] + [
        Binding("up,down", "noop", "Move", show=True, key_display="↑↓"),
        Binding("left,right", "noop", "Panes", show=True, key_display="←→"),
        Binding("enter", "noop", "Open", show=True, key_display="Enter"),
        Binding("escape", "back", "Back", show=True, key_display="Esc"),
        Binding("backspace", "back", "Back", show=False),
        Binding("tab", "noop", "Next", show=True, key_display="Tab"),
        Binding("slash", "command_palette", "Commands", key_display="/"),
        Binding("r", "refresh_screen", "Refresh", show=False),
        Binding("o", "open_in_browser", "Open in app", show=False),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    Screen { layout: vertical; background: $background; }
    * { scrollbar-size: 0 0; }
    DataTable > .datatable--hover { background: #4D7D55; color: #FFFFFF; }
    OptionList > .option-list--option-hover { background: #4D7D55; color: #FFFFFF; }
    Button.action:hover { background: #FF8C5C; color: #FFFFFF; }
    /* Tabs: never a background. Inactive tabs light gray; the active tab is orange with the
       orange underline; gold (#FFB000) only on the tab under the keyboard cursor */
    Tabs { background: $background; }
    #nav-tabs { height: 2; background: $background; }
    /* every row's text starts in column 2: title, bars, list tabs, chips, hint, table */
    #nav-tabs #tabs-list-bar, #sub-tabs #tabs-list-bar { margin-left: 1; }
    Tab { color: #C4C7CE; background: transparent; }          /* inactive: light gray */
    Tab:hover { color: #FF8C5C; background: transparent; text-style: none; }
    Tab.-active { color: $primary; background: transparent; text-style: bold; }
    Tab.-active:hover { color: #FF8C5C; background: transparent; }
    Tabs:focus Tab.-active { color: #FFB000; background: transparent; text-style: bold; }
    Tabs .underline--bar { color: $primary; background: $panel; }
    Tabs:focus .underline--bar { color: $primary; }
    Footer { background: $background; }
    #body { height: 1fr; }
    #main { width: 1fr; height: 1fr; padding: 1 1 0 1; }
    Screen.compact #main { padding: 0; }
    #detail { width: 45%; height: 1fr; border-left: solid $panel-lighten-2; padding: 0 1; }
    Screen.wide #detail { width: 55%; }
    StatusBar { height: 1; background: $background; color: $text-muted; padding: 0 1; }
    .section-title { text-style: bold; color: $primary; }
    .muted { color: $text-muted; }
    .warn { color: $warning; }
    """

    def __init__(self, dc, argv: Optional[List[str]] = None, data: Optional[DataClient] = None):
        super().__init__()
        self.dc = dc
        self.data = data if data is not None else DataClient(dc)
        self.argv = list(argv or [])
        self.layout_mode_name = "compact"
        self.last_refresh_at: Optional[float] = None
        self.unread: Optional[Fetched] = None
        self._last_key_at = time.time()
        self._tick_timer = None
        self._history: List[str] = []       # section ids, for Esc/Backspace
        self._focus_nav_next = False        # set when a section was chosen on the bar

    # ── Lifecycle ─────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.register_theme(DC_THEME)
        self.theme = "dc"
        start = self.argv[0] if self.argv and self.argv[0] in self.SCREENS else "home"
        self.push_screen(start)
        self.bootstrap()

    def on_key(self, event: events.Key) -> None:
        self._last_key_at = time.time()

    @property
    def idle_seconds(self) -> float:
        return max(0.0, time.time() - self._last_key_at)

    # ── Sections ──────────────────────────────────────────────────────

    def action_goto_section(self, section_id: str) -> None:
        if section_id not in self.SCREENS:
            return
        if isinstance(self.screen, ModalScreen):
            self.pop_screen()
        current = getattr(self.screen, "SECTION", None)
        if current == section_id:
            return
        if current and (not self._history or self._history[-1] != current):
            self._history.append(current)
            del self._history[:-20]
        self.switch_screen(section_id)

    def open_in_section(self, section_id: str, key: Optional[str] = None) -> None:
        """Jump to a section and open one of its rows (Home cards deep-link here)."""
        self.action_goto_section(section_id)
        screen = self.screen
        if key and hasattr(screen, "select_key"):
            screen.select_key(key)  # type: ignore[attr-defined]

    def open_person(self, member: dict) -> None:
        """Show a DCer's profile in the People section (terminal first; the web
        profile is a button inside it)."""
        self.action_goto_section("people")
        screen = self.screen
        if hasattr(screen, "show_person"):
            screen.show_person(member)  # type: ignore[attr-defined]

    def action_back(self) -> None:
        """Esc / Backspace: close an open modal, else the previous section, else Home."""
        if isinstance(self.screen, ModalScreen):
            self.pop_screen()
            return
        current = getattr(self.screen, "SECTION", None)
        while self._history:
            target = self._history.pop()
            if target != current and target in self.SCREENS:
                self.switch_screen(target)
                return
        if current != "home":
            self.switch_screen("home")

    def action_noop(self) -> None:
        """Footer-only entries: the focused widget handles these keys itself."""

    def action_show_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen())

    def action_refresh_screen(self) -> None:
        screen = self.screen
        if isinstance(screen, DCScreen):
            screen.refresh_data(force=True)
        self.poll_unread(force=True)

    def action_open_in_browser(self) -> None:
        screen = self.screen
        url = screen.current_url() if isinstance(screen, DCScreen) else WEB_APP
        try:
            opened = webbrowser.open(url or WEB_APP)
        except Exception:  # noqa: BLE001
            opened = False
        if opened:
            self.notify("Opened in browser", title=url or WEB_APP, timeout=3)
        else:
            self.notify(url or WEB_APP, title="Couldn't launch a browser — open this URL",
                        severity="warning", timeout=8)

    def palette_commands(self) -> List[Tuple[str, str, Callable[[], None]]]:
        commands: List[Tuple[str, str, Callable[[], None]]] = []
        for section in SECTIONS:
            commands.append(("Go to %s" % section.title, section.hint,
                             (lambda sid=section.id: self.action_goto_section(sid))))
        commands.extend([
            ("Refresh", "Re-fetch this screen, bypassing the cache", self.action_refresh_screen),
            ("Open in browser", "Open the current item in the DC web app", self.action_open_in_browser),
            ("Help", "Keyboard reference", self.action_show_help),
            ("Quit", "Exit dc tui", self.action_quit),
        ])
        return commands

    # ── Status bar ────────────────────────────────────────────────────

    def status_text(self) -> str:
        parts = [self.data.budget.summary()]
        if self.last_refresh_at:
            parts.append("refreshed %s ago" % _ago(time.time() - self.last_refresh_at))
        unread = self.unread
        if unread is not None and unread.data is not None:
            count = _unread_count(unread.data)
            label = "%d unread" % count if count is not None else "inbox ok"
            if unread.stale:
                label += " (stale)"
            parts.append(label)
        elif unread is not None and unread.error:
            parts.append("inbox: %s" % unread.error)
        parts.append(self.layout_mode_name)
        return " · ".join(parts)

    def refresh_status(self) -> None:
        for bar in self.screen.query(StatusBar):
            bar.update(self.status_text())

    def apply_layout(self, width: int) -> None:
        self.layout_mode_name = layout_mode(width)
        screen = self.screen
        if isinstance(screen, DCScreen):
            screen.set_layout_mode(self.layout_mode_name)
        self.refresh_status()

    # ── Background work ───────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="bootstrap", exit_on_error=False)
    def bootstrap(self) -> None:
        """First contact: learn the rate budget, then the unread state."""
        limits = self.data.fetch("limits", force=True)
        self.call_from_thread(self._after_limits, limits)
        self._poll_unread_blocking(force=False)

    def _after_limits(self, fetched: Fetched) -> None:
        if fetched.error:
            self.notify(fetched.error, title="Couldn't read /limits", severity="warning", timeout=8)
        self.refresh_status()

    @work(thread=True, exclusive=True, group="tick", exit_on_error=False)
    def poll_unread(self, force: bool = False) -> None:
        self._poll_unread_blocking(force=force)

    def _poll_unread_blocking(self, force: bool) -> None:
        fetched = self.data.fetch("inbox", force=force, background=not force)
        self.call_from_thread(self._after_unread, fetched)

    def _after_unread(self, fetched: Fetched) -> None:
        self.unread = fetched
        if not fetched.from_cache and fetched.ok:
            self.last_refresh_at = fetched.fetched_at
        screen = self.screen
        if isinstance(screen, HomeScreen):
            screen.show_unread(fetched)
        self.refresh_status()
        self._schedule_tick()

    def _schedule_tick(self) -> None:
        if self._tick_timer is not None:
            self._tick_timer.stop()
        delay = self.data.budget.poll_interval(self.idle_seconds)
        self._tick_timer = self.set_timer(delay, self.poll_unread, name="unread-tick")


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm" % (seconds // 60)
    return "%dh" % (seconds // 3600)


def _unread_count(data) -> Optional[int]:
    """Best-effort unread total from the ``inbox`` envelope."""
    if not isinstance(data, dict):
        return None
    extra = data.get("extra") or {}
    for key in ("totalUnread", "unreadCount", "total"):
        value = extra.get(key) if isinstance(extra, dict) else None
        if isinstance(value, int):
            return value
    items = data.get("items")
    if isinstance(items, list):
        total = 0
        for item in items:
            if isinstance(item, dict):
                n = item.get("unreadCount", item.get("badgeCount"))
                total += n if isinstance(n, int) and n > 0 else 1
        return total
    count = data.get("count")
    return count if isinstance(count, int) else None
