"""People — search DCers, ask the matchmaker, and manage who you follow.
Profiles show exactly what the API exposes to any DCer; `o` opens the full
profile in the app."""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from textual import work
from textual.binding import Binding
from textual.widgets import Input

from .data import Fetched
from .format import flag, plural, trunc
from .profile import profile_lines
from .listing import ListDetailScreen, dict_of, esc, items_of, plain, name_and_headline
from .screens import WEB_APP

MODES = ("follows", "search", "match")


class PeopleScreen(ListDetailScreen):
    SECTION = "people"
    TITLE_TEXT = "Profiles"
    TOP_INPUT = True
    HINT = "↑↓ pick a DCer · → open · Search / Match / Follow are buttons in the detail"
    URL = WEB_APP + "/members"
    COLUMNS = ("Name", "Headline", "Chapter")
    COLUMN_WIDTHS = {"Handle": 18, "Headline": 40, "Chapter": 16}
    COLUMNS_COMPACT = ("Name", "Headline")
    EMPTY_TEXT = "nobody here yet — press Enter to search DCers"

    BINDINGS = [
        Binding("s", "search", "Search", show=False),
        Binding("M", "match", "Match", show=False),
        Binding("F", "follow", "Follow", show=False),
        Binding("U", "unfollow", "Unfollow", show=False),
        Binding("escape", "back_to_follows", "Follows", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.mode = "follows"
        self.query_text = ""
        self._following = set()
        self._person: Optional[dict] = None

    def show_person(self, member: dict) -> None:
        """Open one DCer (from Home, Locator, Search, an attendee list…) in the detail."""
        self.mode = "person"
        self._person = dict(member)
        self._detail_item = None
        self._pending_key = str(member.get("userID") or "")
        self.refresh_data(force=False)

    def populate(self) -> None:
        super().populate()
        self.main_pane().mount(Input(placeholder="search DCers…", id="people-query", classes="-hidden"), before=0)

    # ── rows ──────────────────────────────────────────────────────────
    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        follows = data.fetch("follows-profiles", force=force)
        self._following = {p.get("userID") for p in _profiles(follows)}
        if self.mode == "person" and self._person:
            person = dict(self._person)
            # enrich from search (headline, business) — the full profile arrives with API 2.5
            name = person.get("displayName") or person.get("userName") or ""
            if name and not person.get("headline"):
                hit = data.fetch("search-profiles", name, limit=5)
                for h in dict_of(hit).get("hits") or []:
                    if isinstance(h, dict) and str(h.get("userID")) == str(person.get("userID")):
                        person.update({k: v for k, v in h.items() if v not in (None, "")})
                        break
            fetched = follows
            rows = [person]
        elif self.mode == "search" and self.query_text:
            fetched = data.fetch("search-profiles", self.query_text, limit=50)
            hits = dict_of(fetched).get("hits") or dict_of(fetched).get("items") or []
            rows = [_flatten(h) for h in hits if isinstance(h, dict)]
        elif self.mode == "match":
            fetched = data.fetch("profile-match", query=self.query_text or None, limit=50)
            results = dict_of(fetched).get("results") or dict_of(fetched).get("items") or []
            rows = []
            for r in results:
                if not isinstance(r, dict):
                    continue
                prof = dict(r.get("profile") or {}) if isinstance(r.get("profile"), dict) else dict(r)
                prof["_score"] = r.get("score")
                rows.append(prof)
        else:
            fetched = follows
            rows = _profiles(follows)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        return rows

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("userID") or index)

    def base_columns(self):
        if self.mode == "follows":
            return ("Name",)
        return super().base_columns()

    def _rows_loaded(self, rows, error):
        self._setup_columns()          # the column set depends on the mode
        super()._rows_loaded(rows, error)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        chapter = item.get("chapter")
        chapter = ("%s %s" % (flag(chapter.get("countryCode")), chapter.get("cityName") or "")).strip() if isinstance(chapter, dict) else (chapter or "")
        name = item.get("displayName") or item.get("userName") or ""
        name = ("★ " if item.get("userID") in self._following else "👤 ") + name
        cells = {"Name": trunc(name, 26), 
                 "Headline": trunc(plain(item.get("headline") or item.get("businessName") or ""), 40),
                 "Chapter": trunc(str(chapter or ""), 16)}
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        what = {"follows": "you follow", "search": "matching “%s”" % self.query_text,
                "match": "matched" + (" for “%s”" % self.query_text if self.query_text else " for you"),
                "person": "· Esc for the people you follow"}[self.mode]
        return "%s %s  [dim]%s[/dim]" % (plural(len(self.items), "DCer"), what, self.HINT)

    def detail_actions(self):
        item = self._detail_item or {}
        following = item.get("userID") in self._following
        return [("Search", "search"), ("Match for me", "match"),
                ("Unfollow", "unfollow") if following else ("Follow", "follow"),
                ("Open profile", "app.open_in_browser")]

    def action_open_detail(self) -> None:
        if not self.items:
            self.action_search()
            return
        super().action_open_detail()

    # ── detail ────────────────────────────────────────────────────────
    def detail_title(self, item: dict) -> str:
        return name_and_headline(item.get("displayName") or "", str(item.get("headline") or ""))

    def fetch_detail(self, item: dict, force: bool) -> Any:
        dc = self.app.data.dc  # type: ignore[attr-defined]
        if hasattr(dc, "dcer"):
            return self.app.data.fetch("dcer", item.get("userID"), force=force)  # type: ignore[attr-defined]
        return None

    def render_detail(self, item: dict, data: Any) -> List[str]:
        prof = dict(item)
        if data is not None and data.ok:
            body = dict_of(data)
            prof.update(body.get("profile") if isinstance(body.get("profile"), dict) else body)
        lines: List[str] = []
        if prof.get("_score") is not None:
            lines.append("[dim]match score %.2f[/dim]" % float(prof["_score"]))
        lines += profile_lines(prof, width=self.detail_width())
        if data is not None and data.error:
            lines.append("[$warning]%s[/]" % esc(data.error))
        lines.append("")
        lines.append("[dim]%s[/dim]" % ("★ following" if prof.get("userID") in self._following else "not following"))
        return lines

    # ── actions ───────────────────────────────────────────────────────
    def action_search(self) -> None:
        box = self.query_one("#people-query", Input)
        box.placeholder = "search DCers by name, business, city…"
        box.remove_class("-hidden")
        box.focus()
        self._pending_mode = "search"

    def action_match(self) -> None:
        box = self.query_one("#people-query", Input)
        box.placeholder = "describe who you want to meet (empty = recommend for me)"
        box.remove_class("-hidden")
        box.focus()
        self._pending_mode = "match"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "people-query":
            return
        self.query_text = event.value.strip()
        self.mode = getattr(self, "_pending_mode", "search")
        if self.mode == "search" and not self.query_text:
            self.mode = "follows"
        event.input.add_class("-hidden")
        self._detail_item = None
        self.refresh_data(force=False)
        self.query_one("#list").focus()

    def action_back_to_follows(self) -> None:
        if self._detail_open:
            self.action_close_detail()
            return
        if self.mode != "follows":
            self.mode, self.query_text = "follows", ""
            self._detail_item = None
            self.refresh_data(force=False)

    def action_follow(self) -> None:
        item = self.selected()
        if item is None:
            return
        self.mutate("follow-profile", item.get("userID"), ok_text="following %s" % (item.get("displayName") or ""))

    def action_unfollow(self) -> None:
        item = self.selected()
        if item is None:
            return
        self.mutate("unfollow-profile", item.get("userID"), ok_text="unfollowed %s" % (item.get("displayName") or ""))

    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)
        if fetched.ok:
            self.refresh_data(force=True)

    def current_url(self) -> str:
        item = self.selected()
        if item and (item.get("shortURL") or item.get("profileURL")):
            return str(item.get("shortURL") or item.get("profileURL"))
        if item and item.get("userName"):
            return WEB_APP + "/" + str(item["userName"])
        return self.URL


def _profiles(fetched: Fetched) -> List[dict]:
    body = dict_of(fetched)
    profiles = body.get("profiles") if isinstance(body.get("profiles"), list) else None
    return [p for p in (profiles if profiles is not None else items_of(fetched)) if isinstance(p, dict)]


def _flatten(hit: dict) -> dict:
    """Search hits may nest the profile under `profile`; flatten for the table."""
    if isinstance(hit.get("profile"), dict):
        out = dict(hit["profile"]); out.setdefault("_score", hit.get("score")); return out
    return hit
