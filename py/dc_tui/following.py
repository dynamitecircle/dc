"""Locator sub-tabs beyond the digest, mirroring the web's /locator tabs:

- Following (MyFollowing.vue): the DCers and the chapters you follow.
- New Trips (NewTrips.vue): recently added trips. The web reads the whole
  community's latest trips straight from Firestore; the Member API only exposes
  trips from DCers you follow (the Locator digest), which is the web tab's
  "Only from DCers I follow" view — so that is what this tab shows.
"""
from __future__ import annotations

from typing import Any, List, Tuple

from .data import Fetched
from .format import date_range, flag, plural
from .listing import ListDetailScreen, dict_of, esc, items_of, name_and_headline, next_cursor
from .profile import profile_lines
from .screens import WEB_APP


def _profiles(f: Fetched) -> List[dict]:
    data = dict_of(f)
    return [p for p in (data.get("profiles") or data.get("items") or []) if isinstance(p, dict)]


def _chapters(f: Fetched) -> List[dict]:
    data = dict_of(f)
    return [c for c in (data.get("chapters") or data.get("items") or []) if isinstance(c, dict)]


def _chapter_name(c: dict) -> str:
    return "DC %s Chapter" % (c.get("city") or c.get("cityName") or c.get("name") or "?")


class FollowingScreen(ListDetailScreen):
    SECTION = "following"
    TITLE_TEXT = "Following"
    HINT = "↑↓ pick · Enter opens the profile · Unfollow is a button in the detail"
    URL = WEB_APP + "/locator/following"
    LIST_TABS = (("people", "DCers"), ("chapters", "Chapters"))
    COLUMNS = ("Name",)
    COLUMN_WIDTHS = {"Handle": 24, "Country": 16}
    EMPTY_TEXT = "you don't follow anyone here yet — follow DCers from their profile (Profiles) and chapters on the web"

    def base_columns(self):
        return ("Chapter", "Country") if self.list_tab == "chapters" else ("Name",)

    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        if self.list_tab == "chapters":
            fetched = data.fetch("follows-chapters", force=force)
            rows = _chapters(fetched)
            rows.sort(key=lambda c: str(c.get("city") or c.get("cityName") or "").lower())
        else:
            fetched = data.fetch("follows-profiles", force=force)
            rows = _profiles(fetched)
            rows.sort(key=lambda p: str(p.get("displayName") or p.get("userName") or "").lower())
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        self._cap = dict_of(fetched).get("cap")
        return rows

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("userID") or item.get("cityID") or index)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        if self.list_tab == "chapters":
            cells = {"Chapter": "%s %s" % (flag(item.get("countryCode")) or "📍", _chapter_name(item)),
                     "Country": str(item.get("country") or "")}
        else:
            cells = {"Name": "👤 " + str(item.get("displayName") or item.get("userName") or "DCer"),
                     }
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        noun = "chapter" if self.list_tab == "chapters" else "DCer"
        cap = getattr(self, "_cap", None)
        return "%s you follow%s  [dim]%s[/dim]" % (plural(len(self.items), noun), (" of %s" % cap) if cap else "", self.HINT)

    def detail_title(self, item: dict) -> str:
        if self.list_tab == "chapters":
            return "%s  [dim]%s[/dim]" % (esc(_chapter_name(item)), esc(item.get("country") or ""))
        prof = self._full(item)
        return name_and_headline(prof.get("displayName") or "DCer", str(prof.get("headline") or ""))

    def _full(self, item: dict) -> dict:
        """The list row merged with its loaded full profile (when it is the open item)."""
        prof = dict(item)
        data = self._detail_data if item is self._detail_item else None
        if data is not None and getattr(data, "ok", False):
            body = dict_of(data)
            prof.update(body.get("profile") if isinstance(body.get("profile"), dict) else body)
        return prof

    def detail_actions(self):
        if self.list_tab == "chapters":
            return [("Unfollow", "unfollow"), ("Open on web", "app.open_in_browser")]
        return [("View profile", "view_person"), ("Unfollow", "unfollow"), ("Open on web", "app.open_in_browser")]

    def fetch_detail(self, item: dict, force: bool) -> Any:
        data = self.app.data  # type: ignore[attr-defined]
        if self.list_tab == "people" and item.get("userID") and hasattr(data.dc, "dcer"):
            return data.fetch("dcer", item.get("userID"), force=force)     # the full profile, always
        return None

    def render_detail(self, item: dict, data: Any) -> List[str]:
        if self.list_tab == "chapters":
            return ["You follow this chapter: its events, new DCers and visitors show up in your Locator."]
        prof = self._full(item)
        lines = profile_lines(prof, width=self.detail_width(), header=False)[1:]   # the headline sits in the title
        if data is None:
            lines.append("[dim]loading the profile…[/dim]")
        elif getattr(data, "error", None):
            lines.append("[$warning]%s[/]" % esc(data.error))
        return lines

    def action_open_detail(self) -> None:
        item = self.selected()
        if self.two_pane:                     # side by side: the profile shows in the pane
            super().action_open_detail()
            return
        if item is not None and self.list_tab == "people":
            self.app.open_person(dict(item))  # type: ignore[attr-defined]
            return
        super().action_open_detail()

    def action_view_person(self) -> None:
        item = self._detail_item or self.selected()
        if item is not None:
            self.app.open_person(dict(item))  # type: ignore[attr-defined]

    def action_unfollow(self) -> None:
        item = self._detail_item or self.selected()
        if item is None:
            return
        if self.list_tab == "chapters":
            self.mutate("unfollow-chapter", item.get("cityID"), ok_text="unfollowed %s" % _chapter_name(item))
        else:
            self.mutate("unfollow-profile", item.get("userID"), ok_text="unfollowed %s" % (item.get("displayName") or "DCer"))

    def after_mutation(self, fetched: Fetched, ok_text: str) -> None:
        super().after_mutation(fetched, ok_text)
        if fetched.ok:
            self._detail_item = None
            self.refresh_data(force=True)

    def current_url(self) -> str:
        item = self._detail_item or self.selected() or {}
        if self.list_tab == "people" and item.get("userName"):
            return item.get("profileURL") or "%s/profile/%s" % (WEB_APP, item["userName"])
        return self.URL


class NewTripsScreen(ListDetailScreen):
    SECTION = "newtrips"
    TITLE_TEXT = "New Trips"
    HINT = "Enter opens the DCer"
    LIST_TABS = (("following", "DCers I Follow"), ("all", "All"))
    URL = WEB_APP + "/locator/new-trips"
    COLUMNS = ("Trip", "Dates")                    # who → where in one column, so the place never drops
    COLUMN_WIDTHS = {"Dates": 25}                  # "06 Dec 2026 – 16 Jan 2027"
    EMPTY_TEXT = "no upcoming trips from DCers you follow"

    def fetch_rows(self, force: bool) -> List[dict]:
        data = self.app.data  # type: ignore[attr-defined]
        if self.list_tab == "all":
            if not hasattr(data.dc, "trips_recent"):
                raise RuntimeError("community trips need a newer dc client (trips-recent)")
            fetched = data.fetch("trips-recent", limit=100, force=force)
            if fetched.error and fetched.data is None:
                raise RuntimeError(fetched.error)
            self._next_cursor = next_cursor(fetched)
            self._new = set()
            return [t for t in items_of(fetched) if isinstance(t, dict)]      # newest first, as the web
        fetched = data.fetch("locator", force=force)
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        people = dict_of(fetched).get("favoritePeople")
        people = people if isinstance(people, dict) else {}
        seen, trips = set(), []
        for t in list(people.get("newTrips") or []) + list(people.get("comingTrips") or []):
            if isinstance(t, dict) and t.get("tripID") not in seen:
                seen.add(t.get("tripID"))
                trips.append(t)
        new_ids = {t.get("tripID") for t in people.get("newTrips") or [] if isinstance(t, dict)}
        trips.sort(key=lambda t: (t.get("tripID") not in new_ids, str(t.get("startDate") or "")))
        self._new = new_ids
        return trips

    def fetch_more(self, cursor):
        if self.list_tab != "all":
            return [], None
        fetched = self.app.data.fetch("trips-recent", limit=100, cursor=cursor)  # type: ignore[attr-defined]
        if fetched.error and fetched.data is None:
            raise RuntimeError(fetched.error)
        return [t for t in items_of(fetched) if isinstance(t, dict)], next_cursor(fetched)

    def row_key(self, item: dict, index: int) -> str:
        return str(item.get("tripID") or index)

    def _member(self, item: dict) -> dict:
        m = item.get("member")
        return m if isinstance(m, dict) else {}

    def _where(self, item: dict) -> str:
        loc = item.get("location") if isinstance(item.get("location"), dict) else {}
        name = loc.get("city") or loc.get("name") or "Somewhere"
        return "%s %s" % (flag(loc.get("countryCode")) or "📍", name)

    def row_cells(self, item: dict) -> Tuple[str, ...]:
        m = self._member(item)
        who = "👤 %s → %s" % (m.get("displayName") or m.get("userName") or "DCer", self._where(item))
        cells = {"Trip": who, "Dates": date_range(item.get("startDate"), item.get("endDate"))}
        return tuple(cells[c] for c in self._columns())

    def hint_text(self) -> str:
        scope = "recently added across DC" if self.list_tab == "all" else "from DCers you follow"
        return "%s %s  [dim]%s[/dim]" % (plural(len(self.items), "trip"), scope, self.HINT)

    def detail_title(self, item: dict) -> str:
        m = self._member(item)
        return "%s  [dim]%s[/dim]" % (esc(m.get("displayName") or "DCer"), esc(self._where(item)))

    def detail_actions(self):
        return [("View profile", "view_person"), ("Open on web", "app.open_in_browser")]

    def fetch_detail(self, item: dict, force: bool) -> Any:
        return None

    def render_detail(self, item: dict, data: Any) -> List[str]:
        lines = ["✈ %s  %s" % (esc(self._where(item)), date_range(item.get("startDate"), item.get("endDate")))]
        if item.get("note"):
            lines += ["", esc(item["note"])]
        return lines

    def action_open_detail(self) -> None:
        self.action_view_person()

    def action_view_person(self) -> None:
        item = self._detail_item or self.selected()
        if item is not None and self._member(item):
            self.app.open_person(dict(self._member(item)))  # type: ignore[attr-defined]

    def current_url(self) -> str:
        item = self._detail_item or self.selected() or {}
        return item.get("shortURL") or item.get("tripURL") or self.URL
