"""Tiny formatting helpers shared by the screens (no Textual imports)."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Optional


def cell_width(ch: str) -> int:
    """Terminal columns one character takes (wide/fullwidth and most emoji = 2)."""
    if ch in ("\u200d", "\ufe0f") or unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    o = ord(ch)
    if 0x1F300 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or 0x1F900 <= o <= 0x1F9FF:
        return 2
    return 1


def display_width(text: Any) -> int:
    return sum(cell_width(ch) for ch in str(text or ""))


def trunc(text: Any, width: int) -> str:
    """Truncate to `width` terminal columns (not characters) with an ellipsis."""
    s = str(text or "")
    width = max(4, int(width))
    if display_width(s) <= width:
        return s
    out, used = [], 0
    for ch in s:
        w = cell_width(ch)
        if used + w > width - 1:
            break
        out.append(ch)
        used += w
    return "".join(out).rstrip() + "…"


def pad(text: Any, width: int) -> str:
    """Left-align to `width` columns (cell-aware ljust)."""
    s = trunc(text, width)
    return s + " " * max(0, width - display_width(s))


def rpad(text: Any, width: int) -> str:
    """Right-align to `width` columns (cell-aware rjust)."""
    s = trunc(text, width)
    return " " * max(0, width - display_width(s)) + s


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
    """`Sep 28` / `Oct  6` — month first, day space-padded to 2, so a column of
    dates keeps the month aligned and the day digits under each other."""
    d = _parse(value)
    return "%s %2d" % (d.strftime("%b"), d.day) if d else ""


def date_range(start: Any, end: Any) -> str:
    """`Oct 22–25`, `Mar  2–4`, `Sep 30 – Oct  2` — same fixed-width lead as fmt_date."""
    a, b = _parse(start), _parse(end)
    if not a:
        return ""
    if not b or a.date() == b.date():
        return fmt_date(a)
    if a.month == b.month and a.year == b.year:
        return "%s–%d" % (fmt_date(a), b.day)
    return "%s – %s" % (fmt_date(a), fmt_date(b))


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
