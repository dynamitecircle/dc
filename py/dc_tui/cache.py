"""Disk cache for Member API reads — sealed files under ``~/.cache/dc/``.

The Member API has no push transport and tight per-key budgets (DCC
10/min · 300/day, DCB 60/min · 3,000/day), so the TUI never hits the
network for something it fetched a moment ago. Each logical read is keyed
by the ``dc`` command name plus its arguments; every command has a TTL
(``DEFAULT_TTLS``) after which the entry is *stale* but still returned, so
screens can render instantly and refresh in the background
(stale-while-revalidate). When the rate budget is exhausted, stale data is
what keeps the UI usable.

Entries are member data, so they are not stored as plain text: each file is
zlib-compressed JSON, encrypted with a keystream from keyed BLAKE2b in counter
mode and authenticated with a keyed BLAKE2b tag. The key is derived from the
member's API key (``secret``) — without it the files are unreadable, and a
changed key or a tampered file reads as a cache miss. It keeps the cache from
being casually readable; it is not a vault (anyone with the API key can read it).

Pure stdlib, no Textual import — unit-tested offline.
"""
from __future__ import annotations

import hashlib
import json
import os
import zlib
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

__all__ = ["DiskCache", "Entry", "DEFAULT_TTLS", "DEFAULT_TTL", "cache_dir"]

#: Seconds each command's result stays *fresh*. Anything not listed uses
#: ``DEFAULT_TTL``. Tuned for "a dashboard glance", not real-time chat.
DEFAULT_TTLS: Dict[str, int] = {
    # Me
    "profile":              3600,
    "membership":           3600,
    "limits":                 60,
    "notifications":         600,
    "alerts":                600,
    "interests":             600,
    "calendar":              600,
    "locator-settings":      600,
    # Home
    "inbox":                  60,
    "announcements":         300,
    "announcements-latest":  300,
    "locator":              1800,
    "tickets":               900,
    # Trips
    "trips":                 300,
    "trip":                  300,
    "trip-discovery":        900,
    "overlaps":              600,
    # Events
    "events":                600,
    "event":                 600,
    "event-schedule":        900,
    "event-agenda":          120,
    "event-agendas":         120,
    "event-meetups":         300,
    "event-attendees":       600,
    "event-sponsors":       3600,
    "virtual-events":        600,
    "virtual-event":         600,
    "virtual-event-attendees": 600,
    # Rooms
    "rooms":                 120,
    "browse-rooms":          600,
    "room":                  300,
    "room-messages":          60,
    "room-summary":         1800,
    "room-summaries":       1800,
    # People
    "follows-profiles":      600,
    "follows-chapters":      600,
    "chapters":             3600,
    "chapter":              1800,
    "search":                120,
    "search-profiles":       120,
    "profile-match":         600,
    "places-search":        3600,
    "place":                3600,
}
DEFAULT_TTL = 300


def cache_dir() -> Path:
    """``$XDG_CACHE_HOME/dc`` or ``~/.cache/dc`` (``DC_CACHE_DIR`` overrides)."""
    override = os.environ.get("DC_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "dc"


_MAGIC = b"DCC1"
_SUFFIX = ".bin"


def _keys(secret: str) -> "tuple[bytes, bytes]":
    root = hashlib.sha256(("dc-tui-cache\0" + (secret or "")).encode("utf-8")).digest()
    return (hashlib.blake2b(b"enc", key=root, digest_size=32).digest(),
            hashlib.blake2b(b"mac", key=root, digest_size=32).digest())


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    for counter in range((length + 63) // 64):
        blocks.append(hashlib.blake2b(nonce + counter.to_bytes(8, "big"), key=key, digest_size=64).digest())
    return b"".join(blocks)[:length]


def _xor(data: bytes, stream: bytes) -> bytes:
    n = len(data)
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(n, "big") if n else b""


def seal(doc: Any, secret: str) -> bytes:
    """``doc`` → MAGIC · nonce · tag · ciphertext."""
    enc, mac = _keys(secret)
    plain = zlib.compress(json.dumps(doc, ensure_ascii=False, default=str).encode("utf-8"), 6)
    nonce = os.urandom(16)
    body = _xor(plain, _keystream(enc, nonce, len(plain)))
    tag = hashlib.blake2b(nonce + body, key=mac, digest_size=16).digest()
    return _MAGIC + nonce + tag + body


def unseal(blob: bytes, secret: str) -> Any:
    """Inverse of :func:`seal`; ``ValueError`` when the key is wrong or the file was changed."""
    if len(blob) < 36 or blob[:4] != _MAGIC:
        raise ValueError("not a cache file")
    nonce, tag, body = blob[4:20], blob[20:36], blob[36:]
    enc, mac = _keys(secret)
    if not hmac_equal(hashlib.blake2b(nonce + body, key=mac, digest_size=16).digest(), tag):
        raise ValueError("cache file failed its check")
    return json.loads(zlib.decompress(_xor(body, _keystream(enc, nonce, len(body)))).decode("utf-8"))


def hmac_equal(a: bytes, b: bytes) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


class Entry:
    """One cached result plus its bookkeeping."""

    __slots__ = ("key", "command", "data", "stored_at")

    def __init__(self, key: str, command: str, data: Any, stored_at: float):
        self.key = key
        self.command = command
        self.data = data
        self.stored_at = stored_at

    def age(self, now: Optional[float] = None) -> float:
        return max(0.0, (time.time() if now is None else now) - self.stored_at)

    def is_fresh(self, ttl: float, now: Optional[float] = None) -> bool:
        return self.age(now) < ttl

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Entry(command=%r, age=%.0fs)" % (self.command, self.age())


class DiskCache:
    """Thread-safe JSON file cache with per-command TTLs.

    Every I/O error degrades to an in-memory dict so a read-only or missing
    cache directory never breaks the UI — the data is only a convenience.
    """

    def __init__(self, root: Optional[Path] = None, ttls: Optional[Dict[str, int]] = None,
                 clock: Callable[[], float] = time.time, secret: str = ""):
        self.root = Path(root) if root is not None else cache_dir()
        self._secret = secret
        self.ttls: Dict[str, int] = dict(DEFAULT_TTLS)
        if ttls:
            self.ttls.update(ttls)
        self._clock = clock
        self._lock = threading.RLock()
        self._memory: Dict[str, Entry] = {}
        self._disk_ok = True
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.root, 0o700)  # member data — keep it private
            except OSError:
                pass
        except OSError:
            self._disk_ok = False
        if self._disk_ok:                       # earlier versions wrote plain JSON — remove it
            try:
                for old in self.root.glob("*.json"):
                    old.unlink()
            except OSError:
                pass

    # ── Keys / TTLs ───────────────────────────────────────────────────

    @staticmethod
    def key(command: str, *args: Any, **kwargs: Any) -> str:
        """Stable key for ``command(*args, **kwargs)`` — safe as a filename."""
        payload = json.dumps(
            {"c": command, "a": list(args), "k": {k: kwargs[k] for k in sorted(kwargs) if kwargs[k] is not None}},
            sort_keys=True, default=str, ensure_ascii=False,
        )
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
        slug = "".join(ch if ch.isalnum() or ch == "-" else "_" for ch in command)[:40]
        return "%s.%s" % (slug, digest)

    def ttl_for(self, command: str) -> int:
        return int(self.ttls.get(command, DEFAULT_TTL))

    # ── Read / write ──────────────────────────────────────────────────

    def _path(self, key: str) -> Path:
        return self.root / (key + _SUFFIX)

    def get(self, key: str) -> Optional[Entry]:
        """Return the entry (fresh *or* stale) or ``None`` when absent."""
        with self._lock:
            entry = self._memory.get(key)
            if entry is not None:
                return entry
            if not self._disk_ok:
                return None
            path = self._path(key)
            try:
                raw = path.read_bytes()
            except OSError:
                return None
            try:
                doc = unseal(raw, self._secret)
                entry = Entry(key, str(doc.get("command", "")), doc.get("data"), float(doc.get("storedAt", 0)))
            except (ValueError, TypeError, AttributeError, zlib.error):
                # Corrupt, tampered or sealed with another key — drop it rather than fail forever.
                try:
                    path.unlink()
                except OSError:
                    pass
                return None
            self._memory[key] = entry
            return entry

    def get_fresh(self, key: str, command: str) -> Optional[Entry]:
        """Return the entry only when still within the command's TTL."""
        entry = self.get(key)
        if entry is not None and entry.is_fresh(self.ttl_for(command), self._clock()):
            return entry
        return None

    def set(self, key: str, command: str, data: Any) -> Entry:
        entry = Entry(key, command, data, self._clock())
        with self._lock:
            self._memory[key] = entry
            if self._disk_ok:
                doc = {"command": command, "storedAt": entry.stored_at, "data": data}
                path = self._path(key)
                tmp = path.with_suffix(_SUFFIX + ".tmp")
                try:
                    tmp.write_bytes(seal(doc, self._secret))
                    try:
                        os.chmod(tmp, 0o600)
                    except OSError:
                        pass
                    tmp.replace(path)
                except (OSError, TypeError, ValueError):
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
        return entry

    # ── Invalidation ──────────────────────────────────────────────────

    def invalidate(self, commands: Iterable[str]) -> int:
        """Drop every entry whose command is in ``commands``. Returns count."""
        wanted = set(commands)
        dropped = 0
        with self._lock:
            for key in [k for k, e in self._memory.items() if e.command in wanted]:
                del self._memory[key]
                dropped += 1
            if self._disk_ok:
                for path in self._iter_files():
                    slug = path.name.rsplit(".", 2)[0]
                    if slug in wanted or slug.replace("_", "-") in wanted:
                        try:
                            path.unlink()
                            dropped += 1
                        except OSError:
                            pass
        return dropped

    def clear(self) -> None:
        with self._lock:
            self._memory.clear()
            if self._disk_ok:
                for path in self._iter_files():
                    try:
                        path.unlink()
                    except OSError:
                        pass

    def _iter_files(self):
        try:
            return [p for p in self.root.iterdir() if p.suffix == _SUFFIX]
        except OSError:
            return []
