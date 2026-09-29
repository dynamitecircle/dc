"""`dc tui` — the Dynamite Circle terminal app.

Ships in the `dynamitecircle` wheel next to the single-file client; Textual is
the `[tui]` extra. `dc.py` calls `run(DC, argv)` after a lazy import, so the
stdlib-only CLI never pays for this package unless you launch it.

Python 3.9 compatible: `from __future__ import annotations` everywhere, no
`match`, no runtime `X | Y` unions, no 3.10+ stdlib.
"""
from __future__ import annotations

import sys
from typing import Any, Optional, Sequence

__all__ = ["run", "TUI_VERSION"]

TUI_VERSION = "0.1.0"

_MIN_PY = (3, 9)


def run(dc: Any, argv: Optional[Sequence[str]] = None) -> int:
    """Entry point used by `dc.py` (`DC.run_tui`). Accepts a `DC` instance or
    the class itself. Returns a process exit code."""
    if sys.version_info < _MIN_PY:
        print(f"dc tui needs Python {_MIN_PY[0]}.{_MIN_PY[1]}+ (you have "
              f"{sys.version_info[0]}.{sys.version_info[1]}).", file=sys.stderr)
        return 1
    try:
        import textual  # noqa: F401  — the [tui] extra
    except ImportError:
        print("dc tui needs Textual. Run: pip install 'dynamitecircle[tui]'", file=sys.stderr)
        return 1

    argv = list(argv or [])
    if "--help" in argv or "-h" in argv:
        print("usage: dc tui [section] [--clear-cache]\n\n"
              "  Interactive terminal app for your DC membership.\n"
              "  section: home | rooms | browse | trips | events | locator | people | search | me\n"
              "  Keys: 1-7 sections · / palette · r refresh · o open in browser · ? help · q quit\n"
              "  --clear-cache   drop the on-disk response cache before starting")
        return 0

    from .app import DCApp

    if "--clear-cache" in argv:
        clear_cache()

    client = dc() if isinstance(dc, type) else dc
    app = DCApp(client, argv=[a for a in argv if not a.startswith("--")])
    app.run()
    return 0


def clear_cache() -> None:
    """`--clear-cache`: drop the on-disk response cache (stdlib only)."""
    from .cache import DiskCache
    DiskCache().clear()
    print("cleared the dc tui response cache", file=sys.stderr)
