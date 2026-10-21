# Feature Specification: Service Foundation

**Feature Branch**: `001-service-foundation`

**Created**: 2026-10-21

**Status**: Draft

**Input**: User description: "spec 001 Foundation"

**Roadmap entry**: 001 — Foundation (`.specify/memory/roadmap.md`)

## Clarifications

### Session 2026-10-21

- Q: Does the gateway send the full conversation history with every chat request, or does this service store conversations? → A: Stateless: the gateway sends the full message history (bounded by a size limit) on each request.
- Q: How should the gateway choose which contract version it talks to? → A: Version in the URL path (e.g. `/v1/...`).
- Q: Should the service accept any well-formed tenant ID or check it against known tenants? → A: Trust the gateway: any well-formed tenant ID is accepted once the service credential is valid.
- Q: Should health checks be open or require the service credential? → A: Liveness open (status only); readiness requires the service credential for the per-dependency detail.
- Q: When should per-user rate limiting be built? → A: The contract reserves it now (error code, retry hint, identity keys); enforcement is built in spec 009.

## User Scenarios & Testing *(mandatory)*

The people who use this service directly are the **gateway developer** (builds the API gateway that calls
it), the **platform operator** (runs and monitors it), and the **service developer** (extends it in later
specs). End users reach it only through the gateway.

### User Story 1 - Call an authenticated streaming endpoint (Priority: P1)

A gateway developer sends a chat request on behalf of an end user, identifying the caller, the tenant and the
user, and receives a streamed response made of well-defined events. In this spec the answer is a fixed
placeholder: no AI model is involved yet. What matters is that the request path, identity handling and event
stream work end to end and match a published contract.

**Why this priority**: every later capability (model calls, RAG, cache, guardrails, tools) plugs into this
path. Without a working, contract-defined stream there is nothing to build on.

**Independent Test**: send a valid request with credentials and identity headers, and verify the client
receives an ordered stream of events that ends with a completion event, all matching the published schema.

**Acceptance Scenarios**:

1. **Given** a request with valid service credentials, tenant and user identity, **When** the gateway
   developer submits a chat request, **Then** the service streams events in order and finishes with a
   `done` event.
2. **Given** a request without credentials or with invalid credentials, **When** it is submitted, **Then** it
   is rejected before any processing and no stream is opened.
3. **Given** valid credentials but a missing tenant or user identity, **When** it is submitted, **Then** it is
   rejected with an error that names the missing identity field.
4. **Given** a malformed or oversized request body, **When** it is submitted, **Then** the service returns a
   structured validation error and does not start a stream.
5. **Given** a failure after the stream has started, **When** the failure occurs, **Then** the client
   receives an `error` event followed by stream termination, not a silent disconnect.

---

### User Story 2 - Rely on a versioned, documented contract (Priority: P1)

A gateway developer reads a published contract describing every route, request shape, response shape, error
shape and streamed event type, and can build against it without reading the service's code. Automated
contract tests prove the running service matches the document.

**Why this priority**: the constitution makes the boundary contract-first (principle I). Later specs add
events and routes to this contract, so its versioning rules must exist from the start.

**Independent Test**: run the contract test suite against the running service and confirm it passes; change a
response shape without updating the contract and confirm the suite fails.

**Acceptance Scenarios**:

1. **Given** the published contract, **When** the contract tests run against the service, **Then** every
   route and every event type conforms.
2. **Given** a change that breaks the contract without a version bump, **When** CI runs, **Then** the build
   fails.
3. **Given** the contract defines the event types `token`, `tool_call`, `tool_result`, `citation`, `usage`,
   `done` and `error`, **When** a client reads the contract, **Then** each type has a documented payload and
   is marked required or optional (`tool_call` and `tool_result` are informational).

---

### User Story 3 - Start the whole stack with one command (Priority: P2)

A platform operator or service developer starts the service and all supporting components from a clean
checkout with a single command, and gets a clear signal when the stack is healthy.

**Why this priority**: reproducibility (constitution principle VII) and a fast feedback loop for every later
spec. It does not block the gateway developer's contract work, so it ranks below P1.

**Independent Test**: from a clean checkout, run the one start command and confirm the health check reports
the service and its dependencies as ready within the time limit.

**Acceptance Scenarios**:

1. **Given** a clean checkout and required local tools, **When** the operator runs the start command, **Then**
   the service and its supporting components come up without manual steps.
2. **Given** a running stack, **When** the operator queries health, **Then** liveness and readiness are
   reported separately, and readiness lists each dependency's status when queried with the service
   credential (overall status only otherwise).
3. **Given** a supporting component is down, **When** readiness is queried, **Then** the service reports
   not-ready (naming the failing dependency for credentialed callers), while liveness stays healthy.

---

### User Story 4 - Catch regressions automatically (Priority: P2)

A service developer opens a change and an automated pipeline runs checks (lint, types, unit and contract tests, a
start-the-stack smoke test) and blocks the merge if any fail.

**Why this priority**: the constitution requires these gates for every component; setting them up now means
every later spec inherits them.

**Independent Test**: open a change with a deliberately failing test and confirm the pipeline blocks it; fix
it and confirm the pipeline passes.

**Acceptance Scenarios**:

1. **Given** a change that passes every check, **When** the pipeline runs, **Then** it reports success.
2. **Given** a change that fails any check, **When** the pipeline runs, **Then** it reports failure naming the
   failing check.
3. **Given** a clean checkout in the pipeline, **When** the smoke test runs, **Then** it starts the stack and
   completes one authenticated streaming request.

---

### User Story 5 - Diagnose a request from its identifier (Priority: P3)

A platform operator takes a request identifier from a client error report and finds every log line for that
request, including the tenant and user it belonged to.

**Why this priority**: useful immediately but not required to prove the contract; richer cost and trace records
arrive in spec 003.

**Independent Test**: submit a request, take the identifier from the response, and confirm logs for that
request are findable by it and carry tenant and user identity without secrets.

**Acceptance Scenarios**:

1. **Given** any request, **When** the response is returned, **Then** it carries a request identifier that
   also appears on all of that request's log entries.
2. **Given** a client-supplied request identifier, **When** it is valid, **Then** the service reuses it;
   otherwise it generates one.
3. **Given** a request with credentials, **When** logs are written, **Then** no credential value appears in them.

---

### Edge Cases

- Client disconnects mid-stream: the service stops work for that request and releases its resources.
- Request arrives while the service is shutting down: in-flight streams finish within a grace period, new
  requests are refused with a clear error.
- Identity headers are present but empty, extremely long, or contain disallowed characters: rejected as
  invalid.
- Two tenants send identical requests at the same time: responses and logs remain separated by tenant.
- Clients that only understand an older contract version: the older version continues to be served until it is
  retired (principle I).
- Credentials are rotated: the new credential works and the old one stops working after the rotation window
  without a redeploy of the gateway.
- A supporting component is unreachable at startup: the service starts, reports not-ready, and recovers
  without a restart when the component returns.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The service MUST expose a streaming chat route that returns a sequence of typed events ending in
  exactly one terminal event (`done` or `error`).
- **FR-002**: The service MUST define and document the event types `token`, `tool_call`, `tool_result`,
  `citation`, `usage`, `done` and `error`, with a payload definition for each. `tool_call` and `tool_result`
  MUST be documented as informational for the client.
- **FR-003**: In this spec the chat route MUST return a deterministic placeholder answer so the full path is
  testable without any AI model.
- **FR-004**: The service MUST reject any request lacking valid service credentials before doing any other
  processing.
- **FR-005**: The service MUST require a tenant identity and a user identity on every request and reject
  requests where either is missing, empty or invalid, naming the offending field.
  A well-formed tenant identity MUST be accepted without a lookup in any tenant list; tenant
  authorization is the gateway's responsibility.
- **FR-006**: Tenant and user identity MUST be available to every part of request handling and MUST appear
  on every log entry for that request.
- **FR-007**: The service MUST validate request bodies, including a maximum size, and return structured
  errors for invalid input.
- **FR-008**: All error responses MUST use one documented error shape containing a stable error code, a
  human-readable message and the request identifier.
- **FR-009**: Every response MUST carry a request identifier; a valid client-supplied identifier MUST be
  reused, otherwise one is generated.
- **FR-010**: The service MUST publish a versioned contract covering every route, request, response, error
  and event type, and MUST serve the contract version in use.
  The major version MUST appear in the URL path of every route (e.g. `/v1/...`), and a previous major
  version's routes MUST keep working until it is formally retired.
- **FR-011**: Contract tests MUST verify the running service against the published contract, and the
  pipeline MUST fail when the service diverges from it or a breaking change lacks a version bump.
- **FR-012**: The service MUST expose separate liveness and readiness checks. Liveness MUST be open and
  return status only. Readiness MUST return only an overall ready or not-ready status to callers without the
  service credential, and MUST add the status of each declared dependency for callers with it.
- **FR-013**: The service MUST obtain all configuration (credentials, endpoints, limits) from its
  environment, fail fast with a clear message when required configuration is missing, and MUST NOT log
  secret values.
- **FR-014**: The full stack (the service plus every supporting component declared for the project) MUST
  start from a clean checkout with one command.
- **FR-015**: The service MUST stop work for a request when its client disconnects, and MUST drain in-flight
  streams within a grace period on shutdown.
- **FR-016**: The automated pipeline MUST run lint, type checks, unit tests, contract tests and a
  stack-start smoke test on every change, and block merge on any failure.
- **FR-017**: Logs MUST be structured and machine-searchable by request identifier, tenant and user.
- **FR-018**: The service MUST support rotating service credentials without a gateway redeploy.
- **FR-019**: The service MUST be stateless with respect to conversations: each chat request carries the full
  ordered message history, the service MUST NOT store conversation content between requests, and requests
  whose history exceeds the documented limit MUST be rejected with a structured error.
- **FR-020**: The contract MUST define a `rate_limited` error code and a retry-after hint in the error shape,
  and the caller's tenant and user identity MUST be available to request handling as the keys a limiter will use.
  This spec MUST NOT enforce any limit.

### Key Entities

- **Caller identity**: the service credential presented by the gateway, plus tenant identity and user identity;
  scopes all later cache, knowledge-base, cost and log data.
- **Request**: one chat call with its identifier, caller identity and body (the full ordered message history); has a lifecycle of accepted,
  streaming, then completed, failed or cancelled.
- **Stream event**: a typed, ordered message in a response stream; types are listed in FR-002.
- **Error**: a structured failure with a stable code, message and request identifier.
- **Contract**: the versioned document that defines routes, schemas, errors and events.
- **Dependency**: a supporting component the service needs, with a health status reported by readiness.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A gateway developer can complete a first authenticated streaming call in under 30 minutes using
  only the published contract.
- **SC-002**: From a clean checkout, the full stack is healthy within 3 minutes of the single start command.
- **SC-003**: 100% of routes and event types are covered by contract tests, and any undocumented change fails
  the pipeline.
- **SC-004**: 100% of requests without valid credentials or complete identity are rejected, with zero streams
  opened.
- **SC-005**: Given a request identifier, an operator finds all log entries for that request within 1 minute.
- **SC-006**: The first streamed event reaches the client within 500 ms of request acceptance for the
  placeholder answer under normal load.
- **SC-007**: A change that fails any required check is blocked from merging in 100% of cases.
- **SC-008**: No secret value appears in any log entry, verified by an automated check over a full test run.

## Assumptions

- Spec 001 contains no AI model calls, caching, knowledge base, guardrails, routing or real tools; those are specs
  002–008. The placeholder answer exists only to prove the path.
- End-user authentication belongs to the API gateway. This service trusts the gateway's tenant and user
  identity once the service credential is valid (roadmap C-10).
- Supporting components are those the roadmap names for later specs. Readiness reports only the ones this
  spec actually uses, and the list grows with each spec.
- The contract is a machine-readable document stored in the repository and versioned with semantic
  versioning (constitution principle I).
- Credential rotation accepts two valid credentials during a rotation window.
- The request size limit and the shutdown grace period have documented defaults and are configurable.
- Local development uses a container runtime available on the developer's machine; the CI service is GitHub
  Actions (roadmap C-11).
- The gateway owns tenant authorization; this service keeps no tenant registry in v1.
- The gateway owns conversation storage and retention; this service holds no conversation state.
- Rate limit enforcement, dashboards and load testing are deferred to spec 009. Spec 001 only reserves the
  contract for rate limiting (FR-020); what a limit counts (requests, tokens or cost) is decided in 009.
