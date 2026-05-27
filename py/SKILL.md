---
name: dc
description: Read and act on your own Dynamite Circle membership data via the public Member API — profile (read+update), trips (CRUD), events + RSVP, virtual events + RSVP, tickets, invites (send), inbox, rooms, chapters, places lookup, locator digest. Self-contained single-file Python client.
tags: dc, dynamite-circle
---

# DC Member API Skill

A self-contained Python client for the public DC Member API at
`https://api.dynamitecircle.com`. Read-only and write access to your own
membership data — your profile, trips, events, tickets, invites, inbox,
rooms, chapters, and locator digest.

Single file, stdlib-only, works the same from Claude Code, Codex, Gemini
CLI, and GitHub Copilot.

## Setup

Each member needs their own personal API key. Generate one from the DC
profile dropdown → **DC Member API Key**. Keys look like
`dk_<api-key>` and are revocable from the same dropdown.

Save it with the built-in `setup` command:

```bash
python3 py/dc.py setup --api-key dk_<api-key>
```

This writes the key to `py/.env.dc` (chmod 600). The file
is gitignored.

Verify the setup:

```bash
python3 py/dc.py self-test
```

Runs four checks: `env`, `keyShape`, `profile` (live API call), and `mcpSchemas` (every command declares an explicit `args=` schema for MCP clients). Expected output: all four green with `connected as userID[<id>] <Your Name>`.

## Endpoints

The skill wraps the public Member API. Full live reference:

**`https://www.dynamitecircle.com/developers/`**

## Pagination

Every list-returning command takes the same cursor pagination flags:

```bash
<command> [--limit N] [--cursor TOKEN]
```

- `--limit N` — page size (1-100; default varies by endpoint)
- `--cursor TOKEN` — opaque continuation token from the previous response

Responses are wrapped in the standard envelope:

```json
{
  "items":    [...],
  "count":    42,
  "cursor":   "opaque-token-or-null",
  "has_more": true
}
```

Any non-paginated extras the API returned (e.g. `totalUnread` on `inbox`)
are passed through under an `extra` key.

## Output formats

```bash
python3 dc.py profile             # text (pretty JSON)
python3 dc.py profile --json      # explicit JSON
python3 dc.py profile --python    # Python repr
python3 dc.py --format python profile
```

## Version warnings

Every API response carries an `X-API-Version` header. The skill compares
it against its own `DC_API_VERSION` constant. When the **server's major or
minor** is ahead of the skill, you'll see a one-shot warning on stderr
prompting you to update:

```
⚠  DC API has new features available (server 1.3.0, this skill built for 1.2.0).
   Update the dc client: cd <your dc clone> && git pull
```

Patch differences (e.g. server 1.2.5 vs skill 1.2.0) are silent — they're
bug fixes only. The warning fires once per process so it doesn't spam
script users.

## Local development

Override the API base URL to test against a local server (e.g. when
running the API on `localhost:8083`):

```bash
# CLI
python3 dc.py --api-url http://localhost:8083 profile

# Python
DC(api_url="http://localhost:8083")
```

## Commands

### Setup & diagnostics

```bash
# Save your DC API key to .env.dc
python3 dc.py setup --api-key dk_<api-key>

# Validate env, network, and /profile end-to-end
python3 dc.py self-test

# Machine-readable recipes — ordered {method, path} steps for common
# tasks (who's in <city>, plan together at an event, find DCers by
# description, manage inbox, refresh profile, …). Good first call for
# an unfamiliar agent.
python3 dc.py workflows
```

### Follows (DCers + chapters)

Manage your follow list — the same state the in-app **Follow** buttons
read and write. Drives the `/locator/digest` `favoritePeople` and
`favoriteCities` sections, so following someone here means their trip
+ event + ticket activity shows up in your locator digest.

Caps: **150 followed DCers + 50 followed chapters**. Hitting the cap
returns `409 follow_limit_reached` — unfollow before retrying.

```bash
# List
python3 dc.py follows-profiles
python3 dc.py follows-chapters

# Follow / unfollow a DCer
python3 dc.py follow-profile 27
python3 dc.py unfollow-profile 27

# Follow / unfollow a chapter (city hub)
python3 dc.py follow-chapter ChIJ82ENKDJgHTERIEjiXbIAAQE
python3 dc.py unfollow-chapter ChIJ82ENKDJgHTERIEjiXbIAAQE
```

All mutations idempotent. Cannot follow yourself. Target must exist
(and for profiles: be publicly visible).

### Search

Full-text search across the DC corpus — profiles, rooms, messages
(incl. your private DMs + group DMs you're a member of), events,
chapters. Privacy is scoped to your API key's owner.

```bash
# Cross-resource omni — top-5 of each, grouped by resource
python3 dc.py search "remote work"

# Scope omni to one DCer's content (profile + their messages, rooms, events, chapter memberships)
python3 dc.py search "SaaS" --user-id 940

# Search messages — includes your private DMs and group DMs
python3 dc.py search-messages "hiring in Lisbon"
python3 dc.py search-messages "budget" --room-id abc123       # scope to one room (you must be a member)
python3 dc.py search-messages "hiring" --user-id 940          # just one author's messages

# Search profiles (plain full-text; for richer matchmaking, prefer profile-match)
python3 dc.py search-profiles "SaaS founder"

# Search rooms by name / topic
python3 dc.py search-rooms "outsourcing"
python3 dc.py search-rooms "Asia" --type channel

# Search events — no default time filter, pass --since / --until to constrain
python3 dc.py search-events "DCBKK"
python3 dc.py search-events "DC" --country TH
python3 dc.py search-events "retreat" --since 2026-01-01

# Search chapters
python3 dc.py search-chapters "Bangkok"
```

**Query syntax (`q=`):** plain words match with prefix + typo
tolerance. Wrap a phrase in double quotes for an exact ordered match —
`'"remote work"'`. AND/OR/NOT/parentheses are **not** parsed in `q=` —
use the structured filter args (`--room-id`, `--user-id`, `--type`,
`--country`, `--since`, `--until`) for boolean composition.

### Profile

```bash
# Your own profile
python3 dc.py profile

# Update profile fields
python3 dc.py profile-update --headline 'CEO at Acme'

# Set your GitHub username — required to be granted access to the
# private dc repo (active DC member with GitHub username on
# profile)
python3 dc.py profile-update --github octocat

# Show your effective rate limits (per-minute, per-day) + current usage
python3 dc.py limits
```

### Announcements

Read-only access to DC's broadcast channels (DC, DCBKK, DCMEX, DC BLACK, etc.).
Same content visible in the app's announcements channels — DCC members see
DC-scope announcements; DCB / Accel / Admin members additionally see DC BLACK.

```bash
# Mixed newest-first feed across all visible channels (cursor-paginated)
python3 dc.py announcements
python3 dc.py announcements --limit 25
python3 dc.py announcements --limit 10 --cursor <token>

# Quick "what's new across DC?" — one most-recent announcement per channel
python3 dc.py announcements-latest
```

### Trips

```bash
# Upcoming trips (cursor-paginated)
python3 dc.py trips
python3 dc.py trips --limit 10 --cursor <token>

# Past trips
python3 dc.py trips --past

# Trip overlaps — DCers whose trips overlap with yours in the same city
python3 dc.py overlaps

# Create a trip — provide either --place-id (Google Place ID) OR --event-id
python3 dc.py trip-create \
  --start-date 2026-12-01 --end-date 2026-12-05 --place-id ChIJ-ZRLfIQzMBQR2bAQQ8sZh90
python3 dc.py trip-create \
  --start-date 2026-12-01 --end-date 2026-12-05 --place-id ChIJ-ZRLfIQzMBQR2bAQQ8sZh90 \
  --points '[{"note":"Coffee near the venue","noteHTML":"<p>Coffee near the venue</p>"}]'

# Or attach to a DC event (location is copied from the event's city)
python3 dc.py trip-create \
  --start-date 2026-11-01 --end-date 2026-11-05 --event-id sWnllj1DW2jLMZ1n2KWB

# Update / delete a trip
python3 dc.py trip-update <tripID> --end-date 2026-12-06
python3 dc.py trip-update <tripID> --points '[]'
python3 dc.py trip-delete <tripID>
```

### Events (in-person)

```bash
# Upcoming / past, cursor-paginated
python3 dc.py events
python3 dc.py events --past --limit 5

# Single event
python3 dc.py event <eventID>

# Attendees (cursor-paginated)
python3 dc.py event-attendees <eventID> --limit 50

# RSVP — yes | maybe | no
python3 dc.py event-rsvp <eventID> --status yes
```

#### Event extras (require an event ticket)

These endpoints return rich event-day content. They require you to hold a
valid ticket for the event — calls without a ticket return 403.

Time fields on the schedule are wall-clock ISO strings paired with the
event's IANA timezone — the digits are venue-local, NOT real UTC.
Always combine `startAt` + `timezone` together when displaying.

```bash
# Full schedule — sessions grouped by day
python3 dc.py event-schedule <eventID>

# YOUR agenda (sessions you bookmarked + meetups you joined)
python3 dc.py event-agenda <eventID>

# Approved member-organized meetups
python3 dc.py event-meetups <eventID>

# Sponsors — ordered by tier, then display order
python3 dc.py event-sponsors <eventID>

# Who else bookmarked a session?
python3 dc.py session-attendees <eventID> <sessionID>

# Who else RSVPd to a meetup?
python3 dc.py meetup-attendees <eventID> <meetupID>

# Bookmark / unbookmark a session (default: bookmark)
python3 dc.py session-bookmark <eventID> <sessionID>
python3 dc.py session-bookmark <eventID> <sessionID> --bookmarked false

# Join / leave a meetup (default: join)
python3 dc.py meetup-rsvp <eventID> <meetupID>
python3 dc.py meetup-rsvp <eventID> <meetupID> --joined false
```

### Virtual events (online sessions/calls)

```bash
# Upcoming / past
python3 dc.py virtual-events
python3 dc.py virtual-events --past

# Single session
python3 dc.py virtual-event <sessionID>

# RSVP
python3 dc.py virtual-event-rsvp <sessionID> --status maybe
```

### Tickets

```bash
# All your tickets (cursor-paginated)
python3 dc.py tickets

# Filter by status (valid|maybe|refunded|canceled)
python3 dc.py tickets --status valid
```

### Invites

```bash
# Your sent invites (cursor-paginated)
python3 dc.py invites

# Your permanent invite code
python3 dc.py permacode

# Send a new invite
python3 dc.py invite-create --email new@friend.com --full-name 'New Friend'
```

### Inbox

```bash
# Unread messages summary (rooms list + totalUnread under .extra)
python3 dc.py inbox
```

### Rooms

```bash
# Rooms you are subscribed to
python3 dc.py rooms
python3 dc.py rooms --type channel

# Browse public rooms (type required: channel|discussion|activity)
python3 dc.py browse-rooms channel
python3 dc.py browse-rooms channel --limit 20 --cursor <token>
```

### Chapters (city hubs)

```bash
# All DC chapters (cursor-paginated, sorted by member count)
python3 dc.py chapters
python3 dc.py chapters --limit 5 --cursor <token>

# Single chapter (cityID == Google Place ID) — includes up to 100 members
python3 dc.py chapter ChIJ82ENKDJgHTERIEjiXbIAAQE
```

### Places (Google Places lookup)

Helpers for resolving a Google Place ID before creating a trip.

```bash
# Search for a place by name
python3 dc.py places-search --q 'Tokyo Japan' --limit 5

# Verify a placeID
python3 dc.py place ChIJ51cu8IcbXWARiRtXIothAS4
```

### Locator

```bash
# Full weekly digest (favorites, home city, attending, who's coming where)
python3 dc.py locator

# Just one or more sections
python3 dc.py locator --sections homeCity,favoriteCities
```

## MCP server (optional)

The same file can run as an MCP server. Tools are auto-derived from the
registered commands.

```bash
pip install -r py/requirements.txt
python3 py/dc.py --mcp
```

Client config (Claude Desktop / Cursor):

```json
{
  "mcpServers": {
    "dc": {
      "command": "python3",
      "args": [".../dc/py/dc.py", "--mcp"]
    }
  }
}
```

CLI and Python-import users do not need the `mcp` package.

## Import usage

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.abspath('.'), '.claude', 'skills', 'dc'))
from dc import DC

dc = DC()

# Reads
dc.profile()
dc.trips(cursor="abc")                       # cursor-paginated
dc.events(past=True, limit=5)
dc.chapters()
dc.places_search(q="Tokyo Japan")
dc.locator(sections="homeCity,favoriteCities")

# Writes
dc.profile_update({"headline": "CEO at Acme"})
dc.trip_create(start_date="2026-12-01", end_date="2026-12-05", place_id="ChIJ-ZRLfIQzMBQR2bAQQ8sZh90")
dc.event_rsvp("<eventID>", "yes")
dc.invite_create(email="new@friend.com", full_name="New Friend")
```

## Rate limits

Member API rate limits apply:

| Tier              | Per minute | Per day |
|-------------------|------------|---------|
| DC Community      | 10         | 300     |
| DC BLACK          | 60         | 3,000   |

Headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
`X-RateLimit-Reset`, `X-RateLimit-Daily-Remaining`.
