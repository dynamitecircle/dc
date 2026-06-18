import { DC } from "../src/index.js";

const apiKey = process.env.DC_API_KEY;
if (!apiKey) {
  throw new Error("Set DC_API_KEY before running this example.");
}

const dc = new DC({ apiKey });

const profile = await dc.profile.get();
console.log(profile);

const trips = await dc.trips.list({ limit: 5 });
console.log(trips);
