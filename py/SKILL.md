---
name: dc
description: Read and act on your own Dynamite Circle membership data via the public Member API — profile (read+update), trips (CRUD), events + RSVP, virtual events + RSVP, tickets, invites (send), inbox, rooms, chapters, places lookup, locator digest. Self-contained single-file Python client (CLI / library / MCP), or a hosted MCP endpoint with zero install.
tags: dc, dynamite-circle
---

# DC Member API Skill

Read and act on your own Dynamite Circle membership data via the public DC
Member API at `https://api.dynamitecircle.com` — your profile, trips, events,
tickets, invites, inbox, rooms, chapters, announcements, and locator digest.
Reads and writes are always scoped to **you** (the owner of the API key).

There are two ways to use it, and **one of them needs nothing installed**:

| Path | What it is | Pick it when |
|---|---|---|
| **Local client** (this file) | One stdlib-only Python file: a CLI (`dc …`), a Python library (`from dynamitecircle import DC`), and a local stdio MCP server (`dc --mcp`) | You're an agent that can run Python or shell — you get a CLI, scriptable library calls, and a local server you can pin/run offline |
| **Hosted MCP** | A remote MCP endpoint: `https://api.dynamitecircle.com/mcp` (Streamable HTTP) | You're an MCP-capable chat app and want zero install + always-current tools (no updates to manage) |

**Rule of thumb for an agent:** if you can execute commands, prefer the local
client (richest: CLI + library + MCP, works offline, version-pinnable). If
you're a hosted assistant that only speaks MCP, use the hosted URL. Both
authenticate with the same `dk_` key.

## Install the local client

Three ways to get the client, from quickest to most isolated:

```bash
# A) PyPI — quickest. Gives you the `dc` command + the importable library.
pip install dynamitecircle            # CLI + library
pip install 'dynamitecircle[mcp]'     # + local MCP server (dc --mcp)

# B) uvx — no install, auto-updates on every run (great for an MCP config)
uvx --from 'dynamitecircle[mcp]' dc --help

# C) Clone — full repo (MCP config, docs, vendor via submodule/subtree)
git clone https://github.com/dynamitecircle/dc.git && cd dc
```

> **Command form in this doc:** examples use the installed `dc` command. From
> a clone, replace `dc` with `python3 py/dc.py` (e.g. `python3 py/dc.py profile`).

## Setup (get + save your key)

Each member needs their own personal API key. Generate one from the DC
profile dropdown → **DC Member API Key**. Keys look like `dk_<api-key>` and
are revocable from the same dropdown.

```bash
# Save it (writes .env.dc next to the client, chmod 600, gitignored)
dc setup --api-key dk_<api-key>

# Verify env, key shape, a live /profile call, and MCP schemas — all green
dc self-test
```

`self-test` should end with `connected as userID[<id>] <Your Name>`.

Alternatively, set `DC_API_KEY` in the environment instead of running `setup`
— an explicit env var always wins over `.env.dc`. This is how the hosted MCP
and ephemeral `uvx` installs receive the key (e.g. the `env` block of an MCP
server config).

## Discovering endpoints

You don't need to memorize the surface — discover it live:

```bash
# Every command + a one-line description
dc help

# Full detail for one command (flags, args, examples)
dc help trips

# Machine-readable recipes: ordered {method, path} steps for common goals
# (who's in <city>, plan together at an event, find DCers by description,
# manage inbox, refresh profile…). Best first call for an unfamiliar agent.
dc workflows
```

Authoritative references:

- **`https://www.dynamitecircle.com/developers/`** — full human reference, every endpoint/param/response, regenerated on every deploy (always current)
- **`https://api.dynamitecircle.com/openapi.json`** — the OpenAPI spec (machine-readable)
- **`https://api.dynamitecircle.com/.well-known/mcp.json`** — MCP discovery descriptor (transport, auth, install)

> **~80 commands.** That's a lot to scan, and some MCP clients cap how many
> tools they load. Don't read them all — call **`dc workflows`** first to get
> the handful of ordered recipes for common goals, then `dc help <command>`
> for the specific ones you need.

### Read vs. write (MCP annotations)

Every MCP tool is annotated: reads carry `readOnlyHint: true`; writes carry
`readOnlyHint: false` (and `destructiveHint: true` for `trip_delete`), plus a
"⚠️ Write operation" note in the description. Reads (`profile`, `trips`,
`search`, …) are safe to run freely; writes (`trip_create`, `profile_update`,
`event_rsvp`, …) mutate **your** account. Clients that honor annotations can
auto-approve reads and prompt on writes.

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
dc profile             # text (pretty JSON)
dc profile --json      # explicit JSON
dc profile --python    # Python repr
dc --format python profile
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
dc --api-url http://localhost:8083 profile

# Python
DC(api_url="http://localhost:8083")
```

## Commands

### Setup & diagnostics

```bash
# Save your DC API key to .env.dc
dc setup --api-key dk_<api-key>

# Validate env, network, and /profile end-to-end
dc self-test

# Machine-readable recipes — ordered {method, path} steps for common
# tasks (who's in <city>, plan together at an event, find DCers by
# description, manage inbox, refresh profile, …). Good first call for
# an unfamiliar agent.
dc workflows
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
dc follows-profiles
dc follows-chapters

# Follow / unfollow a DCer
dc follow-profile 27
dc unfollow-profile 27

# Follow / unfollow a chapter (city hub)
dc follow-chapter ChIJ82ENKDJgHTERIEjiXbIAAQE
dc unfollow-chapter ChIJ82ENKDJgHTERIEjiXbIAAQE
```

All mutations idempotent. Cannot follow yourself. Target must exist
(and for profiles: be publicly visible).

### Search

Full-text search across the DC corpus — profiles, rooms, messages
(incl. your private DMs + group DMs you're a member of), events,
chapters. Privacy is scoped to your API key's owner.

```bash
# Cross-resource omni — top-5 of each, grouped by resource
dc search "remote work"

# Scope omni to one DCer's content (profile + their messages, rooms, events, chapter memberships)
dc search "SaaS" --user-id 940

# Search messages — includes your private DMs and group DMs
dc search-messages "hiring in Lisbon"
dc search-messages "budget" --room-id abc123       # scope to one room (you must be a member)
dc search-messages "hiring" --user-id 940          # just one author's messages

# Search profiles (plain full-text; for richer matchmaking, prefer profile-match)
dc search-profiles "SaaS founder"

# Search rooms by name / topic
dc search-rooms "outsourcing"
dc search-rooms "Asia" --type channel

# Search events — no default time filter, pass --since / --until to constrain
dc search-events "DCBKK"
dc search-events "DC" --country TH
dc search-events "retreat" --since 2026-01-01

# Search chapters
dc search-chapters "Bangkok"
```

**Query syntax (`q=`):** plain words match with prefix + typo
tolerance. Wrap a phrase in double quotes for an exact ordered match —
`'"remote work"'`. AND/OR/NOT/parentheses are **not** parsed in `q=` —
use the structured filter args (`--room-id`, `--user-id`, `--type`,
`--country`, `--since`, `--until`) for boolean composition.

### Profile

```bash
# Your own profile
dc profile

# Update profile fields
dc profile-update --headline 'CEO at Acme'

# Set your GitHub username — required to be granted access to the
# private dc repo (active DC member with GitHub username on
# profile)
dc profile-update --github octocat

# Show your effective rate limits (per-minute, per-day) + current usage
dc limits
```

### Announcements

Read-only access to DC's broadcast channels (DC, DCBKK, DCMEX, DC BLACK, etc.).
Same content visible in the app's announcements channels — DCC members see
DC-scope announcements; DCB / Accel / Admin members additionally see DC BLACK.

```bash
# Mixed newest-first feed across all visible channels (cursor-paginated)
dc announcements
dc announcements --limit 25
dc announcements --limit 10 --cursor <token>

# Quick "what's new across DC?" — one most-recent announcement per channel
dc announcements-latest
```

### Trips

```bash
# Upcoming trips (cursor-paginated)
dc trips
dc trips --limit 10 --cursor <token>

# Past trips
dc trips --past

# Trip overlaps — DCers whose trips overlap with yours in the same city
dc overlaps

# Create a trip — provide either --place-id (Google Place ID) OR --event-id
dc trip-create \
  --start-date 2026-12-01 --end-date 2026-12-05 --place-id ChIJ-ZRLfIQzMBQR2bAQQ8sZh90
dc trip-create \
  --start-date 2026-12-01 --end-date 2026-12-05 --place-id ChIJ-ZRLfIQzMBQR2bAQQ8sZh90 \
  --points '[{"note":"Coffee near the venue","noteHTML":"<p>Coffee near the venue</p>"}]'

# Or attach to a DC event (location is copied from the event's city)
dc trip-create \
  --start-date 2026-11-01 --end-date 2026-11-05 --event-id sWnllj1DW2jLMZ1n2KWB

# Update / delete a trip
dc trip-update <tripID> --end-date 2026-12-06
dc trip-update <tripID> --points '[]'
dc trip-delete <tripID>
```

### Events (in-person)

```bash
# Upcoming / past, cursor-paginated
dc events
dc events --past --limit 5

# Single event
dc event <eventID>

# Attendees (cursor-paginated)
dc event-attendees <eventID> --limit 50

# RSVP — yes | maybe | no
dc event-rsvp <eventID> --status yes
```

#### Event extras (require an event ticket)

These endpoints return rich event-day content. They require you to hold a
valid ticket for the event — calls without a ticket return 403.

Time fields on the schedule are wall-clock ISO strings paired with the
event's IANA timezone — the digits are venue-local, NOT real UTC.
Always combine `startAt` + `timezone` together when displaying.

```bash
# Full schedule — sessions grouped by day
dc event-schedule <eventID>

# YOUR agenda (sessions you bookmarked + meetups you joined)
dc event-agenda <eventID>

# Approved member-organized meetups
dc event-meetups <eventID>

# Sponsors — ordered by tier, then display order
dc event-sponsors <eventID>

# Who else bookmarked a session?
dc session-attendees <eventID> <sessionID>

# Who else RSVPd to a meetup?
dc meetup-attendees <eventID> <meetupID>

# Bookmark / unbookmark a session (default: bookmark)
dc session-bookmark <eventID> <sessionID>
dc session-bookmark <eventID> <sessionID> --bookmarked false

# Join / leave a meetup (default: join)
dc meetup-rsvp <eventID> <meetupID>
dc meetup-rsvp <eventID> <meetupID> --joined false
```

### Virtual events (online sessions/calls)

```bash
# Upcoming / past
dc virtual-events
dc virtual-events --past

# Single session
dc virtual-event <sessionID>

# RSVP
dc virtual-event-rsvp <sessionID> --status maybe
```

### Tickets

```bash
# All your tickets (cursor-paginated)
dc tickets

# Filter by status (valid|maybe|refunded|canceled)
dc tickets --status valid
```

### Invites

```bash
# Your sent invites (cursor-paginated)
dc invites

# Your permanent invite code
dc permacode

# Send a new invite
dc invite-create --email new@friend.com --full-name 'New Friend'
```

### Inbox

```bash
# Unread messages summary (rooms list + totalUnread under .extra)
dc inbox
```

### Rooms

```bash
# Rooms you are subscribed to
dc rooms
dc rooms --type channel

# Browse public rooms (type required: channel|discussion|activity)
dc browse-rooms channel
dc browse-rooms channel --limit 20 --cursor <token>
```

### Chapters (city hubs)

```bash
# All DC chapters (cursor-paginated, sorted by member count)
dc chapters
dc chapters --limit 5 --cursor <token>

# Single chapter (cityID == Google Place ID) — includes up to 100 members
dc chapter ChIJ82ENKDJgHTERIEjiXbIAAQE
```

### Places (Google Places lookup)

Helpers for resolving a Google Place ID before creating a trip.

```bash
# Search for a place by name
dc places-search --q 'Tokyo Japan' --limit 5

# Verify a placeID
dc place ChIJ51cu8IcbXWARiRtXIothAS4
```

### Locator

```bash
# Full weekly digest (favorites, home city, attending, who's coming where)
dc locator

# Just one or more sections
dc locator --sections homeCity,favoriteCities
```

## MCP server

Two ways to expose these commands as MCP tools — pick one:

**Hosted (no install, always current):** point your client at
`https://api.dynamitecircle.com/mcp` (Streamable HTTP; OAuth or `dk_` Bearer).
For Claude Code: `claude mcp add --transport http dc https://api.dynamitecircle.com/mcp`.

**Local stdio server** (offline-capable, version-pinnable). Tools are
auto-derived from the registered commands; CLI and library users don't need
the `mcp` package.

```bash
pip install 'dynamitecircle[mcp]' && dc --mcp     # installed
python3 py/dc.py --mcp                             # from a clone
```

Auto-updating local config (no clone; pulls latest on every launch):

```json
{
  "mcpServers": {
    "dc": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--refresh", "--from", "dynamitecircle[mcp]", "dc", "--mcp"],
      "env": { "DC_API_KEY": "dk_<api-key>" }
    }
  }
}
```

Static path config (Claude Desktop / Cursor, from a clone):

```json
{
  "mcpServers": {
    "dc": {
      "command": "python3",
      "args": ["/absolute/path/to/dc/py/dc.py", "--mcp"]
    }
  }
}
```

Full per-client setup: [docs/mcp-info.md](../docs/mcp-info.md).

## Import usage

```python
# Installed from PyPI — import by package name:
from dynamitecircle import DC
# From a clone instead:  import sys; sys.path.insert(0, "py"); from dc import DC

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
