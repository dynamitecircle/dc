"""Data layer — ``DC`` client + :class:`DiskCache` + :class:`RateBudget`.

Screens never call ``dc.<command>()`` directly. They ask a
:class:`DataClient` for a *command* by its CLI name (``"trips"``,
``"event-schedule"``, …) and get back a :class:`Fetched` that says where
the data came from (cache / network), how old it is, and whether the call
failed — so a screen can always render *something* (stale data + a
warning) instead of a traceback.

Thread-safety: Textual runs API calls in worker threads. ``DiskCache`` and
``RateBudget`` lock internally; ``DC`` itself is plain urllib and safe to
call concurrently.

No Textual import — unit-tested offline with a stub client.
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable, Dict, Iterable, Optional

from .budget import RateBudget
from .cache import DiskCache

__all__ = ["DataClient", "Fetched", "INVALIDATES"]

#: Which cached reads a mutation makes stale. Keys are CLI command names.
INVALIDATES: Dict[str, tuple] = {
    "trip-create":          ("trips", "overlaps", "locator"),
    "trip-update":          ("trips", "trip", "trip-discovery", "overlaps", "locator"),
    "trip-delete":          ("trips", "trip", "trip-discovery", "overlaps", "locator"),
    "trip-refresh":         ("trip", "trip-discovery"),
    "event-rsvp":           ("events", "event", "event-attendees", "tickets"),
    "virtual-event-rsvp":   ("virtual-events", "virtual-event", "virtual-event-attendees"),
    "session-bookmark":     ("event-agenda", "event-schedule"),
    "meetup-rsvp":          ("event-meetups", "event-agenda"),
    "room-subscribe":       ("rooms", "inbox", "room"),
    "room-unsubscribe":     ("rooms", "inbox", "room"),
    "room-mute":            ("rooms", "room"),
    "room-unmute":          ("rooms", "room"),
    "room-archive":         ("rooms", "inbox", "room"),
    "room-unarchive":       ("rooms", "inbox", "room"),
    "room-pin":             ("rooms", "room"),
    "room-unpin":           ("rooms", "room"),
    "room-read":            ("rooms", "inbox", "room"),
    "room-unread":          ("rooms", "inbox", "room"),
    "follow-profile":       ("follows-profiles", "locator"),
    "unfollow-profile":     ("follows-profiles", "locator"),
    "follow-chapter":       ("follows-chapters", "locator"),
    "unfollow-chapter":     ("follows-chapters", "locator"),
    "profile-update":       ("profile",),
    "notifications-update": ("notifications",),
    "locator-settings-update": ("locator-settings",),
    "calendar-update":      ("calendar",),
    "alerts-create":        ("alerts",),
    "alerts-update":        ("alerts",),
    "alerts-delete":        ("alerts",),
    "interests-update":     ("interests",),
}


class Fetched:
    """Result of :meth:`DataClient.fetch`."""

    __slots__ = ("command", "data", "from_cache", "stale", "age", "error", "fetched_at")

    def __init__(self, command: str, data: Any, *, from_cache: bool, stale: bool,
                 age: float, error: Optional[str], fetched_at: float):
        self.command = command
        self.data = data
        self.from_cache = from_cache
        self.stale = stale
        self.age = age
        self.error = error
        self.fetched_at = fetched_at

    @property
    def ok(self) -> bool:
        return self.error is None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Fetched(%r, cache=%s, stale=%s, age=%.0fs, error=%r)" % (
            self.command, self.from_cache, self.stale, self.age, self.error)


def cache_secret(dc: Any) -> str:
    """The member's API key seals the disk cache (see cache.py); empty when unknown."""
    try:
        return str(dc._core._api_key())             # noqa: SLF001 — same package family
    except Exception:  # noqa: BLE001
        return ""


class DataClient:
    def __init__(self, dc: Any, cache: Optional[DiskCache] = None,
                 budget: Optional[RateBudget] = None, clock: Callable[[], float] = time.time):
        self.dc = dc
        self.cache = cache if cache is not None else DiskCache(secret=cache_secret(dc))
        self.budget = budget if budget is not None else RateBudget()
        self._clock = clock
        self._inflight: Dict[str, threading.Lock] = {}
        self._inflight_guard = threading.Lock()
        self._local = threading.local()
        self._attach_header_observer()

    # ── Wiring ────────────────────────────────────────────────────────

    def _attach_header_observer(self) -> None:
        """Feed every response's ``X-RateLimit-*`` headers into the budget.

        ``dc.py`` exposes ``HttpClient._on_response`` for exactly this; we
        look it up on the module the ``DC`` instance came from so both
        ``from dc import DC`` (repo) and ``from dynamitecircle import DC``
        (pip) work. Missing hook → budget only learns from ``/limits``.
        """
        module = sys.modules.get(type(self.dc).__module__)
        http = getattr(module, "HttpClient", None)
        if http is None or not hasattr(http, "_on_response"):
            return
        previous = getattr(http, "_on_response", None)
        budget = self.budget

        def _observe(method, url, status, headers):
            budget.observe_headers(headers)
            if previous is not None:
                try:
                    previous(method, url, status, headers)
                except Exception:  # noqa: BLE001 — never break a request
                    pass

        http._on_response = _observe

    # ── Reads ─────────────────────────────────────────────────────────

    def _method(self, command: str) -> Callable[..., Any]:
        name = command.replace("-", "_")
        fn = getattr(self.dc, name, None)
        if fn is None or not callable(fn):
            raise AttributeError("DC client has no command %r" % command)
        return fn

    def cache_only(self):
        """``with data.cache_only(): …`` — every fetch on this thread answers from the
        cache (fresh or stale) and never touches the network: a screen paints what
        it showed last time while the real fetch runs."""
        client = self

        class _Scope:
            def __enter__(self):
                client._local.cache_only = True

            def __exit__(self, *exc):
                client._local.cache_only = False
                return False

        return _Scope()

    def cached(self, command: str, *args: Any, **kwargs: Any) -> Optional[Fetched]:
        """Whatever the cache holds for this call (fresh or stale), no network."""
        key = DiskCache.key(command, *args, **kwargs)
        entry = self.cache.get(key)
        if entry is None:
            return None
        now = self._clock()
        return Fetched(command, entry.data, from_cache=True,
                       stale=not entry.is_fresh(self.cache.ttl_for(command), now),
                       age=entry.age(now), error=None, fetched_at=entry.stored_at)

    def fetch(self, command: str, *args: Any, force: bool = False,
              background: bool = False, **kwargs: Any) -> Fetched:
        """Return data for ``command(*args, **kwargs)``.

        - Fresh cache hit → returned immediately, no network.
        - Otherwise call the API (unless ``background`` and the budget says
          no) and cache the result.
        - On error, or when skipped for budget, return the stale entry if
          there is one, with ``error`` set so the UI can flag it.

        Concurrent fetches of the same key are serialised so a screen that
        mounts twice doesn't spend two requests.
        """
        key = DiskCache.key(command, *args, **kwargs)
        now = self._clock()
        if getattr(self._local, "cache_only", False):
            return self._fallback(command, self.cache.get(key), "not cached yet")   # any age, never the network
        ttl = self.cache.ttl_for(command)
        if not force:
            entry = self.cache.get_fresh(key, command)
            if entry is not None:
                return Fetched(command, entry.data, from_cache=True, stale=False,
                               age=entry.age(now), error=None, fetched_at=entry.stored_at)

        with self._inflight_guard:
            lock = self._inflight.setdefault(key, threading.Lock())
        with lock:
            # Another thread may have just filled it.
            if not force:
                entry = self.cache.get_fresh(key, command)
                if entry is not None:
                    return Fetched(command, entry.data, from_cache=True, stale=False,
                                   age=entry.age(now), error=None, fetched_at=entry.stored_at)
            stale = self.cache.get(key)
            if background and not self.budget.can_spend(1, background=True):
                return self._fallback(command, stale, "rate budget reserved — showing cached data")
            try:
                result = self._method(command)(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — DCError / UsageError / network
                return self._fallback(command, stale, str(exc) or exc.__class__.__name__)
            data = getattr(result, "data", result)  # unwrap dc.Result
            if command == "limits":
                self.budget.observe_limits(data)
            entry = self.cache.set(key, command, data)
            return Fetched(command, data, from_cache=False, stale=False, age=0.0,
                           error=None, fetched_at=entry.stored_at)

    def _fallback(self, command: str, stale, error: str) -> Fetched:
        now = self._clock()
        if stale is not None:
            return Fetched(command, stale.data, from_cache=True, stale=True,
                           age=stale.age(now), error=error, fetched_at=stale.stored_at)
        return Fetched(command, None, from_cache=False, stale=False, age=0.0,
                       error=error, fetched_at=now)

    # ── Writes ────────────────────────────────────────────────────────

    def mutate(self, command: str, *args: Any, invalidate: Optional[Iterable[str]] = None,
               **kwargs: Any) -> Fetched:
        """Run a write command, then drop the cached reads it affects.

        Writes are always user-initiated, so they bypass the background
        reserve and are never served from cache.
        """
        now = self._clock()
        try:
            result = self._method(command)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return Fetched(command, None, from_cache=False, stale=False, age=0.0,
                           error=str(exc) or exc.__class__.__name__, fetched_at=now)
        data = getattr(result, "data", result)
        targets = tuple(invalidate) if invalidate is not None else INVALIDATES.get(command, ())
        if targets:
            self.cache.invalidate(targets)
        return Fetched(command, data, from_cache=False, stale=False, age=0.0,
                       error=None, fetched_at=now)
