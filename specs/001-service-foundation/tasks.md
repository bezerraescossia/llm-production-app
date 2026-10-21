---

description: "Task list for spec 001 Service Foundation"
---

# Tasks: Service Foundation

**Input**: Design documents from `/specs/001-service-foundation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, repo-root `contracts/v1/`, quickstart.md

**Tests**: INCLUDED. Constitution principle III (Test-First) is mandatory: within every story, tests are written first and MUST fail before the code they cover exists.

**Organization**: grouped by user story. US1 and US2 are both P1. US2's conformance tests exercise routes built in US1, so US2 follows US1 in practice (see Dependencies).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1..US5 map to the user stories in spec.md
- Paths are relative to the repository root. Source lives in `src/ai_services/`, tests in `tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: project initialization

- [X] T001 Create `pyproject.toml` (project `ai-services`, Python `>=3.12,<3.13`) and `.python-version` (`3.12`). Runtime deps pinned exactly: `fastapi==0.156.8`, `uvicorn[standard]==0.54.0`, `pydantic==2.14.1`, `pydantic-settings==2.16.1`, `sse-starlette==3.5.0`, `structlog==26.1.0`. Dev group pinned exactly: `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `httpx==0.28.1`, `asgi-lifespan==2.1.0`, `jsonschema==4.26.0`, `openapi-spec-validator==0.9.0`, `ruff==0.17.1`, `mypy==2.4.0`, and `pyyaml` pinned exactly to the version `uv lock` resolves (record it in `pyproject.toml`). Run `uv lock` to produce `uv.lock` and commit it.
- [X] T002 Add tool configuration to `pyproject.toml` (after T001): ruff lint and format, `mypy --strict` with `src` as target, pytest with `asyncio_mode = "auto"` and `testpaths = ["tests"]`.
- [X] T003 [P] Create package skeleton: `src/ai_services/__init__.py`, `src/ai_services/api/__init__.py`, `src/ai_services/api/v1/__init__.py`, and empty `tests/unit/`, `tests/contract/`, `tests/integration/` directories each with `__init__.py`. The contract files already exist at repo-root `contracts/v1/` and are not recreated.
- [X] T004 [P] Create `.env.example` (documented variables from data-model.md Configuration: `SERVICE_TOKENS`, `READINESS_DEPENDENCIES`, `MAX_REQUEST_BYTES`, `MAX_MESSAGES`, `SHUTDOWN_GRACE_SECONDS`, `PLACEHOLDER_TOKEN_DELAY_MS`, `LOG_LEVEL`, with placeholder values only), `.gitignore` (`.env`, `.venv`, caches), and `.dockerignore`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: shared modules every story needs: configuration, context, logging, errors, schemas, events, app factory.

**⚠️ CRITICAL**: no user story work starts until this phase is complete.

### Tests first (must fail)

- [X] T005 Create `tests/conftest.py` with fixtures: settings factory (two valid test tokens of at least 32 characters), `app` built from `create_app(settings)`, and an `httpx.AsyncClient` using `ASGITransport` plus `asgi_lifespan.LifespanManager`.
- [X] T006 [P] Unit tests for settings in `tests/unit/test_config.py`: `SERVICE_TOKENS` missing fails to start naming the variable; a token shorter than 32 characters is rejected; more than two tokens is rejected; defaults are `MAX_REQUEST_BYTES=262144`, `MAX_MESSAGES=100`, `SHUTDOWN_GRACE_SECONDS=20`, `PLACEHOLDER_TOKEN_DELAY_MS=0`, `LOG_LEVEL=INFO`; `READINESS_DEPENDENCIES` parses `name=host:port,…`.
- [X] T007 [P] Unit tests for the error model in `tests/unit/test_errors.py`: each code maps to its HTTP status (`unauthorized` 401, `invalid_identity` 400, `validation_error` 422, `history_too_long` 422, `payload_too_large` 413, `rate_limited` 429, `shutting_down` 503, `internal_error` 500); body shape is `{"error": {"code", "message", "request_id", "details"?, "retry_after_seconds"?}}`; `Retry-After` header present for 429 and 503; `internal_error` message is generic and never leaks exception text.
- [X] T008 [P] Unit tests for schemas in `tests/unit/test_schemas.py`: `messages` has 1–100 items; `role` is `user` or `assistant` only; `content` is 1–32,000 characters; the last message must have role `user`; unknown fields are rejected; the identifier pattern `^[A-Za-z0-9._:@-]{1,128}$` accepts and rejects the expected values; the request-id pattern `^[A-Za-z0-9._-]{8,128}$` likewise.
- [X] T009 [P] Unit tests for SSE events in `tests/unit/test_events.py`: each of `token`, `tool_call`, `tool_result`, `citation`, `usage`, `done`, `error` encodes to a frame with `id`, `event`, `data`; sequence numbers start at 0 with no gaps; the encoder refuses to emit anything after a terminal event; `usage` with null `cost_usd` is valid.
- [X] T010 [P] Unit tests for logging in `tests/unit/test_logging.py`: output is JSON; `request_id`, `tenant_id`, `user_id` from context appear on every entry; values under keys containing `authorization`, `token`, `secret` or `password` are masked; two concurrent tasks with different contexts never mix identities.
- [X] T011 [P] Unit tests for request-id middleware in `tests/unit/test_request_id_middleware.py`: a client `X-Request-Id` matching `^[A-Za-z0-9._-]{8,128}$` is reused; a missing or invalid one is replaced by a generated UUIDv4; the value is echoed in the `X-Request-Id` response header; `X-Contract-Version` is present on every response.

### Implementation

- [X] T012 Implement settings in `src/ai_services/config.py` with pydantic-settings, fail-fast with a message naming the missing or invalid variable (makes T006 pass).
- [X] T013 [P] Implement `RequestContext` and its context variable in `src/ai_services/context.py` with fields `request_id`, `tenant_id`, `user_id`, `received_at`, `contract_version` (per data-model.md RequestContext).
- [X] T014 Implement structlog JSON setup with context binding and redaction in `src/ai_services/logging.py` (depends on T013; makes T010 pass). Never log headers or bodies.
- [X] T015 [P] Implement error codes, exception types and handlers in `src/ai_services/errors.py` (makes T007 pass), including the reserved `rate_limited` code with `retry_after_seconds` (FR-020). Unhandled exceptions become `internal_error` with detail only in logs.
- [X] T016 [P] Implement `ChatRequest`, `Message`, `Error`, `Liveness`, `Readiness`, `ContractInfo` pydantic models in `src/ai_services/schemas.py` with the exact constraints from data-model.md (makes T008 pass); use `extra="forbid"`.
- [X] T017 [P] Implement typed SSE events and the encoder in `src/ai_services/events.py` (makes T009 pass).
- [X] T018 Implement request-id middleware in `src/ai_services/middleware.py` (makes T011 pass). Depends on T013.
- [X] T019 Implement the app factory in `src/ai_services/main.py`: `create_app(settings)`, lifespan, middleware and error-handler installation, mounting of `api/v1` routers (empty for now), and a module-level `app` for Uvicorn. Depends on T012–T018.

**Checkpoint**: unit tests T006–T011 pass; `uv run mypy --strict src` and `uv run ruff check .` are clean.

---

## Phase 3: User Story 1 - Call an authenticated streaming endpoint (Priority: P1) 🎯 MVP

**Goal**: an authenticated, identity-bearing chat request returns a deterministic placeholder answer as typed SSE events; every failure path is rejected cleanly.

**Independent Test**: send a valid request and receive ordered events ending in one `done`; send invalid credentials, missing identity, bad body and over-limit history and receive the documented errors with no stream.

### Tests for User Story 1 (write first, must fail)

- [X] T020 [P] [US1] Unit tests for authentication in `tests/unit/test_auth.py`: valid token accepted; both tokens accepted when two are configured (FR-018 rotation); a removed token is rejected; comparison uses `hmac.compare_digest`; missing or malformed `Authorization` header rejected; identity headers `X-Tenant-Id` and `X-User-Id` validated against `^[A-Za-z0-9._:@-]{1,128}$` with the failing header named in `details.field`; empty, over-128 and disallowed-character values rejected.
- [X] T021 [P] [US1] Integration test for the success path in `tests/integration/test_chat_stream.py`: 200 `text/event-stream`, events in order `token`… then `usage` then exactly one final `done` with `finish_reason` `stop`; ids 0..n with no gaps; first event received within 500 ms (SC-006).
- [X] T022 [P] [US1] Integration tests for rejections in `tests/integration/test_chat_rejections.py`: no or wrong token gives 401 `unauthorized` and no stream, even for an oversized body (auth runs before body parsing); missing tenant or user gives 400 `invalid_identity` naming the field; malformed JSON or schema violation gives 422 `validation_error`; 101 messages gives 422 `history_too_long`; body over 256 KiB gives 413 `payload_too_large` without buffering the whole body; last role `assistant` gives 422 `validation_error`. Every error body carries `request_id` equal to the `X-Request-Id` header.
- [X] T023 [P] [US1] Integration test for mid-stream failure in `tests/integration/test_chat_failure.py`: a fault injected after the first `token` yields an `error` event (with `code` and `message`) as the terminal event, followed by stream end; no `done` follows.
- [X] T024 [P] [US1] Integration test for client disconnect in `tests/integration/test_chat_disconnect.py`: with `PLACEHOLDER_TOKEN_DELAY_MS` set high, disconnecting mid-stream stops the generator and releases its resources (assert the generator task is cancelled).
- [X] T025 [P] [US1] Integration test for shutdown in `tests/integration/test_shutdown.py`: after the shutdown signal, new requests get 503 `shutting_down` with a `Retry-After` header while an in-flight stream completes within `SHUTDOWN_GRACE_SECONDS`.
- [X] T026 [P] [US1] Integration test for tenant isolation in `tests/integration/test_tenant_isolation.py`: two tenants send identical requests concurrently; responses are correct for each and log entries carry the right `tenant_id` and `user_id` with no cross-contamination.

### Implementation for User Story 1

- [X] T027 [US1] Implement service-token check and identity-header validation in `src/ai_services/auth.py` as a FastAPI dependency that binds `tenant_id` and `user_id` into `RequestContext` and the log context (makes T020 pass).
- [X] T028 [US1] Extend `src/ai_services/middleware.py` with a streaming body-size limit (`MAX_REQUEST_BYTES`, default 262144, rejects before buffering) and a shutdown gate that returns `shutting_down` once the shutdown flag is set. Depends on T018.
- [X] T029 [P] [US1] Implement the deterministic placeholder stream in `src/ai_services/placeholder.py`: fixed text split into word `token` events, optional `PLACEHOLDER_TOKEN_DELAY_MS`, then `usage` (`input_tokens` 0, `output_tokens` 0, `cost_usd` null) and `done` (`stop`); supports test-time fault injection after N events.
- [X] T030 [US1] Implement `POST /v1/chat/stream` in `src/ai_services/api/v1/chat.py` using `sse-starlette` `EventSourceResponse`: auth dependency, `ChatRequest` validation with the `MAX_MESSAGES` limit mapped to `history_too_long`, disconnect checks between events, mid-stream failure converted to an `error` event. Stateless: store nothing between requests (FR-019). Depends on T027–T029.
- [X] T031 [US1] Mount the chat router in `src/ai_services/main.py` and wire the shutdown flag to the app lifespan and Uvicorn graceful-shutdown settings (`--timeout-graceful-shutdown` from `SHUTDOWN_GRACE_SECONDS`). Depends on T030.

**Checkpoint**: T020–T026 pass. US1 is a working, demonstrable MVP: the gateway developer can make a streaming call.

---

## Phase 4: User Story 2 - Rely on a versioned, documented contract (Priority: P1)

**Goal**: the published contract in `contracts/v1/` is the single source of truth, proven by tests, with the version rules enforced.

**Independent Test**: contract tests pass against the running app; changing a response shape without editing the contract fails them.

### Tests for User Story 2 (write first, must fail)

- [X] T032 [P] [US2] Contract conformance tests in `tests/contract/test_openapi_conformance.py`: validate `contracts/v1/openapi.yaml` with `openapi-spec-validator`; for every route and documented status code, issue a real request and validate the JSON response against the matching schema.
- [X] T033 [P] [US2] SSE event conformance tests in `tests/contract/test_event_schema.py`: every frame emitted by the success path and the mid-stream failure path validates against `contracts/v1/events.schema.json`; the schema defines all seven event types; `tool_call` and `tool_result` are documented as informational (assert the text exists in the schema description).
- [X] T034 [P] [US2] Drift test in `tests/contract/test_contract_drift.py`: the app's generated OpenAPI, normalized, equals `contracts/v1/openapi.yaml`; the contract `info.version` equals the version returned by `GET /v1/contract` and the `X-Contract-Version` header; every route path starts with `/v1/`.
- [X] T035 [P] [US2] Contract-route test in `tests/integration/test_contract_route.py`: `GET /v1/contract` returns `{"version": "1.0.0"}` without credentials.

### Implementation for User Story 2

- [X] T036 [US2] Implement `GET /v1/contract` in `src/ai_services/api/v1/contract.py` and mount it in `src/ai_services/main.py`; read the version from repo-root `contracts/v1/openapi.yaml` (loaded by path in development; copied into the image by the Dockerfile, see T043) and set `X-Contract-Version` from it (makes T035 pass).
- [X] T037 [US2] Align app-generated OpenAPI with the contract: set response models, status codes, security schemes and operation ids in `src/ai_services/api/v1/chat.py`, `src/ai_services/api/v1/contract.py` and `src/ai_services/main.py` until T032 and T034 pass. If the app and the contract disagree, the contract wins unless a deliberate contract change (with version bump) is made.
- [X] T038 [US2] Add `scripts/contract-diff.sh`: runs `oasdiff breaking` (Docker image) comparing `contracts/v1/openapi.yaml` from a base git ref to the working tree and fails on a breaking change unless a new major version path (`contracts/v2/`) exists and `info.version` has a new major number. Document usage at the top of the script.

**Checkpoint**: T032–T035 pass and `scripts/contract-diff.sh` runs against a trivial no-change diff. US1 and US2 together satisfy contract-first (constitution I).

---

## Phase 5: User Story 3 - Start the whole stack with one command (Priority: P2)

**Goal**: `docker compose up --wait` brings up the service and Postgres, Redis Stack and Qdrant, with separate liveness and readiness.

**Independent Test**: from a clean checkout, one command reaches healthy within 3 minutes; stopping a dependency makes readiness not-ready while liveness stays ok, and it recovers without a restart.

### Tests for User Story 3 (write first, must fail)

- [X] T039 [P] [US3] Unit tests for dependency checks in `tests/unit/test_readiness.py`: a TCP check against an open local port is `up`; a closed port is `down` within 1 second; overall status is `ready` only if every dependency is `up`; an empty dependency list is `ready`.
- [X] T040 [P] [US3] Integration tests for health in `tests/integration/test_health.py`: `GET /v1/health/live` returns `{"status":"ok"}` without credentials and does no dependency work; `GET /v1/health/ready` without a token returns only `status`; with a token adds `dependencies` with `name` and `status`; with a dependency down returns 503 `not_ready` (detail only with the token) while liveness stays `ok`; the dependency recovers without restarting the app; the app starts when a dependency is unreachable.

### Implementation for User Story 3

- [X] T041 [US3] Implement the dependency registry and TCP checks (1-second timeout, evaluated per call) in `src/ai_services/readiness.py` (makes T039 pass).
- [X] T042 [US3] Implement `GET /v1/health/live` and `GET /v1/health/ready` in `src/ai_services/api/v1/health.py` with optional-credential behavior, mount in `src/ai_services/main.py` (makes T040 pass). Readiness returns 503 while shutting down.
- [X] T043 [P] [US3] Write `Dockerfile`: multi-stage build with uv from `uv.lock`, copying `contracts/` into the image next to the source, non-root user, `CMD` running Uvicorn with `--timeout-graceful-shutdown ${SHUTDOWN_GRACE_SECONDS}`, and a `HEALTHCHECK` on `/v1/health/live`. Pin the base image tag, then record its digest.
- [X] T044 [US3] Write `compose.yaml` with services `service`, `postgres`, `redis` (Redis Stack) and `qdrant`; each has a healthcheck; `service` uses `depends_on` with `condition: service_healthy`, reads `.env`, and sets `READINESS_DEPENDENCIES` to `postgres=postgres:5432,redis=redis:6379,qdrant=qdrant:6333`. Pin every image tag, verify each tag exists with `docker pull`, and record digests. No ports published except the service on `8080`.
- [X] T045 [US3] Verify manually and record results at the end of `specs/001-service-foundation/quickstart.md` (a "Verified on" note): `docker compose up --wait` completes within 3 minutes from a clean checkout (SC-002); `docker compose stop qdrant` makes readiness not-ready and `docker compose start qdrant` recovers it.

**Checkpoint**: T039–T040 pass; the quickstart steps 2 and 3 work.

---

## Phase 6: User Story 4 - Catch regressions automatically (Priority: P2)

**Goal**: every change runs lint, types, unit, contract and integration tests, the breaking-change gate and a stack smoke test, and a failure blocks the merge.

**Independent Test**: a deliberately failing test makes the pipeline fail and name the check; fixing it makes it pass.

### Implementation for User Story 4

- [X] T046 [P] [US4] Write `scripts/smoke.sh`: waits for `/v1/health/live`, sends one authenticated streaming request using `$SERVICE_TOKEN`, asserts the response contains a `done` event as the last event, then calls `/v1/health/ready` with the token and asserts `ready`; exits non-zero with a clear message on any failure.
- [X] T047 [US4] Write `.github/workflows/ci.yml` triggered on `push` and `pull_request`, with separate named jobs: `lint` (`ruff check`, `ruff format --check`), `types` (`mypy --strict src`), `tests` (`pytest tests/unit tests/contract tests/integration`), `contract-breaking` (`scripts/contract-diff.sh` against the base branch, full git history fetched), `smoke` (generate `.env` with random tokens, `docker compose up --wait`, `scripts/smoke.sh`, `docker compose down -v`, upload logs on failure). Install via `uv sync --frozen`. Depends on T038, T043, T044, T046.
- [X] T048 [US4] Document in the repository `README.md` that all five CI jobs must be configured as required status checks on the default branch (branch protection is a repository setting, not code), and list how to run each check locally (commands from quickstart step 9).
- [X] T049 [US4] Prove the gate works: on a scratch branch add a deliberately failing test, confirm the pipeline reports the failing job by name, then revert it. Record the outcome in the pull request description. **Result (2026-10-21):** a no-change branch passed all five jobs; a branch with one deliberately failing test failed only `tests` (step "Run uv run pytest tests/unit tests/contract tests/integration") and the other four jobs passed. Both scratch branches were deleted. Branch protection (required status checks) is still not set on `main`.

**Checkpoint**: the pipeline passes on a clean branch and fails on a broken one.

---

## Phase 7: User Story 5 - Diagnose a request from its identifier (Priority: P3)

**Goal**: an operator finds every log line for a request by its identifier; tenant and user appear on each; no secrets leak.

**Independent Test**: submit a request, take the identifier from the response, find its log entries by it, and confirm no token value appears in any captured log.

### Tests for User Story 5 (write first, must fail where behavior is new)

- [X] T050 [P] [US5] Integration test in `tests/integration/test_request_logs.py`: for success, rejection and mid-stream failure requests, every log entry for the request carries `request_id` equal to the response header, plus `tenant_id` and `user_id` when identity was valid; entries are JSON and filterable by `request_id`.
- [X] T051 [P] [US5] Secret-leak test in `tests/integration/test_no_secrets_in_logs.py` (SC-008): run a full scenario set (success, 401 with a wrong token, bad identity, oversized body, failure, readiness with token) while capturing all log output and assert that no configured token value, no `Authorization` header value and no request body content appears anywhere.

### Implementation for User Story 5

- [X] T052 [US5] Fix any gaps found by T050 and T051 in `src/ai_services/logging.py`, `src/ai_services/middleware.py` and `src/ai_services/auth.py` (for example, log request start and finish with status, duration and outcome, never headers or bodies). If both tests already pass, record that in the task and add no code.

**Checkpoint**: T050–T051 pass; quickstart step 7 works.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T053 Run `quickstart.md` end to end against a fresh `docker compose up --wait`, fix any discrepancy between the guide and behavior, and add a "Verified on" date to the file (covers steps 1–9, including rotation in step 8).
- [X] T054 [P] Amend `.specify/memory/roadmap.md` (PATCH bump, update the Sync Impact Report): set spec 001's status per progress. The deferrals of the principle VI gate (to spec 003) and the CI regression eval (to spec 004) are already recorded in roadmap 1.3.0, so only confirm they are still there.
- [X] T055 [P] Write `README.md` sections: purpose, architecture position (gateway calls this service), how to run, how to run tests, contract location and versioning rule. Link to the constitution and roadmap.
- [X] T056 Security pass: confirm nothing logs headers or bodies, confirm `SERVICE_TOKENS` never appears in `docker compose config` output committed to the repo, confirm the image runs as non-root, confirm only port 8080 is published.
- [X] T057 Final constitution check: re-read plan.md's Constitution Check table and confirm each Pass row holds in the finished code and each Deferred row still names its owner spec on the roadmap; record any new deviation under Complexity Tracking.
- [X] T058 Write `scripts/load-test.py` (httpx, asyncio; `--streams` default 20) that opens 20 concurrent authenticated streams against the Compose stack and passes only if every stream ends in exactly one `done` and the 95th-percentile time to first event is under 500 ms. Run it against `docker compose up --wait`, and record the result in the "Verified on" note of `specs/001-service-foundation/quickstart.md`. Required before this spec is marked done (constitution Development Workflow).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; BLOCKS all stories.
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on Foundational and in practice on US1's routes (conformance and drift tests exercise `POST /v1/chat/stream`). Its contract files already exist from planning.
- **US3 (Phase 5)**: depends on Foundational; the Dockerfile and compose smoke use US1's endpoint, so run after US1 for a meaningful result. Code tasks T039–T042 are independent of US1.
- **US4 (Phase 6)**: depends on US2 (T038), US3 (T043, T044) and US1 (smoke request).
- **US5 (Phase 7)**: depends on US1 (identity binding and request flow).
- **Polish (Phase 8)**: after the stories you intend to ship.

### Within Each Story

- Tests first; confirm they fail for the right reason before implementation.
- Settings and schemas before auth; auth and placeholder before the route; route before contract alignment.
- Commit after each task or logical group.

### Parallel Opportunities

- Setup: T003 and T004 together.
- Foundational tests T006–T011 together (T005 first); implementations T013, T015, T016, T017 together.
- US1 tests T020–T026 together; T029 can run alongside T027.
- US2 tests T032–T035 together.
- US3: T039 and T040 together, T043 alongside T041/T042.
- US4: T046 alongside T038/T043 work.
- US5 tests T050 and T051 together.
- US3 code tasks and US5 tests can proceed in parallel with US2 once US1 is done.

---

## Parallel Example: User Story 1

```text
# Launch all US1 tests together:
Task: "Unit tests for authentication in tests/unit/test_auth.py"
Task: "Integration test for the success path in tests/integration/test_chat_stream.py"
Task: "Integration tests for rejections in tests/integration/test_chat_rejections.py"
Task: "Integration test for mid-stream failure in tests/integration/test_chat_failure.py"
Task: "Integration test for client disconnect in tests/integration/test_chat_disconnect.py"
Task: "Integration test for shutdown in tests/integration/test_shutdown.py"
Task: "Integration test for tenant isolation in tests/integration/test_tenant_isolation.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup, then Phase 2 Foundational.
2. Phase 3 US1.
3. **Stop and validate**: run the success and rejection scenarios from quickstart steps 4 and 5.
4. A gateway developer can already integrate against this endpoint.

### Incremental Delivery

1. Setup + Foundational → skeleton ready.
2. US1 → streaming works (MVP).
3. US2 → contract proven and gated.
4. US3 → one-command stack and health.
5. US4 → CI protects everything above.
6. US5 → diagnosability confirmed.
7. Polish → quickstart verified, roadmap updated.

### Notes

- Every acceptance scenario in spec.md maps to a test: US1 (T021–T023), US2 (T032–T034), US3 (T040, T045), US4 (T047, T049), US5 (T050–T051).
- The constitution's streaming load test requirement is covered by T058; SC-006 "normal load" is defined as 20 concurrent streams.
- FR-018 (rotation) is covered by T020; FR-015 by T024 and T025; FR-019 by T022; FR-020 by T007 and T015.
- Rate limit enforcement is out of scope here (deferred to spec 009); only the reserved error code and identity keys exist.
