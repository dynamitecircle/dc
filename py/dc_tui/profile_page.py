"""A DCer's profile as its own page: a header card, then one card per section of
the web profile (ProfileCore.vue order) — the same boxes as the Home screen.
Opened from anywhere a DCer appears (Following, Locator, Search, attendees…)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from textual import work
from textual.containers import Horizontal
from textual.widgets import Button

from .data import Fetched
from .format import fmt_date, guard_flags
from .listing import dict_of, esc
from .profile import SECTIONS, _val
from .screens import DCScreen, WEB_APP
from .widgets import Panel


def _profiles(f: Optional[Fetched]) -> List[dict]:
    data = dict_of(f) if f is not None else {}
    return [p for p in (data.get("profiles") or data.get("items") or []) if isinstance(p, dict)]


class ProfileScreen(DCScreen):
    SECTION = "profile"
    TITLE_TEXT = "Profile"
    HINT = ""
    URL = WEB_APP + "/members"
    HAS_DETAIL = False

    DEFAULT_CSS = """
    ProfileScreen #profile-actions { height: 1; margin: 0 0 1 0; }
    ProfileScreen #profile-actions Button { height: 1; min-width: 0; border: none; padding: 0 1; margin: 0 1 0 0;
                                            background: $panel; color: $text; text-style: none; }
    ProfileScreen #profile-actions Button.back { background: $surface; color: $primary; }
    ProfileScreen #profile-actions Button:hover, ProfileScreen #profile-actions Button:focus {
        background: $block-cursor-background; color: $block-cursor-foreground; border: none; }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._member: Dict[str, Any] = {}
        self._profile: Dict[str, Any] = {}
        self._following: Optional[bool] = None

    # ── entry point ──────────────────────────────────────────────────
    def show(self, member: dict) -> None:
        self._member = dict(member or {})
        self._profile = dict(self._member)
        self._following = None
        self.sub_title = self._member.get("displayName") or "Profile"
        self._render_all()
        self._load(False)

    def populate(self) -> None:
        self.set_main(Horizontal(Button("← Back", id="profile-back", classes="back"),
                                 Button("Follow", id="profile-follow"),
                                 Button("Open in app", id="profile-open"), id="profile-actions"),
                      Panel("Profile", id="pf-head"),
                      *[Panel(title, id="pf-%d" % i) for i, (title, _) in enumerate(SECTIONS)])
        if self._member:
            self.call_after_refresh(self._render_all)    # the cards' lists mount on the next refresh

    def refresh_data(self, force: bool = False) -> None:
        if self._member:
            self._load(force)

    @work(thread=True, exclusive=True, group="profile", exit_on_error=False)
    def _load(self, force: bool) -> None:
        data = self.app.data  # type: ignore[attr-defined]
        user_id = self._member.get("userID")
        full = data.fetch("dcer", user_id, force=force) if user_id and hasattr(data.dc, "dcer") else None
        follows = data.fetch("follows-profiles", force=force)
        self.app.call_from_thread(self._loaded, user_id, full, follows)

    def _loaded(self, user_id: Any, full: Optional[Fetched], follows: Fetched) -> None:
        if user_id != self._member.get("userID"):
            return                                  # another profile was opened meanwhile
        if full is not None and full.ok:
            body = dict_of(full)
            self._profile.update(body.get("profile") if isinstance(body.get("profile"), dict) else body)
        self._following = any(str(p.get("userID")) == str(user_id) for p in _profiles(follows))
        self._render_all(error=full.error if full is not None and not full.ok else "")

    # ── rendering ────────────────────────────────────────────────────
    def _render_all(self, error: str = "") -> None:
        p = self._profile
        try:
            head = self.query_one("#pf-head", Panel)
            head.list                              # noqa: B018 — raises until the card's list is mounted
        except Exception:  # noqa: BLE001 — not composed yet; populate renders again
            return
        name = p.get("displayName") or p.get("userName") or "DCer"
        nick = (" “%s”" % p.get("nickname")) if p.get("nickname") and p.get("nickname") != name else ""
        lines = ["[b]%s[/b]%s  [dim]@%s[/dim]" % (esc(name), esc(nick), esc(p.get("userName") or ""))]
        if p.get("headline"):
            lines.append(esc(_val(p.get("headline"))))
        if p.get("joinedDate"):
            lines.append("[dim]Joined DC %s[/dim]" % fmt_date(p.get("joinedDate")))
        if self._following is not None:
            lines.append("[dim]%s[/dim]" % ("★ you follow this DCer" if self._following else "not following"))
        if error:
            lines.append("[$warning]%s[/]" % esc(error))
        head.border_title = "👤 " + esc(name)
        head.set_lines(lines)
        for i, (title, fields) in enumerate(SECTIONS):
            try:
                panel = self.query_one("#pf-%d" % i, Panel)
            except Exception:  # noqa: BLE001
                continue
            rows = [(label, _val(p.get(key))) for label, key in fields]
            rows = [(label, value) for label, value in rows if value]
            panel.display = bool(rows)
            panel.set_lines([guard_flags("[dim]%s[/dim]  %s" % (label, esc(value))) for label, value in rows])
        try:
            self.query_one("#profile-follow", Button).label = "Unfollow" if self._following else "Follow"
        except Exception:  # noqa: BLE001
            pass

    # ── actions ──────────────────────────────────────────────────────
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "profile-back":
            self.app.action_back()  # type: ignore[attr-defined]
        elif bid == "profile-open":
            self.app.action_open_in_browser()  # type: ignore[attr-defined]
        elif bid == "profile-follow":
            self._toggle_follow()

    @work(thread=True, exclusive=True, group="profile-follow", exit_on_error=False)
    def _toggle_follow(self) -> None:
        user_id = self._member.get("userID")
        command = "unfollow-profile" if self._following else "follow-profile"
        done = self.app.data.mutate(command, user_id)  # type: ignore[attr-defined]
        self.app.call_from_thread(self._followed, done, command)

    def _followed(self, done: Fetched, command: str) -> None:
        if done.error:
            self.notify(done.error, severity="warning", timeout=5)
            return
        self._following = command == "follow-profile"
        self.notify("Following %s" % self._profile.get("displayName") if self._following else "Unfollowed", timeout=3)
        self._render_all()

    def current_url(self) -> str:
        user = self._profile.get("userName")
        return self._profile.get("profileURL") or ("%s/profile/%s" % (WEB_APP, user) if user else self.URL)
