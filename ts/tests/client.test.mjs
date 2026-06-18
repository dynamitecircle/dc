import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { DC, DCAPIError, DC_API_VERSION } from "../dist/index.js";

const openapi = JSON.parse(fs.readFileSync("../contracts/openapi.json", "utf8"));
const operationMap = JSON.parse(fs.readFileSync("../contracts/operation-map.json", "utf8"));
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));

function mockFetch(handler) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ init, url: String(url) });
    const response = await handler(String(url), init, calls.length);
    return new Response(JSON.stringify(response.body), {
      headers: response.headers,
      status: response.status ?? 200,
    });
  };
  return { calls, fetch };
}

function getPath(obj, path) {
  return path.split(".").reduce((current, part) => current?.[part], obj);
}

function pathParams(path) {
  return [...path.matchAll(/\{([^}]+)\}/g)].map((match) => match[1]);
}

function pathValue(name) {
  return {
    cityID: "city_123",
    eventID: "event_123",
    meetupID: "meetup_123",
    placeID: "place_123",
    roomID: "room_123",
    sessionID: "session_123",
    tripID: "trip_123",
    type: "daily",
    userID: "user_123",
  }[name] ?? `${name}_123`;
}

function expectedPathname(path) {
  return path.replaceAll(/\{([^}]+)\}/g, (_match, name) =>
    encodeURIComponent(pathValue(name)),
  );
}

function fixtureArgs(operation) {
  const params = pathParams(operation.path).map(pathValue);

  switch (operation.typescriptMethod) {
    case "profile.update":
      return [{ headline: "Founder at Acme" }];
    case "trips.create":
      return [{ endDate: "2026-07-05", placeID: "place_123", startDate: "2026-07-01" }];
    case "trips.update":
      return [...params, { note: "Updated trip" }];
    case "events.rsvp":
    case "virtualEvents.rsvp":
      return [...params, "yes"];
    case "events.sessionBookmark":
    case "events.meetupRsvp":
      return [...params, true];
    case "events.agendas":
      return [...params, ["user_1", "user_2"]];
    case "events.freeSlots":
      return [...params, { minDurationMinutes: 30, userIDs: ["user_1"] }];
    case "invites.create":
      return [{ email: "new@example.com", fullName: "New Friend" }];
    case "locator.updateSettings":
      return [{ enabled: true }];
    case "places.search":
      return [{ limit: 5, q: "Lisbon" }];
    case "notifications.update":
      return [{ categories: { message: { push: true } } }];
    case "calendar.update":
      return [{ includeMyTrips: true }];
    case "discovery.profileMatch":
      return [{ limit: 5, query: "DCers in Lisbon who run SaaS" }];
    case "issues.report":
      return [{ text: "SDK smoke report" }];
  }

  if (operation.typescriptMethod.startsWith("search.")) {
    return [{ limit: 5, q: "founder" }];
  }

  return params;
}

test("package and exported versions match pinned OpenAPI", () => {
  assert.equal(openapi.info.version, "2.0.4");
  assert.equal(packageJson.version, openapi.info.version);
  assert.equal(DC_API_VERSION, openapi.info.version);
});

test("operation map covers every pinned OpenAPI operation", () => {
  const openapiOperationIds = new Set();
  for (const pathItem of Object.values(openapi.paths)) {
    for (const [method, operation] of Object.entries(pathItem)) {
      if (["get", "post", "patch", "put", "delete"].includes(method)) {
        openapiOperationIds.add(operation.operationId);
      }
    }
  }

  const mapped = new Set(operationMap.operations.map((item) => item.operationId));
  assert.deepEqual(mapped, openapiOperationIds);
});

test("every mapped TypeScript method exists on the client", () => {
  const client = new DC({ apiKey: "dk_test", fetch: async () => new Response("{}") });
  for (const operation of operationMap.operations) {
    assert.equal(
      typeof getPath(client, operation.typescriptMethod),
      "function",
      operation.typescriptMethod,
    );
  }
});

test("every mapped TypeScript method routes to the pinned OpenAPI operation", async () => {
  for (const operation of operationMap.operations) {
    const { calls, fetch } = mockFetch(async () => ({
      body: { data: {}, ok: true },
    }));
    const client = new DC({ apiKey: "dk_test", baseUrl: "https://example.test", fetch });
    const method = getPath(client, operation.typescriptMethod);

    await method(...fixtureArgs(operation));

    assert.equal(calls.length, 1, operation.typescriptMethod);
    assert.equal(calls[0].init.method, operation.method, operation.typescriptMethod);
    assert.equal(
      new URL(calls[0].url).pathname,
      expectedPathname(operation.path),
      operation.typescriptMethod,
    );
  }
});

test("request expands path params, serializes query, and sends auth headers", async () => {
  const { calls, fetch } = mockFetch(async () => ({
    body: { data: { ok: true }, ok: true },
  }));
  const client = new DC({ apiKey: "dk_test", baseUrl: "https://example.test", fetch });

  await client.rooms.messages("room 1", { before: "abc", limit: 5 });

  assert.equal(
    calls[0].url,
    "https://example.test/rooms/room%201/messages?before=abc&limit=5",
  );
  const headers = new Headers(calls[0].init.headers);
  assert.equal(headers.get("Authorization"), "Bearer dk_test");
  assert.equal(headers.get("Accept"), "application/json");
  assert.equal(headers.get("User-Agent"), "dc-ts/2.0.4");
});

test("request unwraps standard {ok,data} envelopes", async () => {
  const { fetch } = mockFetch(async () => ({
    body: { data: { displayName: "Jane Doe" }, ok: true },
  }));
  const client = new DC({ apiKey: "dk_test", fetch });

  assert.deepEqual(await client.profile.get(), { displayName: "Jane Doe" });
});

test("typed write helpers serialize JSON bodies", async () => {
  const { calls, fetch } = mockFetch(async () => ({
    body: { data: { tripID: "trip_1" }, ok: true },
  }));
  const client = new DC({ apiKey: "dk_test", baseUrl: "https://example.test", fetch });

  await client.trips.create({
    endDate: "2026-07-05",
    note: "DC week",
    placeID: "place_123",
    startDate: "2026-07-01",
  });

  assert.equal(calls[0].url, "https://example.test/trips");
  const headers = new Headers(calls[0].init.headers);
  assert.equal(headers.get("Content-Type"), "application/json");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    endDate: "2026-07-05",
    note: "DC week",
    placeID: "place_123",
    startDate: "2026-07-01",
  });
});

test("typed profile update preserves canonical Member API field names", async () => {
  const { calls, fetch } = mockFetch(async () => ({
    body: { data: { updated: true }, ok: true },
  }));
  const client = new DC({ apiKey: "dk_test", baseUrl: "https://example.test", fetch });

  await client.profile.update({
    businessIndustry: "SaaS & Tech",
    teamSizeIsPrivate: true,
  });

  assert.deepEqual(JSON.parse(calls[0].init.body), {
    businessIndustry: "SaaS & Tech",
    teamSizeIsPrivate: true,
  });
});

test("request throws DCAPIError for API error envelopes", async () => {
  const { fetch } = mockFetch(async () => ({
    body: { error: "unauthorized", message: "Nope", ok: false },
    status: 401,
  }));
  const client = new DC({ apiKey: "dk_test", fetch });

  await assert.rejects(client.profile.get(), (error) => {
    assert.ok(error instanceof DCAPIError);
    assert.equal(error.status, 401);
    assert.equal(error.code, "unauthorized");
    return true;
  });
});

test("client reports API major/minor version drift once", async () => {
  const drifts = [];
  const { fetch } = mockFetch(async () => ({
    body: { data: {}, ok: true },
    headers: { "X-API-Version": "2.1.0" },
  }));
  const client = new DC({
    apiKey: "dk_test",
    fetch,
    onVersionDrift: (drift) => drifts.push(drift),
  });

  await client.profile.get();
  await client.profile.get();

  assert.deepEqual(drifts, [
    { currentApiVersion: "2.1.0", targetApiVersion: "2.0.4" },
  ]);
});
