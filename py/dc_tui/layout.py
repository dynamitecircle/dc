"""Responsive layout maths — pure functions, no Textual import.

The TUI never assumes a terminal size. Every screen asks
:func:`layout_mode` on mount and on every resize and adapts:

======== ============ ===========================================
mode     width (cols) what changes
======== ============ ===========================================
compact  ≤ 80         single column, condensed labels, no detail pane
single   81 – 99      single column, full labels, detail on demand (Enter)
split    100 – 139    list + detail side by side (detail ≈ 45 %)
wide     ≥ 140        list + detail, detail ≈ 55 %, sidebars allowed
======== ============ ===========================================
"""
from __future__ import annotations

from typing import Tuple

__all__ = ["COMPACT_MAX", "SPLIT_MIN", "WIDE_MIN", "MODES", "layout_mode",
           "detail_fraction", "pane_widths", "is_two_pane"]

COMPACT_MAX = 80
SPLIT_MIN = 100
WIDE_MIN = 140
MODES = ("compact", "single", "split", "wide")


def layout_mode(width: int) -> str:
    """Map a terminal width in columns to one of ``MODES``."""
    try:
        width = int(width)
    except (TypeError, ValueError):
        return "compact"
    if width <= COMPACT_MAX:
        return "compact"
    if width < SPLIT_MIN:
        return "single"
    if width < WIDE_MIN:
        return "split"
    return "wide"


def is_two_pane(width: int) -> bool:
    return layout_mode(width) in ("split", "wide")


def detail_fraction(width: int) -> float:
    """Share of the width given to the detail pane (0 when single column)."""
    mode = layout_mode(width)
    if mode == "split":
        return 0.45
    if mode == "wide":
        return 0.55
    return 0.0


def pane_widths(width: int) -> Tuple[int, int]:
    """``(list_cols, detail_cols)`` for a given terminal width."""
    try:
        width = max(0, int(width))
    except (TypeError, ValueError):
        return (0, 0)
    fraction = detail_fraction(width)
    if fraction == 0.0:
        return (width, 0)
    detail = int(round(width * fraction))
    return (width - detail, detail)
