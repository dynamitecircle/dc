"""Me — your profile, membership and billing, notification preferences,
alerts, interests, calendar feed and locator digest toggles. Read-only in
this version; `o` opens the matching settings page in the app."""
from __future__ import annotations

from typing import Any, Dict, List

from textual import work
from textual.binding import Binding
from textual.widgets import Static

from .data import Fetched
from .format import flag, fmt_date, guard_flags, plural, trunc
from .profile import profile_lines
from .listing import dict_of, esc, items_of, plain
from .screens import DCScreen, WEB_APP
from .widgets import Panel

COMMANDS = ("profile", "membership", "notifications", "alerts", "interests", "calendar", "locator-settings")


class MeScreen(DCScreen):
    SECTION = "me"
    TITLE_TEXT = "Me"
    HINT = "r refresh · o open your profile in the app"
    URL = WEB_APP + "/profile"
    HAS_DETAIL = False

    DEFAULT_CSS = """
    MeScreen #me-hint { color: $text-muted; height: auto; padding: 0 1; }
    """

    def populate(self) -> None:
        self.set_main(Static(self.HINT, id="me-hint"),
                      Panel("Profile", id="me-profile"), Panel("Membership", id="me-membership"),
                      Panel("Notifications", id="me-notifications"), Panel("Alerts", id="me-alerts"),
                      Panel("Interests", id="me-interests"), Panel("Calendar feed", id="me-calendar"),
                      Panel("Friday locator email", id="me-locator"))
        self.refresh_data(force=False)

    def refresh_data(self, force: bool = False) -> None:
        for panel in self.query(Panel):
            panel.set_loading()
        self._load(force)

    @work(thread=True, exclusive=True, group="me", exit_on_error=False)
    def _load(self, force: bool) -> None:
        data = self.app.data  # type: ignore[attr-defined]
        results = {cmd: data.fetch(cmd, force=force) for cmd in COMMANDS}
        self.app.call_from_thread(self._render_all, results)
        self.app.call_from_thread(self.app.refresh_status)  # type: ignore[attr-defined]

    def _render_all(self, r: Dict[str, Fetched]) -> None:
        self._paint("me-profile", *self._profile(r["profile"]))
        self._paint("me-membership", *self._membership(r["membership"]))
        self._paint("me-notifications", *self._notifications(r["notifications"]))
        self._paint("me-alerts", *self._alerts(r["alerts"]))
        self._paint("me-interests", *self._interests(r["interests"]))
        self._paint("me-calendar", *self._calendar(r["calendar"]))
        self._paint("me-locator", *self._locator(r["locator-settings"]))

    def _paint(self, pid: str, lines: List[str], subtitle: str, fetched: Fetched = None) -> None:
        try:
            panel = self.query_one("#%s" % pid, Panel)
        except Exception:  # noqa: BLE001
            return
        panel.set_lines(lines, subtitle=subtitle)

    # ── renderers ─────────────────────────────────────────────────────
    @staticmethod
    def _flag(f: Fetched, base: str) -> str:
        if f.error:
            return "%s · ⚠ %s" % (base, trunc(f.error, 30))
        return base + (" · stale" if f.stale else "")

    def _profile(self, f: Fetched):
        p = dict_of(f)
        chapter = p.get("chapter") if isinstance(p.get("chapter"), dict) else {}
        lines = profile_lines(p, width=max(40, self.main_pane().size.width - 8))
        return lines, guard_flags(self._flag(f, esc(("%s %s" % (flag(chapter.get("countryCode")), chapter.get("cityName") or "")).strip())))

    def _membership(self, f: Fetched):
        m = dict_of(f).get("membership")
        m = m if isinstance(m, dict) else {}
        role = m.get("role") if isinstance(m.get("role"), dict) else {}
        billing = m.get("billing") if isinstance(m.get("billing"), dict) else {}
        dcb = m.get("dcBlack") if isinstance(m.get("dcBlack"), dict) else {}
        trial = m.get("trial") if isinstance(m.get("trial"), dict) else {}
        lines = ["[b]%s[/b]%s  [dim]since %s[/dim]" % (esc(role.get("label") or ""), "  · [b]DC BLACK[/b]" if dcb.get("isMember") else "",
                                                     fmt_date(m.get("joinedDate")))]
        if trial.get("isOnTrial"):
            lines.append("trial: %s days left" % trial.get("daysLeft"))
        if billing.get("planName") or billing.get("amountFormatted"):
            lines.append("%s %s [dim]%s[/dim]" % (esc(billing.get("planName") or ""), esc(billing.get("amountFormatted") or ""),
                                                  esc(billing.get("frequency") or billing.get("interval") or "")))
        if billing.get("nextBillingDate") or billing.get("currentPeriodEnd"):
            lines.append("[dim]renews %s (%s)[/dim]" % (fmt_date(billing.get("nextBillingDate") or billing.get("currentPeriodEnd")),
                                                     plural(int(billing.get("daysTillRenewal") or 0), "day")))
        status = billing.get("status") or ("active" if m.get("isActive") else
                                            "team" if (m.get("isStaff") or m.get("isAdmin")) else "inactive")
        return lines, self._flag(f, esc(str(status)))

    def _notifications(self, f: Fetched):
        n = dict_of(f).get("notifications")
        cats = (n or {}).get("categories") if isinstance(n, dict) else {}
        lines = []
        for name, chans in sorted((cats or {}).items()):
            if not isinstance(chans, dict):
                continue
            on = [c for c, v in chans.items() if v]
            lines.append("%-14s %s" % (esc(name), "[$success]%s[/]" % " ".join(on) if on else "[dim]off[/dim]"))
        return lines or ["[dim]no preferences returned[/dim]"], self._flag(f, "%d categories" % len(lines))

    def _alerts(self, f: Fetched):
        alerts = [a for a in (dict_of(f).get("alerts") or items_of(f)) if isinstance(a, dict)]
        lines = ["%s [b]%s[/b]  [dim]%s · %s[/dim]" % ("●" if a.get("active") else "○", esc(a.get("name") or ""),
                                                     a.get("frequency") or "", esc(trunc(plain(a.get("description")), 60)))
                 for a in alerts[:10]]
        return lines or ["[dim]no alerts — saved searches that email you a digest[/dim]"], self._flag(f, plural(len(alerts), "alert"))

    def _interests(self, f: Fetched):
        tags = [t for t in (dict_of(f).get("tags") or []) if isinstance(t, dict)]
        on = [t.get("name") for t in tags if t.get("subscribed")]
        lines = [esc(", ".join(str(x) for x in on if x)) if on else "[dim]no interests subscribed[/dim]"]
        return lines, self._flag(f, "%d of %d" % (len(on), len(tags)))

    def _calendar(self, f: Fetched):
        cal = dict_of(f).get("calendar")
        cal = cal if isinstance(cal, dict) else {}
        feed = cal.get("feed") if isinstance(cal.get("feed"), dict) else {}
        toggles = cal.get("toggles") if isinstance(cal.get("toggles"), dict) else {}
        on = [_toggle_label(k) for k, v in toggles.items() if v]
        lines = []
        if feed.get("webcalURL") or feed.get("httpsURL"):
            lines.append("[dim]feed:[/dim] %s" % esc(feed.get("webcalURL") or feed.get("httpsURL")))
        lines.append("[dim]includes:[/dim] %s" % (esc(", ".join(on)) if on else "[dim]nothing[/dim]"))
        return lines, self._flag(f, "%d of %d included" % (len(on), len(toggles)))

    def _locator(self, f: Fetched):
        s = dict_of(f).get("locatorSettings")
        s = s if isinstance(s, dict) else {}
        on = [k for k in ("events", "tickets", "trips") if s.get(k)]
        lines = ["%s  [dim]sections: %s[/dim]" % ("[$success]enabled[/]" if s.get("enabled") else "[dim]disabled[/dim]",
                                                 ", ".join(on) if on else "none")]
        return lines, self._flag(f, "")


def _toggle_label(key: str) -> str:
    """`includeMyTickets` → "my tickets"."""
    import re as _re
    words = _re.sub(r"([a-z])([A-Z])", r"\1 \2", str(key).replace("include", "", 1)).strip()
    return words.lower() or str(key)
