# Contracts for spec 002

`v1.1/` holds the **proposed** contract 1.1.0 (`openapi.yaml`, `events.schema.json`). It is not live yet:
the live contract is `contracts/v1/` at the repository root, which the running service and its tests read.
The implementation tasks copy `v1.1/` over `contracts/v1/` in the same change that updates the contract tests
(test-first), so the drift test never sees a contract the code does not match.

## What changes in 1.1.0

| Change | Kind |
|---|---|
| `info.version` 1.0.0 → 1.1.0 | version |
| Error codes `upstream_unavailable` (503), `upstream_timeout` (504), `upstream_error` (502), `input_too_large` (422) | new codes |
| `ErrorCode` becomes an extensible enum (`x-extensible-enum`); clients must treat an unknown code as a generic failure and use the HTTP status | client obligation |
| Chat route documents statuses 502 and 504; 503 and 422 descriptions extended | additive |
| `usage` event: `input_tokens` and `output_tokens` may be `null` when the provider did not report them | loosened (event schema, outside the OpenAPI gate) |

## The one-time gate exception

`oasdiff` reports the enum change as breaking (checked: 7 errors, all of the form "removed the enum
constraint from `error/code` ... status N"; adding values to the strict enum is flagged the same way).
By the owner's decision this one transition is accepted, because 1.0.0 has no deployed consumer.

- `oasdiff-ignore-1.0-to-1.1.txt` lists exactly those seven findings. Passed to `oasdiff` with
  `--err-ignore`, it makes the 1.0.0 → 1.1.0 diff pass. Verified: with the file the diff is clean, and an
  unrelated breaking change (a removed route) is still reported.
- From 1.1.0 on, adding a code to the extensible enum is not flagged, so the ignore file is **single use**.
  **Expired 2026-10-21:** contract 1.1.0 became the baseline on `main`, so `contracts/oasdiff-ignore.txt` and the
  script's reference to it were deleted (task T058). `oasdiff-ignore-1.0-to-1.1.txt` stays here only as the
  record of what the exception covered.
- The constitution needs a short amendment saying an exception to a MUST requires a written reason and an
  expiry. That amendment is task T004 and must be committed before the contract change is applied (T011).
