import { DCAPIError } from "./errors.js";
import {
  DC_API_VERSION,
  DEFAULT_API_URL,
  DEFAULT_USER_AGENT,
} from "./version.js";
import type {
  DCClientOptions,
  CalendarUpdateInput,
  EventFreeSlotsInput,
  HTTPMethod,
  InviteCreateInput,
  ListOptions,
  LocatorSettingsUpdateInput,
  NotificationsUpdateInput,
  PastListOptions,
  ProfileMatchInput,
  ProfileUpdateInput,
  QueryParams,
  ReportIssueInput,
  RequestBody,
  RequestOptions,
  RSVPStatus,
  SearchOptions,
  TripCreateInput,
  TripUpdateInput,
  VersionDrift,
} from "./types.js";

export class DC {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof globalThis.fetch;
  private readonly onVersionDrift: ((drift: VersionDrift) => void) | undefined;
  private readonly sendUserAgent: boolean;
  private readonly userAgent: string;
  private versionDriftWarned = false;

  constructor(options: DCClientOptions) {
    if (!options.apiKey.startsWith("dk_")) {
      throw new Error("DC API keys must start with 'dk_'.");
    }
    if (!options.fetch && typeof globalThis.fetch !== "function") {
      throw new Error("A fetch implementation is required in this runtime.");
    }

    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl ?? DEFAULT_API_URL;
    this.fetchImpl = options.fetch ?? globalThis.fetch;
    this.onVersionDrift = options.onVersionDrift;
    this.sendUserAgent = options.sendUserAgent ?? true;
    this.userAgent = options.userAgent ?? DEFAULT_USER_AGENT;
  }

  async request<T = unknown>(
    method: HTTPMethod,
    path: string,
    options: RequestOptions = {},
  ): Promise<T> {
    const init: RequestInit = {
      headers: this.headers(options.body !== undefined),
      method,
    };
    if (options.body !== undefined) {
      init.body = JSON.stringify(options.body);
    }

    const response = await this.fetchImpl(this.buildUrl(path, options), init);
    this.observeVersion(response);

    const payload = await parseJson(response);
    if (!response.ok) {
      throw DCAPIError.fromPayload(payload, response);
    }

    if (isRecord(payload) && payload.ok === false) {
      throw DCAPIError.fromPayload(payload, response);
    }

    if (isRecord(payload) && payload.ok === true && "data" in payload) {
      return (payload.data ?? {}) as T;
    }

    return payload as T;
  }

  readonly announcements = {
    list: (query?: ListOptions) =>
      this.request("GET", "/announcements", { query }),
    latest: () => this.request("GET", "/announcements/latest"),
  };

  readonly profile = {
    get: () => this.request("GET", "/profile"),
    update: (body: ProfileUpdateInput) =>
      this.request("PATCH", "/profile", { body }),
  };

  readonly trips = {
    list: (query?: PastListOptions) =>
      this.request("GET", "/trips", { query }),
    create: (body: TripCreateInput) => this.request("POST", "/trips", { body }),
    update: (tripID: string, body: TripUpdateInput) =>
      this.request("PATCH", "/trips/{tripID}", { body, path: { tripID } }),
    delete: (tripID: string) =>
      this.request("DELETE", "/trips/{tripID}", { path: { tripID } }),
    get: (tripID: string) =>
      this.request("GET", "/trips/{tripID}", { path: { tripID } }),
    overlaps: (query?: ListOptions) =>
      this.request("GET", "/trips/overlaps", { query }),
    refresh: (tripID: string) =>
      this.request("POST", "/trips/{tripID}/refresh", { path: { tripID } }),
    discovery: (tripID: string, query?: { include?: string }) =>
      this.request("GET", "/trips/{tripID}/discovery", {
        path: { tripID },
        query,
      }),
  };

  readonly events = {
    list: (query?: PastListOptions) =>
      this.request("GET", "/events", { query }),
    get: (eventID: string) =>
      this.request("GET", "/events/{eventID}", { path: { eventID } }),
    attendees: (eventID: string, query?: ListOptions) =>
      this.request("GET", "/events/{eventID}/attendees", {
        path: { eventID },
        query,
      }),
    rsvp: (eventID: string, status: RSVPStatus) =>
      this.request("POST", "/events/{eventID}/rsvp", {
        body: { status },
        path: { eventID },
      }),
    schedule: (eventID: string) =>
      this.request("GET", "/events/{eventID}/schedule", {
        path: { eventID },
      }),
    agenda: (eventID: string) =>
      this.request("GET", "/events/{eventID}/agenda", {
        path: { eventID },
      }),
    userAgenda: (eventID: string, userID: string) =>
      this.request("GET", "/events/{eventID}/agenda/{userID}", {
        path: { eventID, userID },
      }),
    sessionAttendees: (eventID: string, sessionID: string) =>
      this.request(
        "GET",
        "/events/{eventID}/schedule/{sessionID}/attendees",
        { path: { eventID, sessionID } },
      ),
    meetups: (eventID: string) =>
      this.request("GET", "/events/{eventID}/meetups", {
        path: { eventID },
      }),
    meetupAttendees: (eventID: string, meetupID: string) =>
      this.request(
        "GET",
        "/events/{eventID}/meetups/{meetupID}/attendees",
        { path: { eventID, meetupID } },
      ),
    sponsors: (eventID: string) =>
      this.request("GET", "/events/{eventID}/sponsors", {
        path: { eventID },
      }),
    sessionBookmark: (
      eventID: string,
      sessionID: string,
      bookmarked = true,
    ) =>
      this.request("POST", "/events/{eventID}/schedule/{sessionID}/bookmark", {
        body: { bookmarked },
        path: { eventID, sessionID },
      }),
    meetupRsvp: (eventID: string, meetupID: string, joined = true) =>
      this.request("POST", "/events/{eventID}/meetups/{meetupID}/rsvp", {
        body: { joined },
        path: { eventID, meetupID },
      }),
    agendas: (eventID: string, userIDs: string[] | string) =>
      this.request("GET", "/events/{eventID}/agendas", {
        path: { eventID },
        query: { userIDs: Array.isArray(userIDs) ? userIDs.join(",") : userIDs },
      }),
    freeSlots: (
      eventID: string,
      body: EventFreeSlotsInput,
    ) =>
      this.request("POST", "/events/{eventID}/free-slots", {
        body,
        path: { eventID },
      }),
  };

  readonly virtualEvents = {
    list: (query?: PastListOptions) =>
      this.request("GET", "/virtual-events", { query }),
    get: (sessionID: string) =>
      this.request("GET", "/virtual-events/{sessionID}", {
        path: { sessionID },
      }),
    rsvp: (sessionID: string, status: RSVPStatus) =>
      this.request("POST", "/virtual-events/{sessionID}/rsvp", {
        body: { status },
        path: { sessionID },
      }),
  };

  readonly tickets = {
    list: (query?: ListOptions & { status?: string }) =>
      this.request("GET", "/tickets", { query }),
  };

  readonly invites = {
    list: (query?: ListOptions) => this.request("GET", "/invites", { query }),
    create: (body: InviteCreateInput) =>
      this.request("POST", "/invites", { body }),
    permacode: () => this.request("GET", "/invites/permacode"),
  };

  readonly inbox = {
    unread: (query?: ListOptions) =>
      this.request("GET", "/inbox/unread", { query }),
  };

  readonly rooms = {
    list: (query?: ListOptions) => this.request("GET", "/rooms", { query }),
    inbox: (type: string, query?: ListOptions) =>
      this.request("GET", "/rooms/inbox/{type}", { path: { type }, query }),
    browse: (type: string, query?: ListOptions) =>
      this.request("GET", "/rooms/browse/{type}", { path: { type }, query }),
    get: (roomID: string) =>
      this.request("GET", "/rooms/{roomID}", { path: { roomID } }),
    summary: (roomID: string, type: "daily" | "weekly") =>
      this.request("GET", "/rooms/{roomID}/summary/{type}", {
        path: { roomID, type },
      }),
    summaries: (
      roomID: string,
      type: "daily" | "weekly",
      query?: ListOptions,
    ) =>
      this.request("GET", "/rooms/{roomID}/summaries/{type}", {
        path: { roomID, type },
        query,
      }),
    messages: (roomID: string, query?: { before?: string; limit?: number }) =>
      this.request("GET", "/rooms/{roomID}/messages", {
        path: { roomID },
        query,
      }),
    subscribe: (roomID: string) => this.roomMutation(roomID, "subscribe"),
    unsubscribe: (roomID: string) => this.roomMutation(roomID, "unsubscribe"),
    mute: (roomID: string) => this.roomMutation(roomID, "mute"),
    unmute: (roomID: string) => this.roomMutation(roomID, "unmute"),
    archive: (roomID: string) => this.roomMutation(roomID, "archive"),
    unarchive: (roomID: string) => this.roomMutation(roomID, "unarchive"),
    pin: (roomID: string) => this.roomMutation(roomID, "pin"),
    unpin: (roomID: string) => this.roomMutation(roomID, "unpin"),
  };

  readonly locator = {
    digest: (query?: { sections?: string }) =>
      this.request("GET", "/locator/digest", { query }),
    settings: () => this.request("GET", "/locator/settings"),
    updateSettings: (body: LocatorSettingsUpdateInput) =>
      this.request("PATCH", "/locator/settings", { body }),
  };

  readonly places = {
    search: (query: { limit?: number; q: string }) =>
      this.request("GET", "/places/search", { query }),
    get: (placeID: string) =>
      this.request("GET", "/places/{placeID}", { path: { placeID } }),
  };

  readonly chapters = {
    list: (query?: ListOptions) => this.request("GET", "/chapters", { query }),
    get: (cityID: string) =>
      this.request("GET", "/chapters/{cityID}", { path: { cityID } }),
  };

  readonly membership = {
    get: () => this.request("GET", "/membership"),
    invoices: (query?: { limit?: number }) =>
      this.request("GET", "/membership/invoices", { query }),
  };

  readonly notifications = {
    get: () => this.request("GET", "/notifications"),
    update: (body: NotificationsUpdateInput) =>
      this.request("PATCH", "/notifications", { body }),
  };

  readonly calendar = {
    get: () => this.request("GET", "/calendar"),
    update: (body: CalendarUpdateInput) =>
      this.request("PATCH", "/calendar", { body }),
  };

  readonly limits = {
    get: () => this.request("GET", "/limits"),
  };

  readonly follows = {
    profiles: {
      list: () => this.request("GET", "/follows/profiles"),
      follow: (userID: string) =>
        this.request("POST", "/follows/profiles/{userID}", {
          path: { userID },
        }),
      unfollow: (userID: string) =>
        this.request("DELETE", "/follows/profiles/{userID}", {
          path: { userID },
        }),
    },
    chapters: {
      list: () => this.request("GET", "/follows/chapters"),
      follow: (cityID: string) =>
        this.request("POST", "/follows/chapters/{cityID}", {
          path: { cityID },
        }),
      unfollow: (cityID: string) =>
        this.request("DELETE", "/follows/chapters/{cityID}", {
          path: { cityID },
        }),
    },
  };

  readonly discovery = {
    profileMatch: (body: ProfileMatchInput) =>
      this.request("POST", "/profile-match", { body }),
  };

  readonly issues = {
    report: (body: ReportIssueInput) =>
      this.request("POST", "/report-issue", { body }),
  };

  readonly search = {
    all: (query: QueryParams & { q: string }) =>
      this.request("GET", "/search", { query }),
    profiles: (query: SearchOptions & { q: string }) =>
      this.request("GET", "/search/profiles", { query }),
    rooms: (query: SearchOptions & { q: string; type?: string; userID?: string }) =>
      this.request("GET", "/search/rooms", { query }),
    messages: (
      query: SearchOptions & { q: string; roomID?: string; userID?: string },
    ) => this.request("GET", "/search/messages", { query }),
    events: (
      query: SearchOptions & {
        cityID?: string;
        country?: string;
        q: string;
        since?: string;
        until?: string;
        userID?: string;
      },
    ) => this.request("GET", "/search/events", { query }),
    chapters: (query: SearchOptions & { q: string }) =>
      this.request("GET", "/search/chapters", { query }),
  };

  private roomMutation(roomID: string, action: string): Promise<unknown> {
    return this.request("POST", `/rooms/{roomID}/${action}`, {
      path: { roomID },
    });
  }

  private headers(hasBody: boolean): Headers {
    const headers = new Headers();
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${this.apiKey}`);
    if (hasBody) {
      headers.set("Content-Type", "application/json");
    }
    if (this.sendUserAgent) {
      headers.set("User-Agent", this.userAgent);
    }
    return headers;
  }

  private buildUrl(path: string, options: RequestOptions): string {
    const expandedPath = expandPath(path, options.path);
    const url = new URL(expandedPath, this.baseUrl);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value === undefined || value === null || value === "") {
        continue;
      }
      if (Array.isArray(value)) {
        url.searchParams.set(key, value.join(","));
      } else {
        url.searchParams.set(key, String(value));
      }
    }
    return url.toString();
  }

  private observeVersion(response: Response): void {
    if (this.versionDriftWarned) {
      return;
    }

    const currentApiVersion = response.headers.get("X-API-Version");
    if (!currentApiVersion || !isApiAhead(currentApiVersion, DC_API_VERSION)) {
      return;
    }

    this.versionDriftWarned = true;
    const drift = {
      currentApiVersion,
      targetApiVersion: DC_API_VERSION,
    };
    if (this.onVersionDrift) {
      this.onVersionDrift(drift);
      return;
    }

    console.warn(
      `DC API has new features available (current API ${currentApiVersion}, this package targets API ${DC_API_VERSION}).`,
    );
  }
}

async function parseJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    if (response.ok) {
      return text;
    }
    return { error: "invalid_json", message: text };
  }
}

function expandPath(path: string, params: Record<string, string | number> = {}): string {
  return path.replaceAll(/\{([^}]+)\}/g, (_match, key: string) => {
    const value = params[key];
    if (value === undefined || value === null || value === "") {
      throw new Error(`Missing path parameter: ${key}`);
    }
    return encodeURIComponent(String(value));
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isApiAhead(apiVersion: string, targetApiVersion: string): boolean {
  const api = parseSemver(apiVersion);
  const target = parseSemver(targetApiVersion);
  if (!api || !target) {
    return false;
  }
  return api[0] > target[0] || (api[0] === target[0] && api[1] > target[1]);
}

function parseSemver(version: string): [number, number, number] | null {
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(version);
  if (!match) {
    return null;
  }
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}
