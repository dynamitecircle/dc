"""Tiny formatting helpers shared by the screens (no Textual imports)."""
from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from typing import Any, Optional


try:  # Textual lays out with Rich's cell widths — measure the same way or columns drift
    from rich.cells import cell_len as _rich_cell_len
except ImportError:  # pragma: no cover — rich ships with textual
    _rich_cell_len = None


def cell_width(ch: str) -> int:
    """Terminal columns one character takes, as Rich (and so Textual) counts it:
    wide/fullwidth and emoji-presentation characters are 2, text-presentation
    symbols such as ★ ✈ 🎟 are 1."""
    if _rich_cell_len is not None:
        return _rich_cell_len(ch)
    if ch in ("\u200d", "\ufe0f") or unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    o = ord(ch)
    if 0x1F300 <= o <= 0x1FAFF:
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


NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def say_count(n: int) -> str:
    """The web's `sayCount` (shared/util/str.ts): 0–10 as words, 11+ as digits."""
    return NUMBER_WORDS[n] if isinstance(n, int) and 0 <= n <= 10 else str(n)


def say_count_title(n: int) -> str:
    """`SayCount`: same, first letter upper-cased — used by every Locator title."""
    word = say_count(n)
    return word[:1].upper() + word[1:]


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
    """`06 Oct 2026` — zero-padded day, month, year: every date is the same
    shape, so a right-aligned column lines up digit for digit."""
    d = _parse(value)
    return "%02d %s %d" % (d.day, d.strftime("%b"), d.year) if d else ""


def date_range(start: Any, end: Any) -> str:
    """`21–24 Oct 2026` · `30 Sep – 02 Oct 2026` · `21 Dec 2026 – 06 Jan 2027`."""
    a, b = _parse(start), _parse(end)
    if a and b and a > b:
        a, b = b, a                      # reversed endpoints, like formatDates
    if not a:
        return fmt_date(b) if b else ""
    if not b or a.date() == b.date():
        return fmt_date(a)
    if a.year == b.year and a.month == b.month:
        return "%02d–%02d %s %d" % (a.day, b.day, a.strftime("%b"), a.year)
    if a.year == b.year:
        return "%02d %s – %02d %s %d" % (a.day, a.strftime("%b"), b.day, b.strftime("%b"), a.year)
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


_LI = re.compile(r"<li\b[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_BLOCK_END = re.compile(r"</(p|div|h[1-6])>|<br\s*/?>", re.IGNORECASE)


def html_to_text(value: Any) -> str:
    """Profile/room fields stored as editor HTML → one plain line: list items become
    "a, b, c", paragraphs and line breaks a space, links keep their text, entities decode."""
    text = str(value if value is not None else "")
    if "<" not in text and "&" not in text:
        return " ".join(text.split())
    items = [_TAG.sub("", m) for m in _LI.findall(text)]
    if items:
        rest = _TAG.sub(" ", _LI.sub("", text))
        parts = [html.unescape(" ".join(i.split())) for i in items if i.strip()]
        lead = html.unescape(" ".join(rest.split()))
        return (lead + " " if lead else "") + ", ".join(parts)
    text = _BLOCK_END.sub(" ", text)
    return html.unescape(" ".join(_TAG.sub("", text).split()))


def term_text(text: Any) -> str:
    """Drop the emoji variation selector (U+FE0F). Rich measures "🗺️" as one cell
    but terminals draw it as two, which pushes the row into a wrap; without the
    selector both agree."""
    return str(text if text is not None else "").replace("\ufe0f", "")


def align_row(width: int, name: Any, date: Any = "", extra: Any = "", *, prefix: str = "",
              name_min: int = 10, extra_min: int = 8, name_markup: str = "[b]%s[/b]") -> str:
    """One list row that always fits `width` columns and never wraps:

        <prefix><name……………>  <extra (optional)>  <date, right-aligned last>

    The name flexes; `extra` (a place, a note) is shown only when at least
    `extra_min` columns remain for it after the name keeps `name_min`; the date
    keeps its full width. Brackets in the texts are escaped for markup.
    """
    def esc(t: Any) -> str:
        return str(t if t is not None else "").replace("[", r"\[")
    name, date, extra = term_text(name), term_text(date), term_text(extra)
    width = max(12, int(width))
    date = str(date or "")
    extra = str(extra or "")
    # the date is right-aligned at the very end; days are zero-padded so a column
    # of dates lines up digit for digit
    date_w = display_width(date)
    avail = width - display_width(prefix) - (date_w + 1 if date else 0)
    name_w = max(4, min(display_width(name), max(name_min, avail)))
    name_w = min(name_w, max(4, avail))
    extra_w = 0
    if extra:
        room = avail - name_w - 1
        if room >= extra_min:                     # extras only when the name keeps its width
            extra_w = min(display_width(extra), room)
    parts = [prefix, name_markup % esc(pad(name, name_w))]
    used = display_width(prefix) + name_w
    if extra_w:
        parts.append(" " + esc(pad(extra, extra_w)))
        used += extra_w + 1
    if date:
        parts.append(" " * max(1, width - used - date_w) + date)
    return guard_flags("".join(parts))


def flag(country_code: Any) -> str:
    """🇯🇵 from `JP` — the two regional-indicator letters; empty when unknown."""
    code = str(country_code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code)


def event_dates(event: dict) -> str:
    """Event dates the way dc-web shows them (`formatDates(dates, false, !isDateConfirmed)`):
    confirmed → the range; not yet confirmed → month + year only, e.g. `Jul 2027`."""
    start, end = event.get("startDate") or event.get("startAt"), event.get("endDate") or event.get("endAt")
    if event.get("isDateConfirmed") is False:
        d = _parse(start) or _parse(end)
        return d.strftime("%b %Y") if d else ""
    return date_range(start, end)


_FLAG_PAIR = re.compile("([\U0001F1E6-\U0001F1FF]{2})")


def guard_flags(markup: str) -> str:
    """Wrap every flag pair in a default-foreground span. Ghostty draws a flag
    as a box when an explicit RGB foreground precedes it; with `ESC[39m` it
    renders. Widths are unaffected (markup is not counted by the terminal)."""
    return _FLAG_PAIR.sub(r"[default]\1[/default]", markup)
