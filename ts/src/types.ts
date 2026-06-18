export type HTTPMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | Array<string | number | boolean>;

export type QueryParams = Record<string, QueryValue>;
export type PathParams = Record<string, string | number>;
export type RequestBody = unknown;

export interface RequestOptions {
  body?: RequestBody | undefined;
  path?: PathParams | undefined;
  query?: QueryParams | undefined;
}

export interface DCClientOptions {
  apiKey: string;
  baseUrl?: string;
  fetch?: typeof globalThis.fetch;
  onVersionDrift?: (drift: VersionDrift) => void;
  sendUserAgent?: boolean;
  userAgent?: string;
}

export interface VersionDrift {
  currentApiVersion: string;
  targetApiVersion: string;
}

export interface ListOptions {
  [key: string]: QueryValue;
  cursor?: string;
  limit?: number;
}

export interface PastListOptions extends ListOptions {
  past?: boolean;
}

export interface SearchOptions {
  [key: string]: QueryValue;
  limit?: number;
  page?: number;
}

export type RSVPStatus = "yes" | "maybe" | "no";

export type BusinessIndustry =
  | "SaaS & Tech"
  | "Marketing Agency"
  | "Productized Services"
  | "Ecommerce & Amazon"
  | "Courses and Info Products"
  | "Affiliate, Content Creation, or Ad Revenue"
  | "Professional Services & Industry Specific Consulting"
  | "Real Estate and Investing"
  | "Coaching"
  | "Other";

export type AnnualRevenue =
  | "No real income yet, it's still getting off the ground."
  | "I recently exited a business."
  | "$10K+"
  | "$50K+"
  | "$100K+"
  | "$250K+"
  | "$300K+"
  | "$600K+"
  | "$1M+"
  | "$2M+"
  | "$3M+"
  | "$4M+"
  | "$7M+"
  | "$10M+"
  | "$20M+"
  | "$35M+"
  | "$60M+"
  | "$100M+"
  | "Prefer not to say";

export type TeamSize =
  | "None"
  | "1-2"
  | "3-5"
  | "6-9"
  | "10-14"
  | "15-19"
  | "20-34"
  | "35-49"
  | "50-74"
  | "75-99"
  | "100+"
  | "Prefer not to say";

export type Diet =
  | "No Restrictions"
  | "Vegan"
  | "Vegetarian"
  | "Gluten-Free"
  | "Dairy/Lactose-Free";

export type ShirtSize = "XS" | "S" | "M" | "L" | "XL" | "XXL" | "XXXL";

export type YearsInBusiness =
  | "Less than one year"
  | "1-2 years"
  | "3-6 years"
  | "7-9 years"
  | "10-15 years"
  | "15-20 years"
  | "More than 20 years";

export type Gender = "Man" | "Woman" | "Non-binary" | "Prefer not to say";

export interface ProfileUpdateInput {
  annualRevenue?: AnnualRevenue;
  annualRevenueIsPrivate?: boolean;
  askMeAnythingTopics?: string;
  businessDescription?: string;
  businessIndustry?: BusinessIndustry;
  businessName?: string;
  businessWebsite?: string;
  currentChallenge?: string;
  diet?: Diet;
  expertise?: string;
  facebook?: string;
  focusmate?: string;
  github?: string;
  headline?: string;
  hobbies?: string;
  instagram?: string;
  linkedin?: string;
  nickname?: string;
  otherBusinesses?: string;
  peopleOfInterest?: string;
  peopleOfInterestIsPrivate?: boolean;
  previousBusinesses?: string;
  relevantLocations?: string;
  shirtSize?: ShirtSize;
  spouseName?: string;
  teamSize?: TeamSize;
  teamSizeIsPrivate?: boolean;
  twitter?: string;
  whatsApp?: string;
  yearsInBusiness?: YearsInBusiness;
}

export interface TripPointInput {
  note: string;
  noteHTML?: string;
  placeID?: string;
}

export type TripCreateInput =
  | {
      endDate: string;
      eventID: string;
      note?: string;
      placeID?: never;
      points?: TripPointInput[];
      startDate: string;
    }
  | {
      endDate: string;
      eventID?: never;
      note?: string;
      placeID: string;
      points?: TripPointInput[];
      startDate: string;
    };

export interface TripUpdateInput {
  endDate?: string;
  eventID?: string | null;
  note?: string;
  placeID?: string;
  points?: TripPointInput[];
  startDate?: string;
}

export interface InviteCreateInput {
  email: string;
  fullName: string;
  whyDC?: string;
}

export interface EventFreeSlotsInput {
  eventDayDate?: string;
  minDurationMinutes?: number;
  userIDs: string[];
}

export interface CalendarUpdateInput {
  includeDCBlackEvents?: boolean;
  includeEventAgenda?: boolean;
  includeFlagshipEvents?: boolean;
  includeFollowedChapterEvents?: boolean;
  includeHomeChapterEvents?: boolean;
  includeMyTickets?: boolean;
  includeMyTrips?: boolean;
  includeOtherChapterEvents?: boolean;
  includeVirtualCalls?: boolean;
}

export interface LocatorSettingsUpdateInput {
  enabled?: boolean;
  events?: boolean;
  tickets?: boolean;
  trips?: boolean;
}

export type NotificationChannelUpdate = {
  email?: boolean;
  push?: boolean;
};

export interface NotificationsUpdateInput {
  categories: Record<string, NotificationChannelUpdate>;
}

export interface ProfileMatchInput {
  businessIndustry?: BusinessIndustry;
  eventID?: string;
  gender?: Gender;
  isDCB?: boolean;
  limit?: number;
  locationChapterPlaceID?: string;
  locationCurrentPlaceID?: string;
  minAnnualRevenue?: AnnualRevenue | string;
  minTeamSize?: TeamSize | string;
  query?: string;
  skipReranking?: boolean;
}

export interface ReportIssueInput {
  context?: Record<string, unknown>;
  screenshot?: string;
  severity?: "bug" | "feedback" | "question";
  text: string;
}
