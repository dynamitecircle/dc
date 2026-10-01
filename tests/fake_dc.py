"""A stand-in for `dc.DC` with canned Member API payloads (shapes copied from
real responses) so the TUI can be driven headless and offline."""
from __future__ import annotations

from typing import Any, Dict, List

_M = lambda uid, name, user=None: {"userID": uid, "displayName": name, "userName": user or name.replace(" ", ""),
                                   "photo": "", "profileURL": "https://dc.dynamitecircle.com/profile/%s" % (user or name.replace(" ", ""))}
_LOC = lambda city, cc: {"city": city, "name": city, "country": cc, "countryCode": cc}


def _env(items: List[dict], **extra: Any) -> dict:
    out = {"items": items, "count": len(items), "cursor": None, "has_more": False}
    if extra:
        out["extra"] = extra
    return out


class FakeDC:
    """Every method the screens call, with deterministic data."""

    def __init__(self) -> None:
        self.calls: List[tuple] = []
        self.rsvps: Dict[str, str] = {}
        self.badges: Dict[str, int] = {"r1": 2}

    def _log(self, *a: Any) -> None:
        self.calls.append(a)

    # identity / limits
    def profile(self):
        self._log("profile")
        return {"userID": "940", "displayName": "Simon Payne", "userName": "SimonPayne", "headline": "CTO",
                "businessName": "Dynamite", "chapter": {"cityName": "Osaka", "countryCode": "JP", "placeID": "osaka"}}

    def membership(self):
        self._log("membership")
        return {"membership": {"role": {"key": "team", "label": "DC Team Member"}, "isActive": False, "isStaff": True,
                               "dcBlack": {"isMember": False}, "billing": {}, "trial": {}, "joinedDate": "2020-06-20"}}

    def limits(self):
        self._log("limits")
        return {"tier": "dcb", "perMinute": 60, "perDay": 3000}

    def follows_chapters(self):
        return {"chapters": [{"cityID": "tokyo", "placeID": "tokyo", "cityName": "Tokyo", "countryCode": "JP"}]}

    def follows_profiles(self):
        return {"profiles": [_M("1", "Alex Harling"), _M("2", "Till Carlos")], "count": 2, "cap": 150}

    # home
    def inbox(self, limit=50, cursor=None):
        self._log("inbox")
        names = {"r1": "DC Announcements", "r2": "SaaS", "dm_940_1": "Alex Harling"}
        rows = [{"roomID": rid, "roomName": names.get(rid, rid), "roomType": "channel", "badgeCount": n} for rid, n in self.badges.items() if n]
        return _env(rows, totalUnread=sum(self.badges.values()))

    def announcements_latest(self):
        return {"announcements": [{"announcementURL": "https://dc.dynamitecircle.com/channel/r1/message/m1", "shortURL": "https://dc.mba/x",
                                   "author": _M("9", "Beatriz Alves"), "content": "**Hello** DC", "createdAt": "2026-09-28T10:00:00Z"}]}

    def tickets(self, status="", limit=50, cursor=None):
        return _env([{"ticketID": "t1", "eventID": "e-dcbkk", "eventName": "DCBKK 2026", "status": "valid", "ticketName": "GA",
                      "startDate": "2026-10-22", "endDate": "2026-10-25"}])

    def events(self, past=False, limit=20, cursor=None):
        self._log("events", past)
        if past:
            return _env([{"eventID": "e-old", "name": "DCMEX 2026", "eventType": "dcmex", "startDate": "2026-04-06", "endDate": "2026-04-09",
                          "city": {"name": "Mexico City", "placeID": "cdmx"}, "isDateConfirmed": True}])
        return _env([
            {"eventID": "e-dcbkk", "name": "DCBKK 2026", "eventType": "dcbkk", "startDate": "2026-10-22", "endDate": "2026-10-25",
             "city": {"name": None, "placeID": "bkk", "country": "Thailand"}, "venue": {"name": "Conrad", "city": "Bangkok"}, "isDateConfirmed": True,
             "ticketsEnabled": True, "rsvpEnabled": False, "description": "The big one"},
            {"eventID": "e-junto", "name": "Tokyo October 14 Junto", "eventType": "junto", "startDate": "2026-10-14", "endDate": "2026-10-14",
             "city": {"name": "Tokyo", "placeID": "tokyo"}, "isDateConfirmed": True, "rsvpEnabled": True},
            {"eventID": "e-dcbcn", "name": "DCBCN 2027", "eventType": "dcbcn", "startDate": "2027-07-26", "endDate": "2027-07-30",
             "city": {"name": "Barcelona", "placeID": "bcn"}, "isDateConfirmed": False},
        ])

    def trips(self, past=False, limit=50, cursor=None):
        return _env([{"tripID": "trip1", "location": _LOC("Lisbon", "PT"), "startDate": "2026-11-03", "endDate": "2026-11-10", "note": "SaaS"}])

    def trips_recent(self, limit=50):
        return _env([{"tripID": "rt1", "location": _LOC("Porto", "PT"), "startDate": "2026-11-20", "endDate": "2026-11-24",
                      "member": _M("7", "Nathan Rose")}])

    def dcer_events(self, user_id):
        return {"upcoming": [{"eventID": "e9", "name": "DCBKK 2027", "startDate": "2027-03-01", "endDate": "2027-03-04",
                              "isDateConfirmed": True, "city": {"name": "Bangkok"}}],
                "pastEvents": [], "pastMeetups": [], "alsoAttended": ["DCBKK 2014"]}

    def dcer(self, user_id):
        return {"profile": {"userID": user_id, "displayName": "Alex Harling", "userName": "AlexHarling", "headline": "Community",
                            "businessName": "Dynamite Circle"}}

    def trip(self, trip_id):
        return {"trip": {"tripID": trip_id, "discovery": {"people": [{"profile": _M("3", "Ana Silva"), "whyToMeet": "Runs a SaaS in Lisbon"}],
                                                          "fullPool": [_M("3", "Ana Silva"), _M("4", "Bo Li")], "events": []}}}

    def locator(self, sections="", **_):
        self._log("locator")
        return {"homeCity": {"cityID": "osaka", "cityName": "Osaka", "countryCode": "JP", "newMembers": [], "createdEvents": [], "comingEvents": [],
                             "planningToCity": [], "comingToCity": [{"tripID": "v1", "member": _M("5", "Harley Green"), "location": _LOC("Osaka", "JP"),
                                                                     "startDate": "2027-03-15", "endDate": "2027-03-18", "note": ""}]},
                "favoriteCities": [{"cityID": "tokyo", "cityName": "Tokyo", "countryCode": "JP", "comingEvents": [], "newEvents": [], "newTrips": [],
                                    "comingTrips": [{"tripID": "v2", "member": _M("6", "Lisa Eyo"), "location": _LOC("Tokyo", "JP"),
                                                     "startDate": "2027-03-06", "endDate": "2027-03-20"}]}],
                "favoritePeople": {"newTrips": [], "comingTrips": [{"tripID": "v3", "member": _M("1", "Alex Harling"), "location": _LOC("New York", "US"),
                                                                   "startDate": "2026-12-07", "endDate": "2026-12-12"}],
                                   "purchased": [], "attending": [{"eventID": "e-dcbkk", "eventName": "DCBKK 2026", "member": _M("2", "Till Carlos"),
                                                                    "startDate": "2026-10-22", "endDate": "2026-10-25"}]},
                "myTrips": []}

    # rooms
    def rooms(self, room_type="", limit=50, cursor=None, filter=None):
        self._log("rooms", room_type) if not filter else self._log("rooms", room_type, filter)
        rooms = [{"roomID": "r1", "name": "DC Announcements", "type": "channel", "scope": "dc", "lastActivityAt": "2026-09-28T09:00:00Z", "stats": {"subscribers": 900},
                  "seen": {"isPinned": False, "isMuted": False, "isArchived": False}},
                 {"roomID": "r2", "name": "SaaS", "type": "channel", "scope": "dc", "lastActivityAt": "2026-09-27T09:00:00Z", "stats": {"subscribers": 400},
                  "seen": {"isPinned": True, "isMuted": True, "isArchived": False}},
                 {"roomID": "dm_940_1", "name": "", "displayName": "Alex Harling", "type": "dm", "scope": "dc", "lastActivityAt": "2026-09-26T09:00:00Z",
                  "participant": {"userID": "1", "displayName": "Alex Harling", "userName": "AlexHarling", "profileURL": ""}}]
        if filter == "pinned":           # an older pinned DM, past the first page of recent rooms
            rooms.append({"roomID": "dm_940_7", "name": "", "displayName": "Ian Schoen", "type": "dm", "scope": "dc",
                          "lastActivityAt": "2026-01-02T09:00:00Z", "seen": {"isPinned": True, "isMuted": False, "isArchived": False}})
        key = {"pinned": "isPinned", "muted": "isMuted", "archived": "isArchived"}.get(filter or "")
        return _env([r for r in rooms if (not room_type or r["type"] == room_type) and (not key or (r.get("seen") or {}).get(key))])

    def browse_rooms(self, room_type, limit=50, cursor=None):
        return _env([{"roomID": "r9", "name": "SEO", "type": room_type, "scope": "dc", "stats": {"subscribers": 117}, "lastActivityAt": "2026-09-29T09:00:00Z"}])

    def room(self, room_id):
        return {"room": {"roomID": room_id}, "aiSummaryWeekly": {"type": "weekly", "html": "<p>Busy week</p>", "topics": [{"title": "AI"}],
                                                                  "intervalEndAt": "2026-09-28", "messageCount": 3, "participantCount": 2}}

    def room_messages(self, room_id, limit=50, before=None):
        self._log("room-messages", room_id) if not before else self._log("room-messages", room_id, before)
        if before == "older-1":
            return _env([{"messageID": "m0", "sentAt": "2026-09-20T10:00:00Z", "author": _M("1", "Alex Harling"), "text": "First post", "isHTML": False}])
        out = _env([{"messageID": "m2", "sentAt": "2026-09-28T10:00:00Z", "author": _M("9", "Beatriz Alves"), "text": "▌ Replying to Simon Payne in SaaS Sure!", "isHTML": False},
                     {"messageID": "m1", "sentAt": "2026-09-27T10:00:00Z", "author": _M("940", "Simon Payne"), "text": "<p>Hi <b>all</b></p>", "isHTML": True}])
        out["items"].insert(0, {"messageID": "img-" + room_id, "sentAt": "2026-09-29T10:00:00Z", "author": _M("2", "Till Carlos"), "type": "image",
                                "text": "sunset", "attachment": {"kind": "image", "url": "https://cdn.example/sunset.jpg"}})
        out["items"].append({"messageID": "mx-" + room_id, "sentAt": "2026-09-26T10:00:00Z", "author": _M("2", "Till Carlos"),
                             "text": "only in " + room_id, "isHTML": False})
        out["cursor"] = "older-1"
        return out

    def room_read(self, room_id):
        self._log("room-read", room_id); self.badges[room_id] = 0; return {"seen": {}}

    def room_unread(self, room_id):
        self._log("room-unread", room_id); self.badges[room_id] = max(1, self.badges.get(room_id, 0)); return {"seen": {}}

    def room_mute(self, room_id):
        self._log("room-mute", room_id); return {"seen": {"isMuted": True}}

    def room_subscribe(self, room_id):
        self._log("room-subscribe", room_id); return {"seen": {"isSubscribed": True}}

    # events detail
    def event(self, event_id):
        return {"event": {"eventID": event_id, "name": "DCBKK 2026", "description": "# Big\n**event**", "venue": {"name": "Conrad", "city": "Bangkok"},
                          "ticketsEnabled": True}, "myTickets": [{"ticketID": "t1"}]}

    def event_schedule(self, event_id):
        return {"sessions": [{"sessionID": "s1", "title": "Opening", "startAt": "2026-10-22T09:00:00+07:00", "endAt": "2026-10-22T10:00:00+07:00",
                              "type": "mainstage", "speakers": [{"displayName": "Dan Andrews"}], "date": "2026-10-22"}], "timezone": "Asia/Bangkok"}

    def event_agenda(self, event_id, user_id=None):
        return {"sessions": [{"sessionID": "s1"}], "meetups": [], "timezone": "Asia/Bangkok"}

    def event_meetups(self, event_id):
        return {"meetups": [{"meetupID": "mu1", "title": "Chess Meetup", "date": "2026-10-20", "startTime": "15:00", "endTime": "17:00",
                             "maxSeats": 12, "rsvpCount": 7, "host": _M("7", "Nathan Rose")}], "timezone": "Asia/Bangkok"}

    def event_attendees(self, event_id, limit=100, cursor=None):
        return {"attendees": [{"userID": "8", "displayName": "Mony Chim", "headline": "Ads", "businessIndustry": "Marketing"}], "total": 1}

    def session_bookmark(self, event_id, session_id, bookmarked="true"):
        self._log("session-bookmark", event_id, session_id, bookmarked); return {"ok": True}

    def virtual_events(self, past=False, limit=50, cursor=None):
        return _env([{"sessionID": "vc1", "name": "Welcome Call", "kind": "welcome", "scheduledAt": "2026-10-07T15:00:00Z", "duration": 60,
                      "attendeeCount": 6, "myRsvp": self.rsvps.get("vc1", ""), "meetUrl": "https://meet.google.com/x", "description": "Hello"}])

    def virtual_event(self, session_id):
        return {"event": {"sessionID": session_id, "name": "Welcome Call", "kind": "welcome", "scheduledAt": "2026-10-07T15:00:00Z",
                          "duration": 60, "attendeeCount": 6, "myRsvp": self.rsvps.get(session_id, ""), "meetUrl": "https://meet.google.com/x"}}

    def virtual_event_rsvp(self, session_id, status=""):
        self._log("virtual-event-rsvp", session_id, status); self.rsvps[session_id] = status; return {"ok": True}

    # people / search
    def search_profiles(self, q, *, limit=20, page=1):
        return {"hits": [{"userID": "1", "displayName": "Alex Harling", "userName": "AlexHarling", "headline": "Community"}], "total": 1}

    def search(self, q, *, limit=5, user_id=None):
        return {"profiles": {"hits": [{"userID": "1", "displayName": "Alex Harling", "userName": "AlexHarling", "headline": "Community"}]},
                "rooms": {"hits": [{"roomID": "r2", "name": "SaaS", "type": "channel"}]},
                "messages": {"hits": [{"messageID": "m1", "roomID": "r2", "roomName": "SaaS", "body": "<p>hi</p>", "author": _M("9", "Beatriz Alves"), "sentAt": "2026-09-27"}]},
                "events": {"hits": []}, "chapters": {"hits": [{"cityID": "tokyo", "name": "Tokyo", "memberCount": 40}]}}

    def search_rooms(self, q, **kw):
        return {"hits": [{"roomID": "r2", "name": "SaaS", "type": "channel"}]}

    def search_messages(self, q, **kw):
        if kw.get("user_id"):
            return {"hits": [{"messageID": "pm1", "roomID": "r2", "roomName": "SaaS", "body": "<p>Hello from the profile</p>", "sentAt": "2026-09-20"}]}
        return {"hits": []}

    def search_events(self, q, **kw):
        return {"hits": []}

    def search_chapters(self, q, **kw):
        return {"hits": [{"cityID": "tokyo", "name": "Tokyo", "memberCount": 40}]}

    def profile_match(self, query=None, limit=50, **kw):
        return {"results": [{"score": 0.9, "profile": {"userID": "3", "displayName": "Ana Silva", "userName": "AnaSilva", "headline": "SaaS"}}]}

    def unfollow_profile(self, user_id):
        self._log("unfollow-profile", user_id); return {"ok": True}

    def unfollow_chapter(self, city_id):
        self._log("unfollow-chapter", city_id); return {"ok": True}

    def follow_profile(self, user_id):
        self._log("follow-profile", user_id); return {"ok": True}

    # me
    def notifications(self):
        return {"notifications": {"categories": {"announcement": {"push": True, "email": True}, "chat": {"push": True, "email": False}}}}

    def notifications_update(self, fields):
        self._log("notifications-update", fields); return {"ok": True}

    def alerts(self):
        return {"alerts": [{"alertID": "a1", "name": "Japan", "description": "Anyone talking about Japan", "frequency": "daily", "active": True}]}

    def interests(self):
        return {"tags": [{"name": "saas", "subscribed": True}, {"name": "ecommerce", "subscribed": False}]}

    def calendar(self):
        return {"calendar": {"feed": {"webcalURL": "webcal://x"}, "toggles": {"includeMyTickets": True, "includeMyTrips": False}}}

    def calendar_update(self, fields):
        self._log("calendar-update", fields); return {"ok": True}

    def locator_settings(self):
        return {"locatorSettings": {"enabled": True, "events": True, "tickets": False, "trips": True}}

    def locator_settings_update(self, fields):
        self._log("locator-settings-update", fields); return {"ok": True}

    def places_search(self, q="", limit=10):
        return {"places": [{"placeID": "lis", "name": "Lisbon", "region": "Lisbon", "country": "Portugal"}]}
