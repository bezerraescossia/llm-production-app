# Feature Specification: LLM Gateway

**Feature Branch**: `002-llm-gateway`

**Created**: 2026-10-21

**Status**: Draft

**Input**: User description: "spec 002 - LLM Gateway"

**Roadmap entry**: 002 — LLM gateway (`.specify/memory/roadmap.md`)

## Clarifications

### Session 2026-10-21

- Q: Besides streaming, should the gateway let internal callers ask for a complete answer in one piece? → A: Streaming only underneath, plus a helper that returns the collected full answer (text, finish reason, token counts).
- Q: Which real model providers must v1 be set up and documented to use, besides the stub? → A: Anthropic and OpenAI.
- Q: If every model in a tier is failing, may the gateway answer from a different tier? → A: No. Fallback stays among the models of the requested tier; when all fail, the caller gets an error.
- Q: Should the chat route wait for the first piece of output before replying, or open the stream immediately? → A: Wait for the first output, bounded by the first-output limit. A failure before it returns an HTTP error; a failure after it uses the `error` event.
- Q: Who controls generation settings such as maximum answer length and randomness? → A: The operator sets per-tier defaults and a hard ceiling in configuration; callers may lower values per request but never raise them above the ceiling.
- Q: How should new error codes be handled, since the automated breaking-change check flags them? → A: A one-time, owner-approved exception for contract 1.1.0: extensible error codes from then on, with a single-use exception in the check (decided during planning).
- Q: What happens when every model of a tier is cooling down? → A: The gateway still tries the model whose cool-down ends soonest instead of failing without trying (decided in analysis).
- Q: How long may a request wait for the first output across all retries and fallbacks? → A: A separate configurable overall wait (default 45 seconds); reaching it returns a gateway-timeout error (decided in analysis).

## User Scenarios & Testing *(mandatory)*

The people who use this capability are the **service developer** (builds later capabilities such as the
prompt router, retrieval, cache and tools, which all need model completions), the **platform operator**
(chooses which models serve which tier and supplies provider credentials), and, indirectly, the **end user**
(who receives answers through the API gateway). A **tier** is a named class of model (small, medium,
large) that trades cost against capability; callers ask for a tier, never for a specific model.

### User Story 1 - Request a completion by tier and get a uniform stream (Priority: P1)

A service developer asks the gateway for a completion at a given tier, passing the conversation messages,
and receives a stream of events in the one format the service already publishes (`token`, then `usage`, then
a terminal `done`, or `error`). The format is identical whichever provider and model served the request. The
chat route uses the gateway at a configured default tier, so a real answer streams to the caller. A built-in
stub provider produces a deterministic answer so everything works with no provider credentials, in
development and in tests.

**Why this priority**: every later capability depends on getting model output through one stable interface.
Without it nothing can be built on real models, and nothing can be tested without paying for them.

**Independent Test**: with only the stub provider configured, request a completion at each tier and verify an
ordered, well-formed event stream ending in one `done`; then repeat against the chat route.

**Acceptance Scenarios**:

1. **Given** a configured tier, **When** a component requests a completion with a valid message history,
   **Then** it receives `token` events in order, then `usage`, then exactly one `done`.
   **And** when the same component asks for the complete answer instead, it receives the full text, finish
   reason and token counts as one result built from that same stream.
2. **Given** two tiers served by different providers, **When** the same request is made to each, **Then** the
   event types and payload shapes are identical; only the text and token counts differ.
3. **Given** only the stub provider is configured, **When** the chat route receives a request, **Then** a
   deterministic answer streams and the stack needs no external credentials.
4. **Given** a tier name that is not configured, **When** a completion is requested, **Then** the request
   fails immediately with a clear error naming the tier and no provider is contacted.
5. **Given** a provider that signals why generation stopped (finished normally, hit the length limit, or was
   blocked by the provider's own safety filter), **When** the stream ends, **Then** `done` carries the matching
   finish reason (`stop`, `length`, `blocked`).

---

### User Story 2 - Map tiers to pinned models through configuration (Priority: P1)

A platform operator defines, in configuration only, which exact model versions serve each tier, in order of
preference, and supplies provider credentials from the environment. Changing the model behind a tier needs no
code change. A model is always an exact, dated or versioned identifier, never a moving alias such as
"latest".

**Why this priority**: the constitution requires pinned model identifiers (principle VII), and the tier idea
only pays off if swapping models is a configuration change.

**Independent Test**: change a tier's model in configuration, restart, and confirm the new model serves that
tier; supply an alias like "latest" or an unknown tier reference and confirm startup refuses with a clear
message.

**Acceptance Scenarios**:

1. **Given** a configuration listing models per tier, **When** the service starts, **Then** every tier resolves
   to its ordered list of pinned models.
2. **Given** a configuration that names a moving alias, an empty tier, a duplicate model in one tier, or a
   provider without credentials, **When** the service starts, **Then** it fails fast with a message naming the
   offending entry.
3. **Given** a tier's models are changed in configuration, **When** the service restarts, **Then** the new
   models serve that tier with no code change.
4. **Given** provider credentials, **When** the service logs anything, **Then** no credential value appears.

---

### User Story 3 - Survive a provider failure with retries and fallback (Priority: P2)

When a provider is slow, rate-limiting, or failing, the gateway retries briefly, then falls back to the next
model in the same tier's ordered list, so the caller still gets an answer. If every option is exhausted, the
caller gets one clear error, quickly. Fallback never moves a request to a more expensive tier on its own.

**Why this priority**: providers fail routinely; without this a single outage becomes an outage of the whole
service. It ranks below P1 because the happy path must exist first.

**Independent Test**: use the stub provider with injected failures (error, timeout, rate limit) and verify the
retry count, the fallback order, and the final outcome.

**Acceptance Scenarios**:

1. **Given** the first model fails with a temporary error before producing any output, **When** retries are
   exhausted, **Then** the gateway tries the next model in the tier and the caller still receives a complete
   answer.
2. **Given** a permanent error (invalid request, authentication failure), **When** it occurs, **Then** it is not
   retried, and fallback proceeds only where the error was specific to that model or provider.
3. **Given** every model in the tier fails before any output, **When** the last option is exhausted, **Then**
   the chat route returns one HTTP error in the standard error shape, within the overall wait limit, and no
   stream is opened. If output had already begun, the caller instead receives a single `error` event.
4. **Given** a model fails after it has already streamed part of the answer, **When** the failure occurs,
   **Then** no fallback happens, because a half-written answer cannot be continued by a different model; the
   caller gets an `error` event after the partial output.
5. **Given** the first model is failing repeatedly, **When** the gateway keeps receiving requests, **Then** it
   stops sending new requests to it for a short cool-down period and uses the next model directly.

---

### User Story 4 - Bounded time and no wasted work (Priority: P2)

Every completion has time limits: how long to wait for the provider to start answering, how long to wait
overall before the first output across retries and fallbacks, how long between streamed pieces, and how
long in total. If the end user goes away, the gateway stops the provider request so
it stops costing money.

**Why this priority**: unbounded waits tie up capacity and hide failures, and abandoned requests burn paid
tokens. Both are production basics.

**Independent Test**: use the stub provider with slow responses and a disconnect; verify timeouts fire at the
configured limits and provider work stops after a disconnect.

**Acceptance Scenarios**:

1. **Given** a provider that never starts answering, **When** the first-output time limit passes, **Then** the
   attempt is abandoned and counted as a temporary failure (retry or fallback applies).
2. **Given** a stream that stalls between pieces for longer than the idle limit, **When** the limit passes,
   **Then** the attempt ends with an `error` event after the partial output.
3. **Given** an answer that runs past the total time limit, **When** it passes, **Then** the stream ends with an
   `error` event and the provider request is stopped.
4. **Given** the caller disconnects mid-stream, **When** the disconnect is detected, **Then** the provider
   request is cancelled promptly.
5. **Given** every attempt is slow or failing before any output, **When** the overall wait limit is reached,
   **Then** the chat route returns a gateway-timeout error in the standard shape, the provider request is
   cancelled, and no stream is opened.

---

### User Story 5 - See what happened without exposing content (Priority: P3)

A platform operator can see, for every completion, which tier and model served it, how many attempts and
fallbacks it took, how long it took, how it finished, and how many tokens were used, all in searchable logs
tied to the request identifier. Prompts and answers are never logged.

**Why this priority**: operators need this to run the service, but it only becomes valuable once failures and
fallbacks exist; the persistent cost and evaluation records arrive in spec 003.

**Independent Test**: run a completion that needed one fallback, then find its log entries by request
identifier and confirm they show tier, model, attempts, fallback, latency, finish reason and token counts, and
contain no message text.

**Acceptance Scenarios**:

1. **Given** any completion, **When** it finishes, **Then** one summary log entry records tier, serving model,
   attempts, whether a fallback was used, latency to first output, total latency, finish reason, and token
   counts, with the request, tenant and user identifiers.
2. **Given** a completion that failed over, **When** logs are inspected, **Then** each failed attempt is
   recorded with its model and error category, without any message text.
3. **Given** any completion, **When** an automated check scans all logs from a test run, **Then** no prompt
   text, answer text or credential appears.

---

### Edge Cases

- The provider reports usage that is missing or partial: the `usage` event reports what is known and marks
  the rest as unknown rather than guessing.
- A provider returns an empty answer: the stream still ends with `usage` and `done`, with the finish reason
  the provider gave.
- A provider emits very large or very many pieces: the gateway streams them as they arrive without buffering
  the whole answer.
- Provider credentials are missing for a configured provider: startup fails fast, naming the provider.
- Two tenants request completions at the same time: nothing is shared between their requests (no cached
  answers, no shared message history).
- The shutdown signal arrives mid-answer: in-flight completions finish within the grace period, as in spec
  001.
- The requested history is longer than the chosen model can accept: the caller receives a clear error instead
  of a truncated or silently altered conversation.
- A cool-down on a failing model expires: the next request tries it again.
- Every model of a tier is cooling down at once: the gateway still tries the one whose cool-down ends
  soonest (FR-013) rather than failing without trying.
- All providers in all tiers are down at startup: the service still starts (readiness is unaffected, no paid
  probe is made).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The service MUST provide one internal interface through which any component requests a
  completion by tier name, passing an ordered message history, and receives an asynchronous stream of the
  service's existing event types (`token`, `usage`, `done`, `error`).
- **FR-002**: Output MUST be normalised so the event types, payload shapes and ordering are identical
  regardless of which provider or model served the request (`token` events with consecutive indexes, then
  `usage`, then exactly one terminal event).
- **FR-003**: Tiers MUST be defined in configuration as small, medium and large (at minimum), each with an
  ordered list of exact model identifiers and the provider that serves each. v1 MUST support Anthropic and
  OpenAI models in any tier and in any order, so a tier can fall back across the two providers.
- **FR-004**: Model identifiers MUST be pinned: the service MUST reject at startup any identifier that is a
  moving alias (for example "latest"), an empty tier, a duplicate model within a tier, a reference to an
  unknown provider, or a provider with no credentials.
- **FR-005**: Provider credentials MUST come from the environment and MUST NOT appear in logs, error
  messages, events or the contract.
- **FR-006**: Changing which models serve a tier MUST require configuration changes only.
- **FR-007**: The service MUST include a stub provider that returns a deterministic answer, supports
  injectable failures (error, timeout, rate limit, mid-stream failure, slow output) and works with no
  credentials, for development and automated tests.
- **FR-008**: Provider finish reasons MUST be mapped to the contract's finish reasons: normal completion to
  `stop`, length limit to `length`, provider safety block to `blocked`.
- **FR-009**: Provider errors MUST be classified into categories (temporary, rate-limited, timeout,
  authentication, invalid request, content blocked, unavailable) and surfaced to callers only as the
  service's documented error codes, never as raw provider messages.
- **FR-010**: Temporary, rate-limited and timeout failures before any output MUST be retried a bounded
  number of times with backoff; authentication and invalid-request failures MUST NOT be retried.
- **FR-011**: When retries for a model are exhausted, the gateway MUST fall back to the next model in the same
  tier's ordered list. It MUST NOT move to a different tier, larger or smaller, under any configuration;
  when every model of the requested tier has failed, the caller receives an error.
- **FR-012**: Once any output has been streamed for an attempt, the gateway MUST NOT fall back or retry; a
  failure then ends the stream with an `error` event.
- **FR-013**: After a model fails repeatedly, the gateway MUST stop sending new requests to it for a
  configurable cool-down period and resume afterwards. The one exception: when every model of the
  requested tier is cooling down, the gateway MUST still try the model whose cool-down ends soonest
  instead of failing without trying.
- **FR-014**: Each completion MUST have four configurable limits with documented defaults: the time to first
  output for one attempt; the overall wait for the first output across all attempts, retries and fallbacks;
  the time between pieces once output has started; and a total time for the whole completion. Reaching the
  overall wait before any output MUST end the request with the gateway-timeout error (an HTTP error from the
  chat route) and cancel the provider request.
- **FR-015**: When the caller disconnects or the overall limit is reached, the gateway MUST cancel the
  provider request.
- **FR-016**: The `usage` event MUST report input and output token counts as reported by the provider, and
  MUST report cost as unknown (cost computation belongs to spec 003).
- **FR-017**: The gateway MUST reject a request whose history exceeds the selected model's accepted input
  size with a clear error, rather than truncating it.
- **FR-018**: For every completion the gateway MUST write a structured summary log entry (tier, serving model,
  attempt count, fallback used, time to first output, total time, finish reason, token counts) and one entry
  per failed attempt (model, error category), tied to request, tenant and user identifiers.
- **FR-019**: Logs MUST NOT contain prompt text, answer text or credentials.
- **FR-020**: The chat route MUST obtain its answers from the gateway at a configured default tier; with only
  the stub provider configured it MUST behave as the deterministic placeholder of spec 001 did.
- **FR-021**: The gateway MUST keep no state between requests other than failure-cool-down tracking; it MUST
  NOT store message history or answers.
- **FR-022**: The published contract MUST evolve through the versioned process of the constitution. Contract
  1.1.0 is a one-time, owner-approved exception to the rule that breaking changes bump the major version: it
  adds new error codes (FR-024), turns the error-code list into an extensible list that clients must tolerate
  (the automated breaking-change check flags this once), and allows `usage` token counts to be unknown
  (null). After 1.1.0, adding an error code MUST NOT need a major version. All other event types, payload
  shapes and error codes of contract 1.0 are unchanged.
- **FR-023**: The gateway MUST also offer a helper that returns the complete answer as one result (full text, finish reason, token counts) for internal callers that need a whole short answer. It MUST be built on the streaming path, so retries, fallback, time limits, cancellation and logging behave identically in both modes, and a failure MUST surface as the same error categories.
- **FR-024**: The chat route MUST wait for the first output (bounded by the first-output time limit) before it starts the response. When every attempt fails before any output, it MUST return an HTTP error in the service's single error shape instead of opening a stream; once output has begun, failures MUST use the `error` event. Each new failure category (for example provider unavailable, provider timeout, input too large for every model of the tier) MUST have a stable error code and HTTP status in the contract.
- **FR-025**: Generation settings (at minimum maximum answer length and randomness) MUST have per-tier defaults and a per-tier hard ceiling set in configuration. A caller MAY lower a setting for one request but MUST NOT raise it above the ceiling; a request that tries MUST be rejected with a clear error naming the setting. An answer cut off by the maximum length MUST finish with the `length` reason.

### Key Entities

- **Tier**: a named class of model (small, medium, large) with an ordered list of model candidates.
- **Model candidate**: an exact, pinned model identifier plus the provider that serves it and its accepted
  input size.
- **Provider**: an external model service (or the stub) with credentials supplied from the environment.
- **Completion request**: tier, ordered message history, the request context (request, tenant, user), whether the caller wants a stream or the collected full answer, and optional lowered generation settings.
- **Generation settings**: maximum answer length and randomness, with a per-tier default and hard ceiling.
- **Completion result**: the collected form of a completed stream (full text, finish reason, token counts) returned by the helper for internal callers.
- **Attempt**: one try against one model candidate, with an outcome (success, failure category) and timings.
- **Completion outcome**: the final result of a request: served model, attempts, fallback used, finish reason,
  token counts, timings.
- **Failure cool-down**: a short-lived record that a model is temporarily skipped.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the same request, 100% of event streams produced through different providers have identical
  event types, payload shapes and ordering (verified by one shared conformance test run against every
  configured provider type).
- **SC-002**: A model behind a tier can be changed by editing configuration only, and the change takes effect
  within one service restart (verified once end to end).
- **SC-003**: With injected temporary failures on the first model, 100% of requests whose fallback model is
  healthy complete with a full answer, and none exceed the overall wait limit.
- **SC-004**: When every model in a tier fails, 100% of requests end with a single clear error and none hang:
  within the overall wait limit for failures before any output, and within the total time limit for failures
  after output has begun. Failures before any output are HTTP errors; failures after output has begun are
  `error` events.
- **SC-005**: After a caller disconnects, provider work for that request is stopped within 1 second in 100% of
  test runs.
- **SC-006**: The gateway adds no more than 50 ms to time-to-first-output compared with calling the stub
  provider directly, at the 95th percentile with 20 concurrent requests.
- **SC-007**: No prompt text, answer text or credential value appears in any log entry, verified by an
  automated scan over a full test run covering success, fallback, failure and cancellation.
- **SC-008**: 100% of invalid configurations (alias, empty tier, duplicate, unknown provider, missing
  credentials) are refused at startup with a message that names the offending entry.
- **SC-009**: All 132 existing tests (129 from spec 001 plus 3 for the documentation setting) and the contract
  tests keep passing without weakening any assertion.
- **SC-010**: 100% of requests that try to raise a generation setting above its tier ceiling are rejected before any provider is contacted, and 100% of answers cut off by the maximum length finish with the `length` reason.

## Assumptions

- Spec 002 does not decide which tier a request uses: callers pass a tier, and the chat route uses one
  configured default tier. Choosing a tier per request is the prompt router (spec 006). Cost records and
  persistence are spec 003, so `cost_usd` stays unknown here.
- Tool calls, retrieval, cache and guardrails are out of scope. The gateway passes the caller's messages
  through and does not add or alter system prompts.
- The roadmap fixes a multi-provider abstraction library as the way provider differences are hidden
  (constraint C-03). This spec states the behavior; the choice of library belongs to the plan.
- v1 supports and documents two real providers, Anthropic and OpenAI, plus the stub; which of them are
  enabled, and for which tiers, is configuration. Further providers are a configuration change. Only the stub is required to be exercised in automated tests; a live-provider check is a
  separate, explicitly invoked test (constitution principle III).
- Model identifiers, tier assignments, timeouts, retry counts and the cool-down period have documented
  defaults and are configurable through the environment or a configuration file.
- Fallback stays within one tier, decided in clarification. Moving to a larger tier (cost) or a smaller one
  (quality) on failure is a deliberate non-goal; only the router (spec 006) chooses tiers.
- Token counts come from the provider; the gateway does not tokenize messages itself, so the size check in
  FR-017 relies on each model's documented input limit and a conservative estimate.
- Caller identity (tenant, user, request identifier) is available from spec 001's request context.
- The contract version moves from 1.0.0 to 1.1.0: provider failures need new error codes (FR-024), which
  are additive. The first byte of a successful response now arrives after the model's first output (it was
  immediate with the placeholder), so SC-006 of spec 001 is measured with the stub provider.
