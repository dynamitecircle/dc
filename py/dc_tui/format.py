"""Tiny formatting helpers shared by the screens (no Textual imports)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional


def trunc(text: Any, width: int) -> str:
    s = str(text or "")
    width = max(4, int(width))
    return s if len(s) <= width else s[: width - 1] + "…"


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def initials(name: str) -> str:
    parts = [p for p in str(name).split() if p]
    return "".join(p[0].upper() for p in parts[:2]) or "DC"


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / (1000 if value > 1e11 else 1))
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None


def fmt_date(value: Any) -> str:
    d = _parse(value)
    return d.strftime("%b %-d") if d else ""


def date_range(start: Any, end: Any) -> str:
    a, b = _parse(start), _parse(end)
    if not a:
        return ""
    if not b or a.date() == b.date():
        return a.strftime("%b %-d")
    if a.month == b.month:
        return f"{a.strftime('%b')} {a.day}–{b.day}"
    return f"{a.strftime('%b %-d')} – {b.strftime('%b %-d')}"


_MD_IMAGE_LINK = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)")   # [![](img)](url)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")                     # ![alt](img)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")                      # [text](url) -> text
_MD_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~|`)")


def strip_markdown(text: Any) -> str:
    """Flatten announcement/message markdown to one line of plain text.

    Drops images and image-links, keeps link text, removes emphasis markers,
    and collapses whitespace. Good enough for a one-line preview card.
    """
    s = str(text or "")
    s = _MD_IMAGE_LINK.sub("", s)
    s = _MD_IMAGE.sub("", s)
    s = _MD_LINK.sub(r"\1", s)
    s = re.sub(r"^\s{0,3}#{1,6}\s+", "", s, flags=re.MULTILINE)      # headings
    s = re.sub(r"^\s{0,3}>\s?", "", s, flags=re.MULTILINE)           # blockquotes
    s = _MD_EMPHASIS.sub("", s)
    return " ".join(s.split())
