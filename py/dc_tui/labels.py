"""Product labels — mirrors the web client's `shared/enum.ts` so the terminal
never shows wire values (`quick-question`, `dc-chapter-event`, `dcb`) as copy."""
from __future__ import annotations

from typing import Any

# EventKind → label (shared/enum.ts)
EVENT_TYPE_LABELS = {
    "dcbkk": "DCBKK", "dcmex": "DCMEX", "dcbcn": "DCBCN", "dc-black": "DC BLACK",
    "dc-accelerator": "DC Accelerator", "dc-x": "DCX", "dc-adventure": "DC Adventure",
    "dc-chapter-event": "Chapter Event", "junto": "Junto", "co-work": "Co-Work", "meet-up": "Meet-Up",
    "mastermind-meetup": "Mastermind", "breakfast": "Breakfast", "brunch": "Brunch", "lunch": "Lunch",
    "dinner": "Dinner", "coffee": "Coffee",
}
#: GlobalEventList in shared/enum.ts — everything else is a local meetup.
GLOBAL_EVENT_TYPES = {"dcbkk", "dcmex", "dcbcn", "dc-black", "dc-accelerator", "dc-x", "dc-adventure", "dc-chapter-event"}
FLAGSHIP_EVENT_TYPES = {"dcbkk", "dcmex", "dcbcn"}

ROOM_TYPE_LABELS = {"channel": "Channel", "dm": "DM", "group": "Group", "discussion": "Discussion",
                    "quick-question": "Quick Question", "event": "Event"}

# SessionKind → label (shared/enum.ts) keyed by the API's `kind`
CALL_KIND_LABELS = {"virtual": "Live Call", "dc": "Connect Calls", "welcome": "Community Welcome Call",
                    "happy": "Happy Hour Huddle", "dcb": "DC BLACK Live Call", "dca": "DC Accelerator Live Call"}


def event_type_label(kind: Any) -> str:
    k = str(kind or "").lower()
    return EVENT_TYPE_LABELS.get(k, k.replace("-", " ").title())


def room_type_label(kind: Any) -> str:
    k = str(kind or "").lower()
    return ROOM_TYPE_LABELS.get(k, k.replace("-", " ").title())


def call_kind_label(kind: Any) -> str:
    k = str(kind or "").lower()
    return CALL_KIND_LABELS.get(k, "Live Call")


def is_global_event(event: dict) -> bool:
    return str(event.get("eventType") or "").lower() in GLOBAL_EVENT_TYPES
