# Research: Service Foundation

All decisions below resolve open items from the Technical Context. None required a new question to the user;
each is reversible in the plan before tasks are generated.

## R1 — Language, framework, tooling
- **Decision**: Python 3.12, FastAPI, Uvicorn, Pydantic v2, uv for dependency locking.
- **Rationale**: fixed by roadmap C-02. 3.12 is pinned rather than the locally installed 3.14 because dependency wheels and tooling support is broadest there; the container image uses the same version so local and CI behave identically.
- **Alternatives**: Python 3.14 (newer, but higher risk of missing wheels); Poetry/pip-tools (uv is already installed locally and is faster).

## R2 — SSE implementation
- **Decision**: `sse-starlette` `EventSourceResponse`, with an async generator that yields typed events.
- **Rationale**: handles SSE framing, keep-alive pings, client-disconnect detection and cooperative shutdown, which map directly to FR-001 and FR-015.
- **Alternatives**: hand-rolled `StreamingResponse` (more code to get disconnect and framing right); WebSockets (the contract is SSE per C-01).

## R3 — Service authentication and rotation
- **Decision**: `Authorization: Bearer <token>`. The environment variable `SERVICE_TOKENS` holds one or two tokens, comma separated, each at least 32 characters. Comparison uses `hmac.compare_digest`. Auth runs before body parsing.
- **Rotation (FR-018)**: operator adds the new token alongside the old one and restarts the service, then the gateway switches at its own pace, then the old token is removed. The gateway is never redeployed in lockstep.
- **Rationale**: simplest scheme that satisfies the spec. The restart is acceptable at study scale; hot reload is out of scope.
- **Alternatives**: mTLS (deferred by the grilling); JWTs signed by the gateway (adds key management without clear benefit while the gateway is trusted); a secrets-manager integration (out of scope).

## R4 — Identity headers
- **Decision**: `X-Tenant-Id` and `X-User-Id` required, pattern `^[A-Za-z0-9._:@-]{1,128}$`. `X-Request-Id` optional, pattern `^[A-Za-z0-9._-]{8,128}$`; otherwise a UUIDv4 is generated. Invalid or missing identity yields `400 invalid_identity` with the field name in `details.field`.
- **Rationale**: matches roadmap C-10 and spec FR-005/FR-009. The allowed character set blocks log injection and path-like values.
- **Alternatives**: body-carried identity (rejected: headers are available before body parsing and body size checks).

## R5 — Route layout and versioning
- **Decision**: every route lives under `/v1/`: `POST /v1/chat/stream`, `GET /v1/health/live`, `GET /v1/health/ready`, `GET /v1/contract`. The contract version is also returned in an `X-Contract-Version` response header. A future `/v2` package sits beside `api/v1`.
- **Rationale**: FR-010 requires the major version in every route path, health checks included. Orchestrator probes simply target `/v1/health/live`.
- **Alternatives**: unversioned `/livez` (violates FR-010 as written).

## R6 — Contract artifacts and enforcement
- **Decision**: contract-first files in `contracts/v1/` at the repository root (the service, the Docker image and CI all read this one copy): `openapi.yaml` (OpenAPI 3.1) and `events.schema.json` (JSON Schema 2020-12). Three enforcement layers:
  1. *Conformance*: contract tests validate real responses and every SSE event against the schemas.
  2. *Drift*: a test compares the running app's generated OpenAPI to the committed file and fails on any difference, so code and contract cannot diverge silently.
  3. *Breaking change gate*: CI runs `oasdiff breaking` against the base branch's contract and fails when a breaking change is present without a new major version (`/v2`) and a bump of `info.version`.
- **Rationale**: satisfies FR-010, FR-011, constitution I and the Gate "plan and implement fail if a schema change lacks a version bump".
- **Alternatives**: Schemathesis property testing (good for HTTP routes, but does not cover SSE bodies; may be added later); generating the contract from code only (loses contract-first).

## R7 — SSE event format
- **Decision**: each frame is `id: <seq>`, `event: <type>`, `data: <json>`. `seq` starts at 0 and increases by 1. Event types and payloads are in `contracts/v1/events.schema.json`. Exactly one terminal event (`done` or `error`) closes every stream. `tool_call` and `tool_result` are informational. `citation` and `usage` are defined now but the placeholder emits only `token`, `usage` and `done`.
- **Rationale**: matches FR-001/FR-002; `id` lets later specs support resume and lets cache replay (spec 007) emit identical frames.
- **Alternatives**: newline-delimited JSON (not SSE; rejected by C-01).

## R8 — Request body and limits
- **Decision**: body `{messages: [{role, content}]}`. Roles are `user` and `assistant` only (the service owns system prompts). The last message must be `user`. Defaults: maximum body 256 KiB (`413 payload_too_large`), maximum 100 messages (`422 history_too_long`), each content 1–32,000 characters. All limits are configurable.
- **Rationale**: implements FR-007 and FR-019 with defaults left open by the spec. Body size is enforced while reading, so an oversized body is rejected before it is fully buffered.
- **Alternatives**: allowing a client-supplied system role (rejected: it bypasses later guardrails and prompt control).

## R9 — Error model
- **Decision**: one shape `{"error": {"code", "message", "request_id", "details"?, "retry_after_seconds"?}}`. Codes: `unauthorized` (401), `invalid_identity` (400), `validation_error` (422), `history_too_long` (422), `payload_too_large` (413), `rate_limited` (429, reserved by FR-020 and never emitted in 001), `shutting_down` (503), `internal_error` (500). A `Retry-After` header accompanies 429 and 503. Errors after a stream starts use the `error` SSE event with the same `code` and `message`.
- **Rationale**: FR-008, FR-020 and the stream-failure scenario.

## R10 — Logging and secrets
- **Decision**: structlog JSON to stdout. A context-bound processor adds `request_id`, `tenant_id`, `user_id`. A redaction processor masks any value stored under keys containing `authorization`, `token`, `secret` or `password`. Request and response headers and bodies are never logged. A test scans captured logs from a full run for every configured token value (SC-008).
- **Rationale**: FR-006, FR-013, FR-017, SC-005, SC-008; matches constitution VI ("no secrets or raw PII in logs").
- **Alternatives**: stdlib logging with a JSON formatter (less ergonomic context binding).

## R11 — Readiness and dependency checks
- **Decision**: `READINESS_DEPENDENCIES` is a comma-separated list of `name=host:port`. Each check is a TCP connect with a 1-second timeout, evaluated on every call. Compose sets Postgres, Redis and Qdrant. Credentialed callers get `{status, dependencies:[{name,status}]}`; others get `{status}`. Liveness is `{status:"ok"}` and does no dependency work. A dependency that is down at startup does not stop the service; it reports not-ready and recovers on its own.
- **Rationale**: FR-012, User Story 3, the "unreachable at startup" edge case.
- **Alternatives**: protocol-level checks (Postgres `SELECT 1`, Redis `PING`, Qdrant HTTP). More accurate, but they need client libraries that no spec uses yet. Upgraded when each dependency gets a real client (specs 003, 004, 007).

## R12 — Shutdown and disconnect
- **Decision**: Uvicorn with `--timeout-graceful-shutdown 20`. On SIGTERM a shutdown flag makes new requests return `503 shutting_down` while in-flight streams finish. The generator checks for client disconnect between events and exits, releasing its resources.
- **Rationale**: FR-015 and both related edge cases.

## R13 — Placeholder answer
- **Decision**: fixed text, split into word tokens, emitted as `token` events with an optional `PLACEHOLDER_TOKEN_DELAY_MS` (default 0, used to test disconnect and shutdown), then one `usage` event (zero tokens, null cost) and `done` with `finish_reason: "stop"`. A test-only request marker is not added; failure paths are triggered by fault injection in tests.
- **Rationale**: FR-003 deterministic output, SC-006.

## R14 — Stack and pinning
- **Decision**: one `compose.yaml` with the service, Postgres, Redis Stack and Qdrant. Each has a healthcheck, and the service starts after them via `depends_on: condition: service_healthy`. Image tags are pinned, and digests are recorded when implementation starts, since the exact tags are checked then. `docker compose up --wait` is the single command. OTel collector, Jaeger and Grafana are left out of 001 (they arrive with spec 003).
- **Rationale**: FR-014, constitution VII, SC-002.

## R15 — CI pipeline
- **Decision**: GitHub Actions on every push and pull request: (1) `ruff check` and `ruff format --check`; (2) `mypy --strict`; (3) unit tests; (4) contract tests and the drift test; (5) `oasdiff breaking` against the base branch; (6) a Compose smoke job that runs `docker compose up --wait`, then `scripts/smoke.sh` (one authenticated streaming request and a health check), then tears down. All steps are required status checks.
- **Rationale**: FR-016, SC-007, constitution workflow gates.
- **Note**: the regression eval is deferred to spec 004 and the principle VI record to spec 003 under the constitution 1.2.0 phase-in rule. The streaming load test is not deferrable, so 001 includes a small one (`scripts/load-test.py`, task T058): 20 concurrent streams against the Compose stack, passing when every stream ends in exactly one `done` and the 95th-percentile time to first event is under 500 ms. It runs before the spec is marked done and is not a required CI job yet.

## R16 — Test strategy (principle III)
- Unit: identity validation, token comparison (including two-token rotation), error mapping, event encoding, redaction.
- Contract: schema validity, every route response and every SSE event type against the contract, drift test.
- Integration (ASGI, no network): authentication-before-parsing, oversize body, history limit, mid-stream failure yields `error` event, client disconnect cancels work, shutdown gate, two tenants in parallel keep separate context and logs, readiness with dependency up and down.
- Smoke (real stack): compose up, one streaming request, readiness.
