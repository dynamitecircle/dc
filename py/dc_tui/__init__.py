"""`dc tui` — the Dynamite Circle terminal app.

Ships in the `dynamitecircle` wheel next to the single-file client; Textual is
the `[tui]` extra. `dc.py` calls `run(DC, argv)` after a lazy import, so the
stdlib-only CLI never pays for this package unless you launch it.

Python 3.9 compatible: `from __future__ import annotations` everywhere, no
`match`, no runtime `X | Y` unions, no 3.10+ stdlib.
"""
from __future__ import annotations

import os
import re
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
        print("usage: dc tui [section] [--clear-cache] [--api-url URL]\n\n"
              "  Interactive terminal app for your DC membership.\n"
              "  section: home | rooms | browse | events | locator | trips | following | newtrips | people | search | me\n"
              "  Keys: 1-8 sections · / palette · r refresh · o open in browser · ? help · q quit\n"
              "  --clear-cache   drop the on-disk response cache before starting\n"
              "  --api-url URL   talk to another Member API (e.g. a local dev server); also DC_API_URL")
        return 0

    from .app import DCApp
    from .cache import DiskCache, cache_dir
    from .data import DataClient

    api_url = os.environ.get("DC_API_URL") or ""
    if "--api-url" in argv:
        i = argv.index("--api-url")
        api_url = argv[i + 1] if i + 1 < len(argv) else ""
        del argv[i:i + 2]

    if "--clear-cache" in argv:
        clear_cache()

    _tmux_flags()

    if api_url:
        client = (dc if isinstance(dc, type) else type(dc))(api_url=api_url)
        # a separate cache per API host, so dev and production data never mix
        host = re.sub(r"[^A-Za-z0-9]+", "-", api_url.split("//", 1)[-1]).strip("-")
        data = DataClient(client, cache=DiskCache(cache_dir() / ("api-" + host)))
        print("dc tui → %s" % api_url, file=sys.stderr)
    else:
        client = dc() if isinstance(dc, type) else dc
        data = None
    app = DCApp(client, argv=[a for a in argv if not a.startswith("--")], data=data)
    app.run()
    return 0


#: tmux keeps its own width table. Unless it counts a flag's regional-indicator
#: letters as wide, it positions them one by one in a pane that does not start at
#: the left edge, and the terminal draws a gray box instead of the flag (and the
#: row loses a column). One entry fixes it for every pane of that tmux server.
_TMUX_RI_WIDTHS = "U+1F1E6-U+1F1FF=2"


def _tmux_flags() -> None:
    """Inside tmux: teach the server that flags are two columns wide, then use real
    flags. If that fails (old tmux, no permission) flags fall back to country codes.
    DC_TUI_FLAGS=0/1 skips this and forces the choice."""
    import subprocess
    if not os.environ.get("TMUX") or os.environ.get("DC_TUI_FLAGS") is not None:
        return
    try:
        current = subprocess.run(["tmux", "show-options", "-sv", "codepoint-widths"],
                                 capture_output=True, text=True, timeout=3)
        if current.returncode != 0:
            return
        if "1F1E6" not in current.stdout.upper():
            added = subprocess.run(["tmux", "set-option", "-as", "codepoint-widths", _TMUX_RI_WIDTHS],
                                   capture_output=True, text=True, timeout=3)
            if added.returncode != 0:
                return
        os.environ["DC_TUI_FLAGS"] = "1"
    except (OSError, subprocess.SubprocessError):
        return


def clear_cache() -> None:
    """`--clear-cache`: drop the on-disk response cache (stdlib only)."""
    from .cache import DiskCache
    DiskCache().clear()
    print("cleared the dc tui response cache", file=sys.stderr)
