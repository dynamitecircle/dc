# DC TypeScript Client

Official TypeScript client for the public Dynamite Circle Member API.

This package is a library only. It does not include the Python client's CLI,
Agent Skill, or MCP server.

```bash
npm install @dynamitecircle/dc
```

```ts
import { DC, type TripCreateInput } from "@dynamitecircle/dc";

const dc = new DC({ apiKey: process.env.DC_API_KEY! });

const profile = await dc.profile.get();
const trips = await dc.trips.list({ limit: 10 });

const trip: TripCreateInput = {
  placeID: "ChIJi3lwCZyTC0cRkEAWZg-vAAQ",
  startDate: "2026-07-01",
  endDate: "2026-07-05",
};
await dc.trips.create(trip);
```

API keys are personal credentials. Use this package from trusted server-side
TypeScript projects; do not expose a `dk_...` key in browser JavaScript.

## Versioning

The package version matches the pinned Member API contract in
`../contracts/openapi.json`. Contract tests verify that this TypeScript client,
the Python client, and the pinned OpenAPI snapshot all stay in step.

## Publishing

The package is published from GitHub Actions on `v*` tags via npm Trusted
Publishing. Configure the trusted publisher in npm for:

- Package: `@dynamitecircle/dc`
- Owner/repo: `dynamitecircle/dc`
- Workflow: `publish-npm.yml`
- Environment: `npm`

Local publishing should only be used as a fallback.

## Types

The public SDK is hand-written, not generated. The package exports practical
input types for common writes, including:

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

The pinned OpenAPI file is used for validation and parity checks, not to
generate the public method surface.
