"""The DC look — the web app's Tailwind palette (`dc-orange`, `dc-grey`,
`dc-mint`, `dc-gold`) mapped onto a Textual theme. Dark by default: the
terminal is DC's night mode.
"""
from __future__ import annotations

from textual.theme import Theme

# tailwind.config.cjs in the DC web client
ORANGE = "#FF4921"        # dc-orange 600 (DEFAULT)
ORANGE_LIGHT = "#FF8C5C"  # dc-orange 400
ORANGE_DARK = "#E52F07"   # dc-orange 700
GREY_950 = "#0B0C0E"
GREY_900 = "#17181C"
GREY_800 = "#25262B"
GREY_700 = "#30333D"
GREY_600 = "#3D3F47"
GREY_400 = "#777A88"
GREY_300 = "#ADAFB8"
GREY_100 = "#F1F2F3"
MINT = "#80B088"          # dc-mint 600
MINT_DARK = "#4D7D55"     # dc-mint 800 — hover background, white text stays readable
GOLD = "#EDB34A"          # dc-gold 600
HIGHLIGHT = "#FFB000"     # the one highlight colour: cursor row, focused button, focused tab

DC_THEME = Theme(
    name="dc",
    primary=ORANGE,
    secondary=ORANGE_LIGHT,
    accent=ORANGE,
    warning=GOLD,
    error=ORANGE_DARK,
    success=MINT,
    foreground=GREY_100,
    background=GREY_900,
    surface=GREY_800,
    panel=GREY_700,
    dark=True,
    variables={
        "block-cursor-background": HIGHLIGHT,
        "block-cursor-foreground": GREY_900,
        "block-cursor-text-style": "bold",
        # an unfocused list keeps its place in gray, never a second colour
        "block-cursor-blurred-background": GREY_700,
        "block-cursor-blurred-foreground": GREY_100,
        "block-hover-background": GREY_900,
        "footer-key-foreground": ORANGE,
        "footer-description-foreground": GREY_300,
        "border": GREY_600,
        "border-blurred": GREY_700,
        "text-muted": GREY_400,
        "dc-muted": GREY_400,
        "dc-dim": GREY_300,
    },
)
