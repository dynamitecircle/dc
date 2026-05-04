# Changelog

All notable changes to the **`dc` client repo** (formerly `dc-official` /
`dc-py`) are listed here. The version
numbers below track `DC_API_VERSION` in [`py/dc.py`](py/dc.py), which is
deliberately aligned with the DC Member API server version it was last
verified against. Patch bumps from the server are silent; minor or major
bumps surface a one-shot stderr warning when this client falls behind.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/) for
the public Python API surface (`dc.DC`, `dc.DCError`, `dc.Result`,
`dc.Runtime`).

---

## [Unreleased]

_Nothing yet._

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

[Unreleased]: https://github.com/dynamitecircle/dc/compare/v1.10.2...HEAD
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
