# DC Member API Contract

This directory pins the API contract used to validate the official clients.

- `openapi.json` is a committed snapshot of `https://api.dynamitecircle.com/openapi.json`.
- `operation-map.json` maps each OpenAPI operation to the Python command and
  TypeScript SDK method that covers it.

CI should read this pinned contract, not the live API. Live drift checks can be
run manually during releases, then the pinned snapshot is updated intentionally.
