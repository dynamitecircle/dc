# Changelog

All notable changes to the **`dc` client repo** (formerly `dc-official` /
`dc-py`) are listed here. The version
numbers below track `DC_API_VERSION` in [`py/dc.py`](py/dc.py), which is
deliberately aligned with the DC Member API contract version it was last
verified against. Python, TypeScript, and the API contract are released
together on purpose. Patch bumps from the API are silent; minor or major bumps
surface a one-shot stderr warning when an installed client falls behind.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/) for
the public Python API surface (`dc.DC`, `dc.DCError`, `dc.Result`,
`dc.Runtime`).

---

## [Unreleased]

### Added

- TypeScript npm library scaffold under `ts/`, published as
  `@dynamitecircle/dc`, with a hand-written SDK surface for every pinned
  Member API operation. It is a library only: no CLI and no MCP server.
- Pinned OpenAPI contract under `contracts/` plus an explicit operation map
  that validates API operation → Python command → TypeScript method parity.

## [2.0.4] – 2026-06-16

### Added

- **MCP tool annotations** — every tool now advertises `readOnlyHint` /
  `destructiveHint` / `openWorldHint`, so clients can auto-approve reads and
  flag writes. The read/write split is derived from each command's actual HTTP
  verb and guarded by a test that re-derives it from source (no silent drift).
  Write tools also carry a "⚠️ Write operation" note in their description,
  mirroring the hosted MCP server.
- **Structured tool output** — object results (the list envelope
  `{items, count, cursor, has_more}` and single records) are also returned as
  MCP `structuredContent`, so structure-aware clients don't have to re-parse
  the text. No `outputSchema` is declared (it would strictly validate every
  response shape); lists/scalars remain text-only.

### Changed

- **BREAKING (MCP interface) — tool names and fields are now snake_case.**
  MCP tool names switched from kebab-case to snake_case
  (`mcp__dc__trip-create` → `mcp__dc__trip_create`), and tool argument fields
  likewise (`event-id` → `event_id`, `start-date` → `start_date`). This aligns
  the agent-facing MCP surface with the snake_case Python library
  (`dc.trip_create()`) and the prevailing MCP tool-naming convention. The
  **CLI is unchanged** (`dc trip-create`, `--start-date`). Wildcard allow-rules
  like `mcp__dc__*` are unaffected; any config pinning a specific kebab tool
  name must update it. `_call_tool` still accepts the legacy kebab form as a
  transitional fallback.

### Docs / packaging

- Document the hosted MCP (`https://api.dynamitecircle.com/mcp`) and an
  auto-updating `uvx` PyPI config; fix the `.venv/bin/python3` configs to bare
  `python3`; unify `py/SKILL.md` (local client + hosted MCP) and add
  `DC/SKILL.md`; add `tests/test_version_sync.py` guarding manifest/config
  drift from `DC_API_VERSION`.
- **One-click install** — "Add to Cursor" and "Install in VS Code" badges for
  the hosted MCP, a native VS Code section (`.vscode/mcp.json` + `code --add-mcp`),
  and a `workflows`-first note for the ~80-tool surface.
- **`.mcpb` bundle** — the release workflow now builds a `dc.mcpb` (one-click
  Claude Desktop install) via `mcpb pack` and attaches it to the GitHub release;
  `.mcpbignore` keeps the bundle lean.
- **Official MCP Registry** — add `server.json` (`io.github.dynamitecircle/dc`,
  listing the hosted streamable-HTTP endpoint) and a separate, isolated
  `publish-mcp.yml` workflow that publishes it via GitHub OIDC on `v*` tags.
  The registry feeds VS Code, Smithery, PulseMCP, and others. `server.json`
  version is guarded by `tests/test_version_sync.py`.

## [2.0.1] – 2026-06-16

### Changed

- **BREAKING — formal field names, no aliases, no back-compat.** Renamed to
  match the Member API v2 rename:
  - Profile: `bizDesc`→`businessDescription`, `bizName`→`businessName`,
    `bizWeb`→`businessWebsite`, `bizIndustry`→`businessIndustry`,
    `bizRevenue`→`annualRevenue` (+`annualRevenueIsPrivate`), `bizTeam`→`teamSize`
    (+`teamSizeIsPrivate`), `bizOther`→`otherBusinesses`,
    `bizPast`→`previousBusinesses`, `yearsInBiz`→`yearsInBusiness`,
    `ama`→`askMeAnythingTopics`, `connect`→`peopleOfInterest`
    (+`peopleOfInterestIsPrivate`), `locs`→`relevantLocations`,
    `goal`→`currentChallenge`, `whatsapp`→`whatsApp`.
  - Matchmaker: `industry`→`businessIndustry`, `minRevenue`→`minAnnualRevenue`,
    `noRerank`→`skipReranking`.
  - Event free-slots: `minDurationMins`→`minDurationMinutes`,
    `withinDayDate`→`eventDayDate` (response `durationMins`→`durationMinutes`).
- **Removed the legacy field aliases** (`businessDescription`→`bizDesc`, etc.) —
  the server now accepts the formal names natively.

### Added

- Property **discoverability**: an unknown field on any endpoint now returns a
  fuzzy `Unknown field 'X' — did you mean 'Y'?` error with the valid-field list,
  instead of a bare rejection.

## [1.23.3] – 2026-06-13

### Fixed

- **Help text wrongly claimed several event commands require a ticket.**
  Mirroring the server `1.23.3` ticket-gating relax, `event-sponsors`,
  `event-agendas`, and the `--user-id` form of `event-agenda` (viewing another
  attendee's agenda) are now open to any DCer — their help + argument
  descriptions no longer say "requires a ticket". Your OWN `event-agenda`,
  `event-free-slots`, `session-bookmark`, and `meetup-rsvp` stay ticket-gated
  (unchanged). No client behavior change — the server enforces access; this only
  corrects the advertised help so agents don't pre-filter on a ticket they don't
  need.

### Note

Version jumps `1.22.6 → 1.23.3` to realign with the live Member API version (the
`1.23.0`–`1.23.2` server releases — service-layer refactor + in-process MCP
cutover — were server-only with no client surface change, so no client release).

## [1.22.6] – 2026-06-05

### Fixed

- **`profile-update` advertised field names that 400.** The MCP/CLI schema
  documented `businessDescription`, `businessUrl`, and `industry` — none of
  which exist in the server's strict `/profile` schema, so they failed with a
  400. Reworked the blind passthrough into an explicit, validated field map
  covering all 30 real API fields (correct names, boolean coercion for the
  `*IsPrivate` flags); the three legacy names are now accepted as aliases.
  Unknown fields are rejected client-side with the valid list.
- **`trip-create` / `trip-update` silently dropped top-level `--note`.** The
  server accepts a trip caption (`note`) on create + update, but the client
  never sent it through the parser, wrapper, MCP schema, or request body.
  Now fully wired. (HS 3339048660)
- **`calendar-update` forwarded unknown toggles to the server.** Now validated
  client-side against the nine known feed toggles, with a clear error.

### Added

- **Offline test suite** (`tests/`, pytest) — runs with no network, wired
  into CI as a gate before build/publish. Covers **every registered command**
  (parametrized registration + binding checks: each command exposes a typed
  `args=` schema and every declared flag is accepted by its arg-binding),
  plus per-command parser, request-body, and schema-contract tests. Together
  they lock both bug classes shut: "command rejects its own declared flag"
  and "documented-but-wrong field name."

## [1.22.5] – 2026-06-03

### Fixed

- **MCP commands rejecting their own `--flag` args.** Any command declared
  with `@skill_command(args=...)` but no custom `parser=` raised
  `Command '<name>' does not accept flags` when driven over MCP (the
  MCP→CLI bridge serializes every kwarg as `--flag value`). Added an
  auto-parser fallback in the dispatcher that routes declared kebab-case
  flags to the wrapper's snake_case kwargs with type coercion — fixes
  `profile-match`, `trip-discovery`, `event-agenda`, `event-free-slots`,
  `session-bookmark`, `meetup-rsvp`, `room-messages`, `room-summaries`,
  and makes "declared in `args=` ⇒ accepted on the CLI" a structural
  invariant.
- **`event-schedule` / `event-meetups` help corrected.** Both wrongly
  claimed "Requires an event ticket". The listings are public — only
  RSVPing to a meetup needs a ticket.

### Changed

- **Version-locked to API 1.22.5.** Bumped `DC_API_VERSION` to match the
  deployed release: `GET /tickets` now defaults to the tickets you hold
  (`valid` + `maybe`) and never exposes canceled tickets, and the locator
  `serializeProfile` path respects the `shareLoc` location opt-out.

## [1.22.4] - 2026-05-27

### Fixed

- **Trip points CLI drift.** `dc trip-create` and `dc trip-update` now
  actually parse and forward `--points` as a JSON array. The commands had
  advertised the flag, but the custom parser was dropping it before the API
  call.
- **Member API parity fixes are now version-locked.** Bumped
  `DC_API_VERSION` from `1.22.3` to `1.22.4` to match the deployed API
  release that queues profile/calendar sync side effects, makes event
  bookmark/meetup mutations transactional and idempotent, accepts `noteHTML`
  on trip points, and returns the standard membership role key `dcc`.

### Changed

- Trip point docs now include the full supported shape:
  `{note?, noteHTML?, placeID?}`.

## [1.22.3] – 2026-05-23

### Added

- **Search — 6 new commands** wrapping the new `/search/*` endpoint family.
  `dc.search(q, page=1, per_page=20)` runs a multi-resource search across
  profiles, rooms, messages, events, and chapters in one call. Per-resource
  commands (`dc.search_profiles`, `dc.search_rooms`, `dc.search_messages`,
  `dc.search_events`, `dc.search_chapters`) accept the same `q` + pagination
  arguments plus resource-specific filters: `--room-id` + `--user-id` on
  messages; `--type` on rooms; `--city-id` / `--country` / `--since` /
  `--until` on events. 1-indexed pagination via `page` / `per_page`; the
  response envelope is `{ hits, total, page, hasMore }`. Only the caller's
  own visible surface is returned — server-side post-filter drops anything
  the caller can't see, and per-resource serializers whitelist fields.
- **Follows — 6 new commands.** `dc.follows_profiles()` / `dc.follows_chapters()`
  return the caller's full follow lists (caps: **150 profiles**, **50
  chapters**). `dc.follow_profile(userID)` / `dc.follow_chapter(cityID)`
  add to the list (`409 follow_limit_reached` when the cap is hit, `400
  self_follow_not_allowed` on self-follow attempts, `404 profile_not_found`
  for hidden / non-existent users). `dc.unfollow_profile(userID)` /
  `dc.unfollow_chapter(cityID)` remove. All mutations are protected by
  `sensitiveBurstGuard`. The follow list is private to the caller — there
  is no inbound-follower lookup, no follower-count exposure on profiles.

### Changed

- `DC_API_VERSION` bumped from `1.20.1` → `1.22.3` to match the deployed
  server. Server bumps for search + follows shipped as `1.22.0`, then
  re-deployed as `1.22.3` after an in-band fix to the OpenAPI generator
  (missing route-file imports were causing the new endpoints to be absent
  from the published spec).

---

## [1.20.1] – 2026-05-22

### Added

- **`warning` field on the response envelope.** Both success (`ok: true`)
  and error (`ok: false`) payloads now carry an optional top-level
  `warning` string. Currently used by the server to surface client-version
  drift notices ("dc-py 1.10.0 is 10 minor versions behind the deployed
  API…") on every call from an outdated client, alongside the existing
  HTTP `Warning: 299 …` response header. No client-side parsing change
  required — clients that ignore the field stay unaffected.

### Changed

- **Hard rename `direct` → `dm` in the room-type vocabulary.** The
  member-facing room-type values are now `channel`, `dm`, `group`,
  `discussion`, `quick-question`, `event`. Calls to
  `GET /rooms/inbox/direct` now return `400 invalid_type` instead of
  redirecting — there is **no alias**. Update any pinned `?type=direct`
  filters to `?type=dm`. Internal `RoomType.Direct` is unchanged; this
  is a pure wire-format rename.
- **`/profile/limits` 308 redirect removed.** The endpoint moved to
  `/limits` in 1.11.0; the redirect existed for old clients. Now it
  returns `404 not_found` with a hint:
  *Did you mean `GET /limits`?* — `dc-py` has been on `/limits` for
  several releases so no callable change for current clients.
- **Smarter 404 "Did you mean…?" suggester.** Adds a suffix-match
  bonus so `/profile/limits` resolves to `/limits` (previously
  Levenshtein-only would have suggested `/profile-match`). Same for any
  `/v2/X/Y` → `/X/Y` style leftover-prefix mistakes.

### Notes

- The deployed server is **`1.20.1`** (deploy script auto-patched the
  manually-bumped `1.20.0`). The triple-lock is therefore kept at
  `1.20.1` here so the X-API-Version warning stays silent for
  up-to-date clients.

---

## [1.19.3] – 2026-05-21

### Fixed

- **Server-side: did-you-mean 404 suggester is now functional on
  Express 5.** The previous implementation walked the internal Express
  router stack to recover all `METHOD path` pairs at startup, but
  Express 5 nulled `layer.regexp` on mounted sub-routers (the mount
  prefix moved into a `path-to-regexp` closure on `layer.matchers[0]`)
  and renamed `app._router` → `app.router`. Result: the route table
  was empty in production and every 404 fell through to the generic
  hint. Switched the source-of-truth from the router stack to the
  docs `endpointRegistry` (every documented endpoint already calls
  `registerEndpoint(...)`), plus a small static list of unlisted
  discovery endpoints (`/`, `/ping`, `/health`, `/openapi.json`,
  `/workflows`, `/security.txt`).

  No client-side change required — the `hint` field on 404 payloads
  is already surfaced by `DCError`. Bump kept in lockstep with the
  deployed API contract version per the triple-lock rule.

---

## [1.19.2] – 2026-05-21

### Added

- **`workflows` command** — calls the new `GET /workflows` endpoint and
  returns a machine-readable list of common API recipes
  (who-is-in-city, plan-together-at-event, find-DCers-by-description,
  manage-inbox, refresh-profile, catch-up-on-channel, etc.). Each
  recipe carries a goal, an ordered list of `{method, path}` steps,
  and notes. Designed as the first call an unfamiliar agent makes to
  the API.
- **Error responses now carry an optional `hint` field** on the server
  side. The client surfaces it via `DCError` automatically — when the
  server includes a hint pointing at a discovery endpoint or follow-up
  call, it shows up in the exception. No client-side API changes; the
  field is additive on the wire.

### Changed

- **404s on unknown paths now include a "Did you mean…?" suggestion**
  (server side). The Levenshtein-based suggester compares the requested
  path against the live route table — typos like `/place/<id>` get a
  hint pointing at `/places/<id>`. Surfaces in the `hint` field of the
  404 payload.

(Versions 1.18.0 → 1.19.1 were server-side only; this is the first
public client release on the new line.)

---

## [1.17.3] – 2026-05-20

### Changed

- **Big docs audit + cleanup — 25 endpoint description issues fixed.**
  An exhaustive audit of every `registerEndpoint(...)` description
  against the actual handler code surfaced lies, drift, and gaps that
  were misleading LLM agents. All landed in one patch:

  **Response-shape lies (8 critical):**
  - `POST /virtual-events/:sessionID/rsvp` — actual response is
    `{ sessionID, status, userID }`, not `{ status, joinCall, rsvpAt }`.
    Docs claimed RSVPing "unlocks the join URL" — it doesn't; `meetUrl`
    is exposed regardless of RSVP state.
  - `GET /virtual-events/:sessionID` — dropped false claims about
    `host`, IANA `timezone`, `recording URL`, and RSVP-gated join URL.
  - `PATCH /calendar` — returns `{ updated: true }` only, not toggles
    plus feed URLs.
  - `GET /inbox/unread` — `limit` is 1-100, not 1-200.
  - `GET /invites` — `status` enum was missing four real values
    (`booked-call`, `awaiting-payment-auth`, `invalid`, `qualified`).
  - `GET /profile` — removed false "DC BLACK members see additional
    business fields" claim (tier-blind since 1.16.2).
  - `POST /trips` — per-field text clarified to "pass exactly one of
    `placeID` or `eventID`" (was "required if the other not provided",
    which implied both could be passed).

  **Pagination metadata gaps (6 list endpoints):**
  - `/chapters`, `/events`, `/trips`, `/tickets`, `/invites`,
    `/virtual-events` — schemas and handlers already supported
    `cursor` + `nextCursor`. Now documented.

  **Other misleading text (5):**
  - `/profile-match` — `gender` enum gains `Prefer not to say`;
    `minTeamSize` notes that the same value exists in the bucket
    vocabulary but is treated as unknown and filtered out.
  - `/notifications` — fixed stale reference to non-existent
    `/profile/locator-settings` (correct path is `/locator/settings`).
  - `POST /invites` — documented actual response shape (nested
    under `referral`, `referralID` not `inviteID`).
  - `/events/:eventID/agendas` + `/free-slots` — `userIDs` marked
    required.

  **Thin response shapes + access notes (6):**
  - `/events/:eventID/attendees` — full profile shape clarified;
    `limit` corrected to 1-100.
  - `/chapters/:cityID` — full chapter + `currentVisitors` shapes
    spelled out.
  - `/places/:placeID` — full place shape spelled out.
  - `/events/:eventID/{schedule,agenda,meetups,sponsors,
    schedule/:sessionID/attendees,meetups/:meetupID/attendees}` —
    added explicit "Access: caller must hold a valid ticket" note.

No behavior change — pure docs/metadata patch. PyPI tag bump keeps
`DC_API_VERSION` aligned with the deployed server.

## [1.17.2] – 2026-05-20

### Changed

- **Docs cleanup** — four endpoints had near-empty descriptions that
  rendered as placeholder cards in the public Scalar docs. Fleshed
  out so LLM agents and members reading the docs have enough context
  to choose the right endpoint:
  - `DELETE /trips/:tripID` — calls out owner-only, irreversible,
    side-effects (linked chat room destroyed, chapter rollups
    recomputed).
  - `GET /virtual-events/:sessionID` — full payload + RSVP state.
  - `POST /virtual-events/:sessionID/rsvp` — three statuses,
    idempotency, what each does.
  - `GET /invites` — documents the three credit sources (`manual`,
    `permaCode`, `mention`). `mention` noted as a one-line fallback
    (applicant named you on their application form) and explicitly
    framed as not reliable — don't count on it.

No client-facing behavior change — pure documentation patch. PyPI
client tag bumps to keep `DC_API_VERSION` aligned with the deployed
server so the `X-API-Version` warning stays accurate.

## [1.17.1] – 2026-05-20

### Breaking

- **`activity` room-type renamed to `quick-question` on the API wire.**
  The official in-app label has been "Quick Question" for a while —
  the API surface now matches. URLs (`/rooms/inbox/quick-question`,
  `/rooms/browse/quick-question`) and response shapes (`type:
  "quick-question"`) use the new identifier. Old `activity` paths and
  type filters now return 400. The internal Firestore tag stays
  `activity` — this is a wire-format rename only.

### Added

- **AI summaries — daily and weekly slots, history pagination.**
  - `GET /rooms/:roomID` now returns BOTH `aiSummaryDaily` and
    `aiSummaryWeekly` in distinct slots (either may be `null`). They
    cover different windows so they never get blended.
  - **`dc room-summary <roomID> --type daily|weekly`** — fetch the
    latest single summary of a specific type. Type is required; the
    type-agnostic call was deliberately removed.
  - **`dc room-summaries <roomID> --type daily|weekly [--limit N]
    [--cursor TOKEN]`** — paginate past summaries newest-first.
    Cursor encodes `sortDateAt`. Useful for catch-up workflows.
  - Each summary carries: `type`, `summaryID`, sanitized `html`,
    `topics[]`, `urls[]` with `{label, url, sharedBy}`,
    `intervalStartAt`, `intervalEndAt`, `generatedAt`,
    `messageCount`, `participantCount`.
- **Room state management (writes the per-user `seen` doc).**
  - **`dc room-subscribe <roomID>`** — subscribe to a public
    channel, discussion, quick-question room, or event room. Event
    rooms require a valid ticket. DMs and group DMs are managed
    in-app only.
  - **`dc room-unsubscribe <roomID>`** — drop a room from your inbox
    sidebar. Clears the room's badge count to avoid the
    stuck-red-dot bug.
  - **`dc room-mute <roomID>` / `dc room-unmute <roomID>`** — mute is
    indefinite (until you explicitly unmute); the room stays in your
    inbox.
  - **`dc room-archive <roomID>` / `dc room-unarchive <roomID>`** —
    archive hides the room from your inbox sidebar without
    unsubscribing.
  - **`dc room-pin <roomID>` / `dc room-unpin <roomID>`** — pin to
    top of inbox. Pinning a subscription-type room auto-subscribes
    you if you weren't already (mirrors the in-app behavior).

All mutation endpoints mirror the in-app `useSeenService` exactly —
same transaction semantics, same audit timestamps (`subscribedAt`,
`unsubscribedAt`, `archivedAt`, `unarchivedAt`, `pinnedAt`,
`mutedUntilAt`), same auto-subscribe-on-pin behavior. They're also
wired into the new `sensitiveBurstGuard` rate-limit layer so leaked
API keys can't be used to abuse the mutation surface.

## [1.16.2] – 2026-05-20

### Changed

- **Public "other-person" profile now matches the in-app profile card.**
  Every DC tier (DC + DC BLACK alike) now sees the same field set on
  `/profile-match` results, `/events/:eventID/attendees`,
  `/chapters/:cityID/members`, `/chapters/:cityID/currentVisitors`,
  `/trips/:tripID/discovery`, and every other endpoint that returns
  someone else's profile.

  Newly visible fields (were DC-BLACK-only or omitted entirely):
  `bizName`, `bizUrl`, `bizDescription`, `bizYears`, `bizIndustry`,
  `goal`, `expertise`, `ama`, `hobbies`, `nickname`, `locations`,
  `connect`, `revenue`, `teamSize`, and a new `socials` block with
  `facebook`, `focusmate`, `github`, `instagram`, `linkedin`,
  `twitter`.

  Privacy-gated fields (`revenue`, `teamSize`, `connect`) only
  populate when the field owner shared the value with all DCers;
  otherwise `null`.

  **Not exposed on the other-person view:** `whatsapp`. WhatsApp stays
  on the member's own `/profile` only — members have not consented
  to expose it to API consumers.

  **DCB-specific shape removed.** A single `ApiProfile` shape is now
  returned everywhere — DC and DC BLACK callers get the same surface.

### Added

- **Member API now open to trial DC accounts.** Trial members are
  eligible from day one (was: blocked until trial period ended).
  Auto-generated API keys land on first profile sync. Guests and
  inactive accounts remain blocked.

## [1.14.1] – 2026-05-19

### Added

- **`dc room <roomID>`** — single-room metadata read (name, type,
  description, stats, last activity, scope). Access gate is strict:
  the caller must be a subscribed member of the room, or the room must
  be a publicly browsable channel/discussion/activity. Non-members of
  private rooms, DMs, group DMs, and event rooms get a clear 403.
- **`dc room-messages <roomID>`** — paginated, **read-only** message
  history for any room the caller has access to. Newest-first; cursor
  via `--before=<token>`. Limit 1–100 (default 50). Each entry has
  `messageID`, `roomID`, `sentAt`, `editedAt`, `isDeleted`, mini
  `author` block (userID, userName, displayName, photo, profileURL),
  `text` (possibly sanitized HTML), `type`, `isHTML`, `replyTo`,
  `reactions`. Sunk and hidden messages are filtered server-side;
  deleted messages render as tombstones with empty text. Reading does
  NOT mutate the room's unread state on the caller's profile —
  agents can scan history without marking messages as read.
- **`GET /chapters/:cityID` returns `currentVisitors`** — every DCer
  currently in that chapter's city via an active trip
  (`startDate <= now <= endDate`). Each entry includes the visitor's
  mini profile, trip ID, and trip start/end dates. Hidden + guest
  profiles are filtered. Answers "who is in <city> right now?"
  without forcing the caller to create their own trip first.

### Changed

- **`dc rooms` is now path-segment filtered.** The optional
  `--type` flag still works on the client side, but the underlying
  URL changed from `/rooms?type=X` to `/rooms/inbox/:type` (e.g.
  `/rooms/inbox/direct`). The all-types call stays at `/rooms` (no
  filter). Cursor pagination via `--cursor=<token>` is now supported.
- **`dc browse-rooms` switched to `/rooms/browse/:type`.** Existing
  callers (the dc-py 1.13.x release) pointed at `/rooms/browse?type=`
  — this client now uses the new path. Cursor pagination unchanged.
- **`dc rooms --type=` enum trimmed** to `channel`, `direct`, `group`,
  `discussion`, `activity`, `event`. Legacy `city` / `country` /
  `mastermind` types are no longer filterable via this endpoint (the
  app still classifies them internally; they just don't appear on the
  public Member-API filter surface).
- **`/profile-match locationCurrentPlaceID` docs** now flag that this
  filter is sparsely populated (most DCers leave `currentLocation`
  null) and point at the trip-discovery flow as the canonical
  presence query.
- **Public role-label examples** drop the legacy `"DC Red"` string —
  responses now show the canonical `"DC Member"` / `"DC Community"`
  labels per the brand convention.

## [1.13.1] – 2026-05-19

### Added

- **`dc trip <tripID>`** — single-trip read with the full payload.
  Returns trip basics (`location`, `dates`, `note`, `roomID`) plus the
  embedded `points` (up to 20 venue/idea notes with optional Google
  Place data) AND a fully-enriched `discovery` block:
  - `discovery.people` — ranked top-10 DCers to meet, each with mini
    `profile` (userID, userName, displayName, photo, headline), a
    `score` (higher = better match), `reason` (`local` / `visiting` /
    `event-attendee`), `overlapDays`, `detail`.
  - `discovery.fullPool` — every visible DCer travelling or local
    during the trip window. Same shape as `people` minus `score`.
  - `discovery.whyToMeet` — AI-written "why you should meet them"
    paragraphs keyed by userID, each `{ text, generatedAt }`. Only
    the top-10 picks get entries. Persistent across refreshes.
  - `discovery.events` — events in the destination city during the
    trip window.
  - `discovery.overlappingTrips` — other DCers travelling at the
    same time/place, with mini `profile` attached (no second fetch
    needed).
  - `discovery.generatedAt` — when the discovery cache was last
    refreshed.
  Hidden + guest profiles are filtered out from all discovery lists.
  The `discovery` block is `null` for newly-created trips until the
  background sync task runs (typically seconds).

- **`dc trip-discovery <tripID> [--include=...]`** — discovery-only
  read. Same shape as the `discovery` block in the full trip read,
  without the trip body. Useful when an agent just needs the
  matchmaking signal.
  - `--include` accepts a comma-separated subset of
    `people,fullPool,whyToMeet,events,overlappingTrips`. Default = all
    five. Common patterns:
    - `--include=people,whyToMeet` — top-10 picks + their AI paragraphs
    - `--include=fullPool` — every visible DCer in town
    - `--include=events` — just events in the destination city

- **`dc trip-refresh <tripID>`** — owner-only trigger to re-enqueue
  the discovery cache rebuild. Returns 202 immediately; cache
  refreshes in the background.

- **Trip points on `trip-create` / `trip-update`** — both commands now
  accept an optional `--points` array (up to 20). Each item is
  `{note: string (max 280 chars), placeID?: string}`. The optional
  `placeID` is resolved against Google Places at write time and the
  full Place object (city, country, lat/lon, name, etc.) is stored
  on the trip — so reads don't do any lookups. Notes without a
  `placeID` are valid ("remember to book a coworking space"). On
  `trip-update`, passing `--points` **replaces** the entire array;
  pass `[]` to clear.

### Why

The DC web/mobile app now exposes trip "points" and a rich AI
discovery surface in the trip detail page — places to remember,
"who should I meet on this trip?" with ranked picks, AI-written
intros explaining why each pick matters, and overlapping trips with
attached profiles. This release brings all of that through the Member
API so AI agents can plan trips, pre-brief a member before they
travel, and find shared meeting windows without fanning out a dozen
separate calls.

### Fixed

- **MCP stdio transport hang.** Replaced the Python SDK `stdio_server`
  helper with a small buffered stdio transport so `dc.py --mcp`
  responds reliably to `initialize`, `tools/list`, and tool calls on
  current Python/MCP SDK setups.

---

## [1.12.5] – 2026-05-14

### Added

- **`POST /profile-match` — real similarity scores + new filters + reranker A/B.**
  - Each result now carries three scores: `score` (composite, sortable —
    blend of vector + keyword when reranker ran, raw `vectorScore`
    otherwise), `vectorScore` (pure semantic 0..1 from Firestore
    vector search), and `keywordScore` (raw keyword overlap, only when
    reranker ran). Old "fake" rank-derived scores are gone — these are
    the real numbers and reflect actual match quality.
  - Four new filters compose with AND alongside the existing ones:
    - `industry` — exact match on PrimaryBusinessIndustry
      (`"SaaS & Tech"`, `"Marketing Agency"`, `"Ecommerce & Amazon"`,
      `"Coaching"`, `"Other"`, etc.).
    - `min_team_size` — "at least this size" filter, ordered
      `None < 1-2 < 3-5 < 6-9 < 10-14 < 15-19 < 20-34 < 35-49 < 50-74 < 75-99 < 100+`.
      Only matches DCers who set their team-size visibility to "all DCers".
    - `min_revenue` — "at least this revenue" filter (e.g. `"$1M+"`,
      `"$250K+"`). Only matches DCers who set their revenue visibility
      to "all DCers".
    - `gender` — exact match (`Man`, `Woman`, `Non-binary`). **Note:
      Gender is sparsely populated — most DCers leave it blank.**
      Use as a "narrow if set" hint, not a hard requirement.
  - `no_rerank` flag skips the keyword reranker and returns results
    in raw vector-similarity order. Useful for fuzzy/semantic queries
    where exact keyword overlap would add noise, or for A/B comparison
    against the reranked default.
  - Result limit cap raised 20 → 50 (default still 20 in the skill).

- **`GET /` is fully self-describing.** Returns `{ name, version, links }`
  with `links` pointing at `/openapi.json`, `/.well-known/mcp.json`,
  `/.well-known/security.txt`, the docs page, plus marketing URLs
  (`site`, `apply`, `dcBlack`). One fetch tells any agent where to go.
- **`GET /openapi.json`** + **`GET /.well-known/openapi.json`** serve the
  full OpenAPI 3.1 spec. IANA-registered well-known location plus the
  canonical short path.
- **`GET /.well-known/mcp.json`** — Anthropic MCP discovery descriptor
  (name, transport, install command, auth scheme, openapi pointer).
- **`GET /.well-known/security.txt`** — RFC 9116 security contact.

### Fixed
- **Rerank math sign-flip.** The keyword reranker was sorting on raw
  euclidean distance (lower = closer) with the same direction as
  similarity (higher = better) — so ties surfaced the FURTHEST
  candidates, not the closest. Now: distance → similarity via
  `1 / (1 + d)` before reranking, and the keyword score is normalised
  per batch so it doesn't swamp the vector signal.
- **Mode-2 ("DCers you should meet") reranking.** When no `query` is
  passed and the server builds an implicit query from your profile,
  the reranker is now applied (previously skipped because metadata
  was passed as an array).
- **Locator privacy gate.** `GET /locator/digest` now filters hidden
  test accounts and guest profiles out of `homeCity.newMembers`,
  `chapterLeads`, `localMembers`, and every trip/ticket reference.

### Changed
- `profile.locCurrent` type acknowledges that it can carry a `placeID`
  (it's a `Place` when derived from `locMobile` / `locBase` / active
  trip, a bare `Loc` otherwise). No data change; the schema type just
  matches the docs that have always existed in production.

---

## [1.12.1] – 2026-05-08

### Added
- **`GET /events/:eventID/agendas?userIDs=A,B,C`** — bulk fetch up
  to 20 attendee agendas in one call. Drop-in for the LLM use-case
  "compare schedules across several DCers" (find shared sessions,
  spot meetup overlap) without paying N round-trips. Non-attendee
  IDs are silently dropped — pass a candidate list without
  pre-checking each ticket. Caller must hold a valid ticket to the
  event. New skill command: `dc event-agendas <eventID>
  --user-ids=A,B,C`.
- **`POST /events/:eventID/free-slots`** — server-side computation
  of shared free time windows across event attendees. Body:
  `{ userIDs[], minDurationMins?, withinDayDate? }`. Returns slots
  ranked by overlap (most-shared first), each tagged with `freeFor`
  / `busyFor`. Date math runs server-side once instead of in every
  LLM caller — the same fake-UTC wall-clock convention as the rest
  of the events API, paired with the venue IANA timezone. Caller
  must hold a valid ticket; non-attendee IDs silently dropped. New
  skill command: `dc event-free-slots <eventID> --user-ids=A,B,C
  [--min-duration-mins=30] [--within-day-date=2026-05-06]`.

### Why
- Single-attendee `/agenda/:userID` shipped in 1.10.5; the missing
  pieces for "plan together with N DCers at an event" were the
  bulk fetch and the gap-finder. Both now land together so the
  AI-agent UX for "find me 30 minutes with Peter on Tuesday" or
  "plan a junto-style lunch with Alex, Lina, and Jeff at DCMEX"
  works in one or two calls.

---

## [1.11.1] – 2026-05-07

### Breaking
- **`/profile/limits` moved to `/limits`.** The rate-limit
  endpoint is now mounted at the root, like the rest of the
  non-profile surface. The old path returns **HTTP 308** with
  `Location: /limits` — 308 preserves the GET method (vs 301
  which clients sometimes downgrade), so older callers that
  follow redirects keep working through one extra hop. The
  `dc.limits()` helper in this client already points at the
  new path.

### Changed
- **`POST /profile-match` is now described as "AI-powered".**
  Behaviour unchanged. The public OpenAPI description now
  leads with "AI-powered profile matchmaker" so callers
  immediately understand it uses Gemini embeddings + reranking
  under the hood, and carries stricter rate limits than the
  standard CRUD endpoints.

---

## [1.10.5] – 2026-05-07

### Added
- **`POST /profile-match`** — match DCers from a free-form
  description, or recommend if no `query` is passed. Profiles-only.
  Optional filters compose with AND:
   - `query` — free-form description ("DCers in Lisbon who run SaaS")
   - `locationChapterPlaceID` — narrow to DCers based at this Google Place
   - `locationCurrentPlaceID` — narrow to DCers currently at this place
   - `eventID` — narrow to DCers attending the event (valid ticket only)
   - `isDCB` — DC BLACK members only
  Hard cap at `limit: 20`. Each result includes `chapter` (base) +
  `currentLocation` (when travelling).
- **`GET /events/:eventID/agenda/:userID`** — view another attendee's
  agenda for a shared event so AI agents can plan together (find
  coffee windows, suggest sessions to overlap, propose meetups).
  Both you and the target must hold a valid ticket. Returns the same
  shape as the self `/agenda` plus the target's mini profile.
- **`currentLocation` field on every `ApiProfile` response** — built
  from a member's current location, populated only when different
  from their base chapter.
- **New CLI commands**: `dc profile-match [--query …] [--limit N] [--location-chapter-place-id …] [--location-current-place-id …] [--event-id …] [--is-dcb]` and `dc event-agenda <eventID> [--user-id …]`.
- **New library methods**: `DC.profile_match(...)` and `DC.event_agenda(event_id, user_id=None)`.

### Changed
- **List/recommendation endpoints now exclude system-test profiles
  and event-only guest profiles.** New shared `isPubliclyVisible`
  gate applied to: `/profile-match`, `/events/:eventID/attendees`,
  session/meetup attendees, `/chapters/:cityID` members,
  `/trips/overlaps`. Single-profile lookups are unaffected.

Bumped `DC_API_VERSION` to 1.10.5 (matches deployed server).

---

## [1.10.4] – 2026-05-04

### Fixed
- **`PATCH /notifications` now actually persists changes.** Previous
  release set values via `set({"cats.foo.email": false}, {merge:true})`
  which Firestore stores as a literal top-level key — silently no-op
  for the read path. Now uses `update()` (which understands dot paths)
  with a fall-through to `set(nested)` for first-time writes.

### Changed
- API instance class bumped from F1 (256MB / 384MB hard cap) to F2
  (512MB) so the server starts cleanly. The expanded surface (sharp,
  stripe, full route set) was OOM'ing F1 at startup.

Bumped `DC_API_VERSION` to 1.10.4 (matches deployed server).

---

## [1.10.2] – 2026-05-04

### Added
- **`GET /membership/invoices`** — your Stripe invoices (newest first)
  with hosted invoice URL + PDF link, amount, currency, status, period
  start/end, and plan description. Useful for self-serve receipts.
  Returns an empty list for legacy paypal/chargify members or members
  with no Stripe customer record.
- **`GET /notifications` + `PATCH /notifications`** — read and update
  push/email preferences per notification category. 12 categories:
  `account`, `activity`, `announcement`, `channel`, `chat`,
  `directMessage`, `discussion`, `event`, `mention`, `myReaction`,
  `photoTag`, `reaction`. Email is `null` for `reaction` / `myReaction`
  (not supported there). Defaults are applied for any preference you
  haven't explicitly set.
- **`GET /locator/settings` + `PATCH /locator/settings`** — read and
  update the four toggles for the Friday locator email digest:
  `enabled`, `events`, `tickets`, `trips`.
- **`GET /calendar` + `PATCH /calendar`** — your iCalendar feed and
  the 9 content toggles. Returns three subscription URLs for the same
  feed: `httpsURL` (works in any calendar app), `webcalURL` (macOS /
  iOS open it directly), and `googleURL` (one-click Google Calendar
  subscribe). Toggles control which event categories are included:
  your tickets, bookmarked agenda items, virtual calls, your trips,
  flagship events (DCBKK/DCMEX), DC BLACK retreats, home chapter
  events, followed-chapter events, and other-chapter events. Defaults
  mirror the in-app subscribe modal exactly.
- **New CLI commands**: `dc invoices`, `dc notifications`,
  `dc notifications-update`, `dc locator-settings`,
  `dc locator-settings-update`, `dc calendar`, `dc calendar-update`.
- **New library methods**: `DC.membership_invoices()`,
  `DC.notifications()`, `DC.update_notifications()`,
  `DC.locator_settings()`, `DC.update_locator_settings()`,
  `DC.calendar()`, `DC.update_calendar()`.

### Fixed
- Sharp re-encode pipeline for `POST /report-issue` screenshots no
  longer rejects valid PNG/JPEG/WebP images on the right `fit` option.
  EXIF metadata still stripped on every accepted upload.

Bumped `DC_API_VERSION` to 1.10.2 (matches deployed server).

---

## [1.9.1] – 2026-05-04

### Added
- **`GET /membership`** — your full membership state in one call:
  role (label + key), join date, DC BLACK status, trial info, full
  billing details (status, plan, current period, next billing date,
  formatted amount, currency, frequency), and a Stripe Customer Portal
  link for managing your subscription, payment method, and invoices.
  Use this to check renewal dates, see your current tier, or surface
  the manage-billing link in your own UI.
- **`POST /report-issue`** — self-service bug / feedback / question
  reporting endpoint. Sends a structured report to the DC team with
  your message, optional structured `context` for debug info, and an
  optional screenshot. The Python client's `report_issue(...)` helper
  accepts a screenshot as a file path, raw bytes, or a base64 / data:
  URL string and handles encoding for you. PNG, JPEG, or WebP only;
  re-encoded server-side to strip EXIF; max 4 MB raw.
  **Privacy note:** screenshots and report text go to the DC team
  unredacted — don't include passwords, payment details, or secrets.
- **New CLI commands**: `dc membership` and `dc report-issue --text "..." [--severity bug|feedback|question] [--screenshot path] [--context '{...}']`.
- **New library methods**: `DC.membership()` and `DC.report_issue(text, severity, screenshot, context)`.

Bumped `DC_API_VERSION` to 1.9.1 (matches deployed server).

---

## [1.8.1] – 2026-05-04

### Added
- **`type` field on every `/places/search` and `/places/:placeID`
  result** — `"city"` for chapter-level matches usable in `POST
  /trips`; `"venue"` for everything else (specific addresses,
  establishments, country-level matches). Filter `type === "city"`
  in your client code when building a trip-creation flow; events
  and meetups accept both.
- **Richer location fields on every place + trip response**:
  `description`, `lat`, `lon`, `latLon`, `region`, `regionCode`,
  `utcOffsetMins`. Available on `/places/search`, `/places/:placeID`,
  and trip responses.

### Fixed
- **Trips created via API now sync correctly with the DC web app.**
  Previously, opening an API-created trip in the in-app trip editor
  could show a "Location is invalid" error and block Save. Resolved.
- **`/places/search` no longer returns country-level matches with
  empty city fields.** Useless results that could lead to broken
  trips are now properly classified as `type: "venue"` instead.
- **Chapter counts and locator digests update immediately after a
  trip create / update / delete via the API**, instead of waiting
  for the next periodic recalc.

### Changed
- **`POST /trips` rejects placeIDs that aren't cities.** Passing a
  venue placeID now returns 400 with a clear error pointing you at
  `/places/search` and the `type === "city"` filter.

Bumped `DC_API_VERSION` to 1.8.1 (matches deployed server).

---

## [1.7.1] – 2026-05-03

### Changed
- **Profile `chapter` field is now populated.** Previously the API
  always returned `chapter: null` regardless of whether the member
  had set a base location. Now `dc.profile()` returns the member's
  home chapter as `{chapterURL, cityName, country, countryCode, placeID}`
  whenever they've set `locBase` in their DC profile.
- **Chapter shape unified across endpoints.** `/chapters` list/detail
  now matches the profile.chapter shape exactly: `cityName` (was
  `city`), plus `country` (added) alongside `countryCode`, plus
  `chapterURL` and `placeID`. `/locator/digest` `favoriteCities`
  entries also now include `country` (full name) alongside
  `countryCode`.
- `cityName` uses the same friendly-display logic as the in-app
  profile card ("Bangkok, Thailand" rather than just "Bangkok").

### Fixed
- `/chapters` `chapterURL` was pointing at `cdn.dynamitecircle.com`
  (the CDN, no app routes there). Now points at
  `dc.dynamitecircle.com/chapter/<placeID>`.

Bumped `DC_API_VERSION` to 1.7.1 (matches deployed server).

---

## [1.6.3] – 2026-05-02

Same content as the failed 1.6.2 attempt — PyPI never accepted 1.6.2
because the GitHub Actions smoke step asserted that `dc --json help`
emits JSON, which it never has (`help` is text-only). Smoke step
rewritten to use `dc help setup` (which exercises subcommand-help
dispatch without any network call). Bumping to 1.6.3 because PyPI
versions are immutable — we can't retry 1.6.2.

## [1.6.2] – 2026-05-02 (skipped — workflow failed)

Tag exists but no PyPI release. Replaced by 1.6.3.

### Changed

- **Repo renamed** — `dynamitecircle/dc-py` → `dynamitecircle/dc`. The
  repo is now a **monorepo** so future Go / Node / Rust clients can sit
  alongside the Python one without a separate repo per language.
- **Python client moved to `/py/`** — `/dc/dc.py` → `/py/dc.py`,
  `/dc/SKILL.md` → `/py/SKILL.md`, etc. The `.claude/skills/dc` and
  `.agents/skills/dc` symlinks now point at `../../py` so AI-tool
  auto-discovery is unchanged. (Future siblings will live at `/go/`,
  `/node/`, `/rs/`.)
- **Layout** — canonical files moved out of dotfile-prefixed directories
  so they're visible in `ls`. Python client is at `/py/` and the
  design docs are `/docs/`. `.claude/skills/dc/`, `.agents/skills/dc/`,
  `.claude/docs/`, and `.agents/docs/` are now symlinks pointing at the
  canonical folders. AI-tool auto-discovery still works through the
  symlinks; you only edit files in one place.
- **File rename** — `dc/dc_skill.py` → `dc/dc.py` (later moved to
  `py/dc.py` in the monorepo flip; the `_skill` suffix was redundant
  once the folder itself is the skill).
- **Class renames** — public Python surface refreshed:
  - `DCSkill` → `DC`
  - `Skill` (base) → `Runtime`
  - `SkillError` → `DCError`
  - `SkillResult` → `Result`
  - Old: `from dc_skill import DCSkill; DCSkill().profile()`
  - New: `from dc import DC; DC().profile()`
- **Doc renames** for symmetry inside `docs/`:
  - `docs/skill-conventions.md` → `docs/skill-info.md`
  - `docs/mcp.md` → `docs/mcp-info.md`
- **User-Agent** — `dc-official-skill/<version>` →
  `dc-py/<version>`. Reserves a clean naming pattern for future ports
  (`dc-go`, `dc-node`, `dc-rs`).

### Added

- **PyPI packaging** — `pyproject.toml` at repo root (hatchling backend)
  builds the `dynamitecircle` package from `py/dc.py`. The single file
  ships in the wheel as `dynamitecircle.py`, so installs give users
  `from dynamitecircle import DC` and a `dc` console script on PATH.
  Optional `[mcp]` extra installs the MCP server dependency. Version is
  read at build time from `DC_API_VERSION` so it stays in lockstep with
  the repo's existing version constant.
- **`main()` entry point** in `py/dc.py` — extracted from the
  `if __name__ == "__main__"` block so the `dc` console script
  (`pip install dynamitecircle` → `dc help`) can target it directly.
- **GitHub Actions publish workflow** at `.github/workflows/publish.yml`
  — builds wheel + sdist on every push, smoke-tests installs across
  Python 3.9 + 3.12 on Ubuntu / macOS / Windows, publishes to PyPI on
  every `v*` tag via OIDC trusted publishing (no API tokens stored),
  then auto-creates a GitHub Release with notes pulled from CHANGELOG.md.
- **README rewrite** — opens with "DC Official Client" + a paragraph
  about what the Dynamite Circle actually is (founded 2011, ~1,500
  founders, $100k+ revenue requirement) with inline links to
  dynamitecircle.com and the apply funnel, both UTM-tagged so we can
  track inbound from this repo. Removes the "multi-language client suite"
  framing — only the Python client exists today.
- **Pre-approval configs** for all three auto-discovery AI tools so users
  don't get per-tool-call approval prompts when they open this repo:
  - Claude Code: `.claude/settings.json` with `mcp__dc__*`,
    `Skill(dc *)`, `enableAllProjectMcpServers: true`
  - Codex CLI: `.codex/config.toml` with
    `default_tools_approval_mode = "approve"`
  - Gemini CLI: `.gemini/settings.json` with `trust: true`
- **`Agent Skill` row** in the README's "How it's exposed" table —
  acknowledges the SKILL.md auto-discovery path that 90% of users will
  actually use, alongside CLI / Python import / MCP server.

### Removed

- **Pin-to-commit guidance** from the README's "Update etiquette"
  section — the API moves fast enough that pinning is anti-recommended.
- **Hardcoded command counts** ("28 commands", "29 commands") replaced
  with "full Member API coverage" + a pointer to `help` for the live
  list. Counts went stale every time we shipped.
- **`dk_<userID>_<random>` format string** replaced with `dk_<api-key>`
  in user-facing docs — members shouldn't have to know the key's
  internal structure.

---

## [1.6.1] – 2026-05-02

### Added

- **`manifest.json`** at the repo root — MCPB schema 0.3
  ([MCP 2025-11 spec](https://modelcontextprotocol.io/specification/2025-11-25/changelog)).
  Carries `display_name`, `long_description`, `author`, `repository`,
  `license`, `capabilities`, `compatibility`, `user_config` blocks.
  Aligns the repo with the `.mcpb` bundle convention so we can ship
  installable bundles later.
- **MIT `LICENSE`** at the repo root. Repo is private today, but the
  license is in place if/when it opens up.
- **`dc/` symlink at the repo root** — shortcut pointing at
  `.claude/skills/dc/` (later inverted in the unreleased layout flip,
  but introduced here).

### Changed

- **`DC_API_VERSION`** bumped to 1.6.1 to match the deployed server API
  release.
- **README's "Three integration modes" → "How it's exposed"** with
  Agent Skill added as the primary integration.
- **Cross-platform** — explicit UTF-8 stdout/stderr reconfigure for
  legacy Windows `cmd.exe`; chmod-on-Windows note in `setup`; README
  "Platform support" section.

---

## [1.6.0] – 2026-04-30

### Added

- **MCP per-command JSON Schemas** — `@skill_command(args={...})` lets
  each command declare typed input schemas (types, required, enums,
  formats, descriptions). MCP clients now see rich autocomplete and
  validation instead of a `additionalProperties: true` fallback.
- **`mcpSchemas` check** in `self-test` — fails if any command is
  missing an `args=` schema, catching coverage drift.
- **Hive-style `emit()`** — ContextVar sink, `Result` wrapper. Commands
  can call `Runtime.emit(...)` (or pass dict/list for auto-JSON
  serialization) to send follow-up text to the calling agent. Surfaces
  to CLI stderr, MCP TextContent, or `result.emitted` for Python.
  JSON envelope `{ok, client, command, result, emitted}` when `--json`
  is set with non-empty emit.
- **Version-mismatch warning** — `DC_API_VERSION` constant. Every request
  sends `User-Agent: dc-py/<version>` and reads the server's
  `X-API-Version` response header. `_VersionTracker` warns once per
  process when the server is on a newer minor/major.

---

## [1.5.0] – 2026-04-30

### Added

- **Announcements** (2 commands):
  - `announcements` — cursor-paginated mixed feed across visible
    broadcast channels (DC, DCBKK, DCMEX, DC BLACK)
  - `announcements-latest` — one most-recent announcement per channel
- **Event extras** — 8 commands gated by an event ticket:
  - `event-schedule` — sessions grouped by day; wall-clock ISO time +
    IANA timezone (NOT real UTC — read both fields together)
  - `event-agenda` — your bookmarked sessions + joined meetups
  - `event-meetups` — approved member-organized meetups
  - `event-sponsors` — sponsors ordered by tier then display order
  - `session-attendees` — who else bookmarked a session
  - `meetup-attendees` — who else RSVP'd to a meetup
  - `session-bookmark` — add/remove a session from your agenda
  - `meetup-rsvp` — join/leave a meetup

---

## [1.3.0] – 2026-04-30

### Added

- **`limits` command** — wraps `/profile/limits`. Returns effective
  per-minute / per-day rate limits and current usage as JSON, so
  scripts get a structured snapshot without parsing `X-RateLimit-*`
  headers manually.
- **HTTP 429 retry** — `HttpClient` auto-retries on rate-limit responses.
  Wait time parsed from `Retry-After` (RFC 7231, preferred), then
  `X-RateLimit-Reset`, then "Try again in N seconds." regex from the
  body, then a 60-second fallback. Configurable via class attributes
  (`max_retries=1`, `max_retry_wait=120`, `fallback_retry_wait=60`).
  Emits a friendly `Rate limited (HTTP 429) — waiting Ns before retry…`
  message to stderr before sleeping; no silent multi-minute hangs.

---

## [1.0.0] – 2026-04-30

### Added

- **Initial scaffold** — `Dynamite-Circle-Builders/dc-official` private
  repo created with the single-file Python client at
  `.claude/skills/dc/dc_skill.py` (later moved to `dc/dc.py`).
- **28 commands** wrapping the public DC Member API — profile,
  trips (CRUD + overlaps), events + RSVP, virtual events + RSVP,
  tickets, invites, inbox, rooms, chapters, places lookup, locator
  digest. Plus `setup` (writes API key to skill-local `.env.dc`) and
  `self-test` (env + network + `/profile` end-to-end).
- **Three integration modes**:
  - CLI (`python3 dc_skill.py <command>`) — stdlib only
  - Python library (`from dc_skill import DCSkill`) — stdlib only
  - MCP server (`dc_skill.py --mcp`) — `pip install mcp` (optional, lazy import)
- **Auto-discovery configs** for Claude Code (`.mcp.json`),
  Codex CLI (`.codex/config.toml`), Gemini CLI (`GEMINI.md` symlink),
  GitHub Copilot (`.github/copilot-instructions.md`), and the
  `.agents/skills/` symlink for Codex skill discovery.
- **Output formats** — text (default, pretty JSON for dicts/lists),
  `--json` (canonical machine-readable), `--python` (eval-safe `repr`).
- **Cursor pagination** envelope `{items, count, cursor, has_more}`
  on every list-returning command. Non-paginated extras (e.g.
  `totalUnread` on `inbox`) pass through under `extra`.
- **Hive-inspired conventions**: two-class pattern (`DC` public wrapper
  + `_DCCore` private helper), `@skill_command(name=, help=, parser=)`
  decorator, space-form CLI flags, ArgHelpers + HttpClient utilities.
- **Cross-platform-safe** — every text-mode file op specifies
  `encoding="utf-8"`, atomic env-file write via `.tmp` + `replace()`,
  chmod 600 on `.env.dc` (no-op on Windows, documented).
- **No telemetry, no usage tracking, no error logging** — public-grade
  design intentionally stripped of internal Hive concerns.

---

[Unreleased]: https://github.com/dynamitecircle/dc/compare/v2.0.4...HEAD
[2.0.4]: https://github.com/dynamitecircle/dc/compare/v2.0.1...v2.0.4
[2.0.1]: https://github.com/dynamitecircle/dc/releases/tag/v2.0.1
[1.23.3]: https://github.com/dynamitecircle/dc/releases/tag/v1.23.3
[1.22.6]: https://github.com/dynamitecircle/dc/releases/tag/v1.22.6
[1.22.5]: https://github.com/dynamitecircle/dc/releases/tag/v1.22.5
[1.22.4]: https://github.com/dynamitecircle/dc/releases/tag/v1.22.4
[1.22.3]: https://github.com/dynamitecircle/dc/releases/tag/v1.22.3
[1.20.1]: https://github.com/dynamitecircle/dc/releases/tag/v1.20.1
[1.19.3]: https://github.com/dynamitecircle/dc/releases/tag/v1.19.3
[1.19.2]: https://github.com/dynamitecircle/dc/releases/tag/v1.19.2
[1.10.5]: https://github.com/dynamitecircle/dc/releases/tag/v1.10.5
[1.10.4]: https://github.com/dynamitecircle/dc/releases/tag/v1.10.4
[1.10.2]: https://github.com/dynamitecircle/dc/releases/tag/v1.10.2
[1.9.1]: https://github.com/dynamitecircle/dc/releases/tag/v1.9.1
[1.8.1]: https://github.com/dynamitecircle/dc/releases/tag/v1.8.1
[1.7.1]: https://github.com/dynamitecircle/dc/releases/tag/v1.7.1
[1.6.3]: https://github.com/dynamitecircle/dc/releases/tag/v1.6.3
[1.6.2]: https://github.com/dynamitecircle/dc/releases/tag/v1.6.2
[1.6.1]: https://github.com/dynamitecircle/dc/releases/tag/v1.6.1
[1.6.0]: https://github.com/dynamitecircle/dc/releases/tag/v1.6.0
[1.5.0]: https://github.com/dynamitecircle/dc/releases/tag/v1.5.0
[1.3.0]: https://github.com/dynamitecircle/dc/releases/tag/v1.3.0
[1.0.0]: https://github.com/dynamitecircle/dc/releases/tag/v1.0.0
