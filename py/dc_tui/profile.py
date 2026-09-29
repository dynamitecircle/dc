"""One profile renderer for People and Me — the web's `ProfileCore.vue` field
order and labels: Location → DC Events → Primary Business → About Me."""
from __future__ import annotations

from typing import Any, List

from .format import flag, fmt_date, trunc


def _esc(t: Any) -> str:
    return str(t if t is not None else "").replace("[", r"\[")


def _val(v: Any) -> str:
    if isinstance(v, dict):
        fl = flag(v.get("countryCode"))
        name = v.get("cityName") or v.get("name") or v.get("city") or ""
        return ("%s %s" % (fl, name)).strip() if name else ""
    if isinstance(v, list):
        return ", ".join(_val(x) for x in v if _val(x))
    return " ".join(str(v).split()) if v not in (None, "", [], {}) else ""


SECTIONS = [
    ("Location", [("Home Chapter", "chapter"), ("Current Location", "currentLocation"), ("Relevant Locations", "relevantLocations")]),
    ("Primary Business", [("Business Name", "businessName"), ("Business Description", "businessDescription"), ("Website", "businessWebsite"),
                          ("Industry", "businessIndustry"), ("Started In", "yearsInBusiness"), ("Team Size", "teamSize"),
                          ("Business Annual Revenue", "annualRevenue"), ("Current Challenge or Business Goal", "currentChallenge")]),
    ("Other Business", [("Other Businesses", "otherBusinesses"), ("Previous Businesses", "previousBusinesses"), ("Business Partner", "businessPartnerName")]),
    ("About Me", [("Would like to connect with", "peopleOfInterest"), ("Fields Of Expertise", "expertise"),
                  ("Ask Me Anything About", "askMeAnythingTopics"), ("Non-Business Hobbies", "hobbies")]),
]


def profile_lines(p: dict, *, width: int = 80, header: bool = True) -> List[str]:
    lines: List[str] = []
    if header:
        name = p.get("displayName") or p.get("userName") or "DCer"
        nick = (" “%s”" % p.get("nickname")) if p.get("nickname") else ""
        lines.append("[b]%s[/b]%s  [dim]@%s[/dim]" % (_esc(name), _esc(nick), _esc(p.get("userName") or "")))
        if p.get("headline"):
            lines.append(_esc(trunc(_val(p.get("headline")), width)))
        if p.get("joinedDate"):
            lines.append("[dim]Joined DC %s[/dim]" % fmt_date(p.get("joinedDate")))
    for title, fields in SECTIONS:
        rows = [(label, _val(p.get(key))) for label, key in fields]
        rows = [(l, v) for l, v in rows if v]
        if not rows:
            continue
        lines.append("")
        lines.append("[b]%s[/b]" % title)
        for label, value in rows:
            lines.append("[dim]%s:[/dim] %s" % (label, _esc(trunc(value, max(20, width * 3)))))
    return lines
