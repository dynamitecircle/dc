"""Rate-budget tracker — knows how many Member API calls we can still afford.

Fed from two sources:

- the ``X-RateLimit-*`` response headers on every request (via the
  ``HttpClient`` response observer in ``dc.py``), and
- ``GET /limits`` (same numbers as JSON, plus the caller's tier).

Header and JSON field names are matched loosely (case-insensitive,
``limit`` / ``remaining`` / ``reset`` for the per-minute window, anything
mentioning ``day`` / ``daily`` for the per-day window) so a rename on the
server degrades to "unknown" instead of a crash.

The tracker drives two decisions in the TUI:

- :meth:`RateBudget.can_spend` — whether a *background* refresh may run
  right now (it keeps a reserve for user-initiated actions), and
- :meth:`RateBudget.poll_interval` — how often the ``/inbox/unread`` tick
  fires, so the background tick never eats more than
  ``TICK_BUDGET_SHARE`` of the daily budget, backing off further when the
  user is idle.

Pure stdlib — unit-tested offline.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, Mapping, Optional

__all__ = ["RateBudget", "TICK_BUDGET_SHARE", "MIN_POLL_SECONDS", "MAX_POLL_SECONDS"]

#: Fraction of the daily budget the background tick may consume.
TICK_BUDGET_SHARE = 0.25
MIN_POLL_SECONDS = 30
MAX_POLL_SECONDS = 3600
DEFAULT_POLL_SECONDS = 300
#: Reserve kept for user-initiated calls; background work stops below it.
RESERVE_FRACTION = 0.2

_DAY_RE = re.compile(r"da(y|ily)", re.IGNORECASE)


def _to_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


class _Window:
    """One rate-limit window (per-minute or per-day)."""

    __slots__ = ("limit", "remaining", "reset_at")

    def __init__(self):
        self.limit: Optional[int] = None
        self.remaining: Optional[int] = None
        self.reset_at: Optional[float] = None  # epoch seconds

    def remaining_now(self, now: float) -> Optional[int]:
        """Remaining calls, treating a passed reset as a full refill."""
        if self.reset_at is not None and now >= self.reset_at and self.limit is not None:
            return self.limit
        return self.remaining

    def as_dict(self) -> Dict[str, Optional[float]]:
        return {"limit": self.limit, "remaining": self.remaining, "resetAt": self.reset_at}


class RateBudget:
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self.minute = _Window()
        self.day = _Window()
        self.tier: Optional[str] = None
        self.updated_at: Optional[float] = None
        self.calls_seen = 0

    # ── Observers ─────────────────────────────────────────────────────

    def observe_headers(self, headers: Optional[Mapping[str, Any]]) -> None:
        """Ingest ``X-RateLimit-*`` headers from one response."""
        if not headers:
            return
        now = self._clock()
        with self._lock:
            self.calls_seen += 1
            for raw_name, raw_value in headers.items():
                name = str(raw_name).lower()
                if not name.startswith("x-ratelimit"):
                    continue
                window = self.day if _DAY_RE.search(name) else self.minute
                value = _to_int(raw_value)
                if value is None:
                    continue
                if "remaining" in name:
                    window.remaining = value
                elif "reset" in name:
                    # Epoch seconds (DC) — but tolerate a "seconds from now"
                    # delta the way Retry-After is expressed.
                    window.reset_at = float(value) if value > 10_000_000 else now + value
                elif "limit" in name:
                    window.limit = value
            self.updated_at = now

    def observe_limits(self, payload: Any) -> None:
        """Ingest the ``GET /limits`` JSON (tier + per-minute / per-day numbers)."""
        if not isinstance(payload, dict):
            return
        now = self._clock()
        with self._lock:
            tier = payload.get("tier") or payload.get("plan") or payload.get("role")
            if isinstance(tier, dict):
                tier = tier.get("key") or tier.get("name") or tier.get("label")
            if isinstance(tier, str) and tier.strip():
                self.tier = tier.strip()
            for key, value in payload.items():
                if not isinstance(value, dict):
                    continue
                lowered = str(key).lower()
                if _DAY_RE.search(lowered):
                    self._ingest_window(self.day, value, now)
                elif "min" in lowered:
                    self._ingest_window(self.minute, value, now)
            # Flat shapes: {"limitPerMinute": 60, "limitPerDay": 3000, ...}
            for key, value in payload.items():
                if isinstance(value, dict):
                    continue
                lowered = str(key).lower()
                window = self.day if _DAY_RE.search(lowered) else self.minute if "min" in lowered else None
                if window is None:
                    continue
                num = _to_int(value)
                if num is None:
                    continue
                if "remaining" in lowered:
                    window.remaining = num
                elif "used" in lowered or "usage" in lowered:
                    if window.limit is not None:
                        window.remaining = max(0, window.limit - num)
                elif "reset" in lowered:
                    window.reset_at = float(num) if num > 10_000_000 else now + num
                else:
                    # `limit` / `max` — and the bare `perMinute` / `perDay` caps
                    # that `GET /limits` actually returns.
                    window.limit = num
            self.updated_at = now

    @staticmethod
    def _ingest_window(window: _Window, block: Mapping[str, Any], now: float) -> None:
        limit = _to_int(block.get("limit", block.get("max", block.get("cap"))))
        remaining = _to_int(block.get("remaining"))
        used = _to_int(block.get("used", block.get("usage", block.get("count"))))
        reset = _to_int(block.get("resetAt", block.get("reset", block.get("resetsAt"))))
        if limit is not None:
            window.limit = limit
        if remaining is not None:
            window.remaining = remaining
        elif used is not None and window.limit is not None:
            window.remaining = max(0, window.limit - used)
        if reset is not None:
            window.reset_at = float(reset) if reset > 10_000_000 else now + reset

    # ── Decisions ─────────────────────────────────────────────────────

    def _reserve(self, window: _Window) -> int:
        if window.limit is None:
            return 0
        return max(1, int(window.limit * RESERVE_FRACTION))

    def can_spend(self, calls: int = 1, *, background: bool = True) -> bool:
        """May we make ``calls`` more requests right now?

        Background work keeps ``RESERVE_FRACTION`` of each window for the
        user; foreground (user-initiated) work only refuses at zero.
        """
        now = self._clock()
        with self._lock:
            for window in (self.minute, self.day):
                remaining = window.remaining_now(now)
                if remaining is None:
                    continue
                floor = self._reserve(window) if background else 0
                if remaining - calls < floor:
                    return False
            return True

    def seconds_until_minute_reset(self) -> float:
        now = self._clock()
        with self._lock:
            if self.minute.reset_at is None:
                return 0.0
            return max(0.0, self.minute.reset_at - now)

    def poll_interval(self, idle_seconds: float = 0.0) -> float:
        """Seconds between background ``/inbox/unread`` ticks.

        Sized so the tick spends at most ``TICK_BUDGET_SHARE`` of the daily
        budget (and never more than that share of the per-minute budget),
        then stretched up to 4× as the user goes idle (linear over ten
        minutes). Clamped to ``[MIN_POLL_SECONDS, MAX_POLL_SECONDS]``.
        """
        with self._lock:
            day_limit = self.day.limit
            minute_limit = self.minute.limit
            day_remaining = self.day.remaining
        interval = float(DEFAULT_POLL_SECONDS)
        candidates = []
        if day_limit:
            candidates.append(86400.0 / max(1.0, day_limit * TICK_BUDGET_SHARE))
        if minute_limit:
            candidates.append(60.0 / max(1.0, minute_limit * TICK_BUDGET_SHARE))
        if candidates:
            interval = max(candidates)
        # Running low on the day → slow down proportionally (down to 4× slower).
        if day_limit and day_remaining is not None and day_limit > 0:
            fraction_left = max(0.0, min(1.0, day_remaining / float(day_limit)))
            if fraction_left < 0.5:
                interval *= 1.0 + (0.5 - fraction_left) * 6.0
        # Idle back-off: +1× per 200 s idle, capped at 4× total.
        if idle_seconds > 0:
            interval *= min(4.0, 1.0 + idle_seconds / 200.0)
        return float(max(MIN_POLL_SECONDS, min(MAX_POLL_SECONDS, interval)))

    # ── Presentation ──────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "tier":      self.tier,
                "minute":    self.minute.as_dict(),
                "day":       self.day.as_dict(),
                "updatedAt": self.updated_at,
                "callsSeen": self.calls_seen,
            }

    def summary(self) -> str:
        """Compact status-bar text, e.g. ``42/60 min · 2,801/3,000 day · DCB``."""
        now = self._clock()
        with self._lock:
            parts = []
            for label, window in (("min", self.minute), ("day", self.day)):
                remaining = window.remaining_now(now)
                if window.limit is None and remaining is None:
                    continue
                left = "?" if remaining is None else "{:,}".format(remaining)
                cap = "?" if window.limit is None else "{:,}".format(window.limit)
                parts.append("%s/%s %s" % (left, cap, label))
            if self.tier:
                parts.append(self.tier)
            return " · ".join(parts) if parts else "budget: unknown"
