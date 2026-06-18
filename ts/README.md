# DC TypeScript Client

Official TypeScript SDK for the public [Dynamite Circle Member API](https://www.dynamitecircle.com/developers/).

Use it from trusted server-side TypeScript and Node.js projects to read and act on your own DC membership data: profile, trips, events, virtual events, tickets, invites, inbox, rooms, chapters, places, search, follows, calendar feed settings, notifications, and the weekly locator digest.

This package is a library only. It does not include the Python client's CLI, Agent Skill, or MCP server. If you want shell commands, a local MCP server, or an AI-agent skill, use the Python package: [`pip install dynamitecircle`](https://pypi.org/project/dynamitecircle/). If you want zero install MCP, use the hosted endpoint at `https://api.dynamitecircle.com/mcp`.

## About the Dynamite Circle

[Dynamite Circle](https://www.dynamitecircle.com/?utm_medium=npm&utm_source=@dynamitecircle/dc&utm_campaign=client-package) is a private community for location-independent founders running profitable businesses around the world.

Members use DC to meet other founders, attend vetted in-person events like [DCBKK](https://www.dynamitecircle.com/dcbkk/?utm_medium=npm&utm_source=@dynamitecircle/dc&utm_campaign=client-package) and DCMEX, coordinate trips, find people in cities they are visiting, and keep up with private community rooms and announcements.

DC is open to applications from founders running location-independent businesses doing $100k+ in annual revenue. Every application is personally reviewed by the team. [Start an application here](https://dc.dynamitecircle.com/account/apply?utm_medium=npm&utm_source=@dynamitecircle/dc&utm_campaign=client-package&referrer=npmjs.com) if that sounds like you.

## Install

```bash
npm install @dynamitecircle/dc
```

Requirements:

- Node.js 20+
- A DC account with a personal Member API key
- Server-side code only; do not expose a `dk_...` key in browser JavaScript

## Get an API key

In your DC account, open your profile dropdown and choose **DC Member API Key**. Copy the key that starts with `dk_`.

API keys are personal credentials. Requests are scoped to the member who owns the key, and write methods mutate that member's DC account.

## Quick Start

```ts
import { DC, type TripCreateInput } from "@dynamitecircle/dc";

const dc = new DC({ apiKey: process.env.DC_API_KEY! });

const profile = await dc.profile.get();
const trips = await dc.trips.list({ limit: 10 });

const trip: TripCreateInput = {
  placeID: "ChIJi3lwCZyTC0cRkEAWZg-vAAQ",
  startDate: "2026-07-01",
  endDate: "2026-07-05",
  note: "Looking for founder coffees and coworking recommendations.",
};

await dc.trips.create(trip);

console.log(profile, trips);
```

Override the API URL for local API development:

```ts
const dc = new DC({
  apiKey: process.env.DC_API_KEY!,
  baseUrl: "http://localhost:8080",
});
```

## What You Can Do

The SDK wraps the same public Member API as the Python client:

- Profile: read and update your member profile
- Trips: create, update, delete, refresh discovery, and see who overlaps with you
- Events: list events, RSVP, view attendees, schedules, agendas, meetups, sponsors, and shared free slots
- Virtual events: list sessions, inspect details, and RSVP
- Tickets and invites: list tickets, send invites, and fetch your referral permacode
- Inbox and rooms: read rooms/messages/summaries, browse public rooms, and manage room subscription state
- Locator: read the weekly digest and update locator email settings
- Places and chapters: search places, list chapters, and inspect chapter members/visitors
- Search and discovery: search profiles, rooms, messages, events, chapters, and use AI-powered profile matching
- Account settings: membership, invoices, notifications, calendar feed settings, follows, limits, announcements, and issue reports

Example reads:

```ts
const events = await dc.events.list({ limit: 5 });
const chapters = await dc.chapters.list({ limit: 10 });
const matches = await dc.discovery.profileMatch({
  query: "DCers in Lisbon who run SaaS companies",
  limit: 5,
});
```

Example writes:

```ts
await dc.profile.update({ headline: "Founder at Acme" });
await dc.events.rsvp("event_123", "yes");
await dc.rooms.subscribe("room_123");
```

## API Reference

The human reference for every endpoint, parameter, and response shape is regenerated on every API deploy:

- [DC Member API reference](https://www.dynamitecircle.com/developers/)
- [OpenAPI JSON](https://api.dynamitecircle.com/openapi.json)
- [Hosted MCP endpoint](https://api.dynamitecircle.com/mcp)

For lower-level calls or a newly released endpoint before the SDK surface catches up, use `dc.request()` directly:

```ts
const payload = await dc.request("GET", "/profile");
```

## TypeScript Surface

The public SDK is hand-written for a practical TypeScript API, not generated wholesale from OpenAPI. The pinned OpenAPI file is used for validation and parity checks so the Python client, TypeScript client, and API contract stay aligned.

The package exports typed inputs for common writes, including:

- `ProfileUpdateInput`
- `TripCreateInput`
- `TripUpdateInput`
- `EventFreeSlotsInput`
- `InviteCreateInput`
- `CalendarUpdateInput`
- `LocatorSettingsUpdateInput`
- `NotificationsUpdateInput`
- `ProfileMatchInput`
- `ReportIssueInput`

Errors from API error envelopes throw `DCAPIError`, which includes the HTTP status, API error code, and response payload when available.

```ts
import { DC, DCAPIError } from "@dynamitecircle/dc";

try {
  await new DC({ apiKey: process.env.DC_API_KEY! }).profile.get();
} catch (error) {
  if (error instanceof DCAPIError) {
    console.error(error.status, error.code, error.payload);
  }
}
```

## Versioning

The package version matches the pinned Member API contract in `../contracts/openapi.json`. Contract tests verify that this TypeScript client, the Python client, and the pinned OpenAPI snapshot all stay in step.

The client also watches the `X-API-Version` response header. If the live API reports a newer major/minor version than this package targets, the SDK warns once by default. Pass `onVersionDrift` if you want to route that warning into your own logging:

```ts
const dc = new DC({
  apiKey: process.env.DC_API_KEY!,
  onVersionDrift: ({ currentApiVersion, targetApiVersion }) => {
    console.warn({ currentApiVersion, targetApiVersion });
  },
});
```

## Publishing

This package is published from GitHub Actions on `v*` tags via npm Trusted Publishing.

Trusted publisher settings:

- Package: `@dynamitecircle/dc`
- Owner/repo: `dynamitecircle/dc`
- Workflow: `publish-npm.yml`
- Environment: `npm`

Local publishing should only be used as a fallback.

## Links

- [Dynamite Circle](https://www.dynamitecircle.com/?utm_medium=npm&utm_source=@dynamitecircle/dc&utm_campaign=client-package)
- [Apply to DC](https://dc.dynamitecircle.com/account/apply?utm_medium=npm&utm_source=@dynamitecircle/dc&utm_campaign=client-package&referrer=npmjs.com)
- [API reference](https://www.dynamitecircle.com/developers/)
- [GitHub repo](https://github.com/dynamitecircle/dc)
- [Python package](https://pypi.org/project/dynamitecircle/)
