---

description: "Task list for spec 002 LLM Gateway"
---

# Tasks: LLM Gateway

**Input**: Design documents from `/specs/002-llm-gateway/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (proposed 1.1.0 in `contracts/v1.1/`), quickstart.md

**Tests**: INCLUDED. Constitution principle III (Test-First) is mandatory: within every story, tests are written first and MUST fail before the code they cover exists. All gateway tests use the stub provider or a faked LiteLLM stream; nothing in the default test run contacts a real provider or needs credentials.

**Organization**: grouped by user story. US1 and US2 are both P1; US3 and US4 are P2; US5 is P3. Paths are relative to the repository root.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1..US5 map to the user stories in spec.md
- Spec 001's 129 tests (plus the 3 docs tests) must keep passing **unchanged** throughout (SC-009). If one needs editing, that is a signal to stop and reconsider, not to loosen the assertion.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dependency and scaffolding

- [X] T001 Add `litellm==1.106.2` (exact pin) to `dependencies` in `pyproject.toml`, run `uv lock` and `uv sync`, and if `uv run mypy --strict src` reports missing types for `litellm` add `[[tool.mypy.overrides]] module = "litellm.*" ignore_missing_imports = true` (that module only). Register a `live` pytest marker and set `addopts = "-m 'not live'"` so real-provider tests are skipped by default.
- [X] T002 [P] Create package skeleton: `src/ai_services/gateway/__init__.py`, `src/ai_services/gateway/providers/__init__.py`, `tests/unit/gateway/__init__.py`, `tests/live/__init__.py`.
- [X] T003 [P] Create `config/gateway.example.yaml` with the structure from data-model.md Configuration: `default_tier: medium`; `timeouts` first output 15 (per attempt), pre-output 45 (overall wait for the first piece), idle 20, total 120; `retry` 2 attempts, backoff 0.25 s base and 2.0 s cap; `cooldown` threshold 3, 30 s; tiers `small` = `[anthropic/claude-haiku-5-5, openai/gpt-5-nano-2025-08-07]`, `medium` = `[anthropic/claude-sonnet-5-5, openai/gpt-5-mini-2025-08-07]`, `large` = `[anthropic/claude-opus-5-5, openai/gpt-5-2025-08-07]`; generation per tier `max_output_tokens` default/ceiling small 2048/4096, medium 4096/8192, large 8192/16384, `temperature` default 0.3 and ceiling 1.0. Comment every field. Add `config/gateway.local.yaml` to `.gitignore`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: governance prerequisites, then contract 1.1.0 applied test-first, new error codes, nullable usage counts, settings, shared gateway types, and the one-time gate exception. No story starts until this is done.

**⚠️ CRITICAL**: no user story work starts until this phase is complete.

### Governance prerequisites (before any code or contract change)

- [X] T004 Amend the constitution to v1.3.0 (MINOR) with `/speckit-constitution`, and commit it before any contract change (T011): add to Governance that an exception to a MUST requires a written reason, an owner decision and an expiry condition, recorded in the plan's Complexity Tracking; name the contract 1.1.0 error-code exception (plan Complexity Tracking, `contracts/README.md`) as the first example, with its expiry "delete `contracts/oasdiff-ignore.txt` once 1.1.0 is the baseline (T058)". Update the Sync Impact Report. This is the legal basis for T011 and T017.
- [X] T005 Amend `.specify/memory/roadmap.md` with `/speckit-roadmap-write` before implementation starts (constitution phase-in rule: the roadmap MUST name the owner of each deferred gate): set spec 002 to `specced`, add to spec 004 that changes to the models serving a tier must pass its eval set (principle II, deferred from spec 002), and keep spec 003 as the owner of the persistent per-request record (principle VI, already recorded).

### Tests first (must fail)

- [X] T006 [P] Extend `tests/unit/test_errors.py`: `EXPECTED` gains `"upstream_unavailable": 503`, `"upstream_timeout": 504`, `"upstream_error": 502`, `"input_too_large": 422`; the code-to-status test still asserts the full mapping; `Retry-After` header is present for `upstream_unavailable` when `retry_after_seconds` is set.
- [X] T007 [P] Extend `tests/unit/test_events.py`: a `usage` payload with `input_tokens: None` and/or `output_tokens: None` is valid ("`input_tokens`/`output_tokens` may be `null` when the provider did not report them"); negative counts are still rejected; `cost_usd` null stays valid.
- [X] T008 [P] Extend `tests/unit/test_config.py`: `GATEWAY_CONFIG` is optional (None by default, empty string treated as unset); `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are optional secrets (`SecretStr`), `repr(settings)` and `str(settings)` never show their values, empty string treated as unset.
- [X] T009 [P] Create `tests/unit/gateway/test_errors.py`: `ProviderError` has `category` in `temporary | rate_limited | timeout | unavailable | auth | context_too_large | content_blocked | invalid_request` and optional `retry_after_seconds`, and carries no provider text; `GatewayError(code, retry_after_seconds)` converts to a `ServiceError` with the codes and statuses of research R6 (`upstream_unavailable` 503, `upstream_timeout` 504, `upstream_error` 502, `input_too_large` 422); an unexpected exception maps to `internal_error` with a generic message.
- [X] T010 [P] Update the contract tests for 1.1.0: in `tests/contract/test_openapi_conformance.py` add the new statuses `502` and `504` to a temporary `COVERED_ELSEWHERE` entry with a comment "covered by tests/integration/test_gateway_failures.py (US3); T045 removes this"; in `tests/contract/test_contract_drift.py` make `project()` treat `x-extensible-enum` exactly like `enum` (compare sorted values); in `tests/contract/test_event_schema.py` add a test that a `usage` frame with null token counts validates, and that the schema description mentions the null tolerance; add a test that the contract's `info.version` is `1.1.0`.

### Implementation

- [X] T011 Apply contract 1.1.0: copy `specs/002-llm-gateway/contracts/v1.1/openapi.yaml` to `contracts/v1/openapi.yaml` and `specs/002-llm-gateway/contracts/v1.1/events.schema.json` to `contracts/v1/events.schema.json` (same paths, new content). Do not hand-edit; the proposed files are the reviewed source.
- [X] T012 Add the four codes to `ErrorCode` and `STATUS` in `src/ai_services/errors.py` exactly as in T006 (makes T006 pass).
- [X] T013 Make `UsageData.input_tokens` and `output_tokens` nullable (`int | None`, `ge=0` when present) in `src/ai_services/events.py` (makes T007 pass). Keep `cost_usd` as is.
- [X] T014 In `src/ai_services/schemas.py` make `ErrorDetail.code` emit an extensible enum in the generated OpenAPI (`x-extensible-enum` with the values of `ErrorCode`, plus the description "clients MUST treat a code they do not recognise as a generic failure and use the HTTP status") instead of a strict `enum`; in `src/ai_services/api/v1/chat.py` add `502` and `504` entries to `_ERROR_RESPONSES` and extend the descriptions of `422` and `503` to match `contracts/v1/openapi.yaml`. Run `uv run pytest tests/contract` until green (apart from nothing: the temporary `COVERED_ELSEWHERE` entry keeps the coverage test passing).
- [X] T015 Add to `Settings` in `src/ai_services/config.py`: `gateway_config: Path | None = None`, `anthropic_api_key: SecretStr | None = None`, `openai_api_key: SecretStr | None = None`, each treating an empty string as unset (makes T008 pass). Add `GATEWAY_CONFIG`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (commented, no values) to `.env.example`, and pass them through in `compose.yaml` (`GATEWAY_CONFIG: ${GATEWAY_CONFIG:-}`, `ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}`, `OPENAI_API_KEY: ${OPENAI_API_KEY:-}`) plus a read-only volume `./config:/app/config:ro` on the service.
- [X] T016 Create `src/ai_services/gateway/types.py` (`Message`, `GenerationSettings` with `max_output_tokens: int | None` and `temperature: float | None`, `CompletionRequest(tier, messages, settings)`, `Completion(text, finish_reason, input_tokens, output_tokens, model, attempts, fallback_used)`) and `src/ai_services/gateway/errors.py` (`ProviderError`, `GatewayError`, `GenerationSettingError`, `UnknownTierError`, and the mapping to `ServiceError` per research R4 and R6) (makes T009 pass). Depends on T012.
- [X] T017 Add one-time exception support to `scripts/contract-diff.sh`: if `contracts/oasdiff-ignore.txt` exists, pass it to `oasdiff` as `--err-ignore`, printing a loud notice that an ignore list is in use. Copy `specs/002-llm-gateway/contracts/oasdiff-ignore-1.0-to-1.1.txt` to `contracts/oasdiff-ignore.txt`. Verify, and record the output in the pull request description: with `BASE_FILE` set to a copy of the 1.0.0 contract the script passes; with an unrelated breaking change (a removed route) added it still fails. Also add the same file mention to the script's header comment ("single use: delete after 1.1.0 is the baseline, see T058").

**Checkpoint**: unit and contract tests are green, spec 001's tests are untouched and passing, `uv run ruff check . && uv run mypy --strict src && uv run pyright` are clean.

---

## Phase 3: User Story 1 - Request a completion by tier and get a uniform stream (Priority: P1) 🎯 MVP

**Goal**: any component can request a completion by tier and receive the service's event stream (or a collected result); the chat route uses the gateway at the default tier; the stub provider makes this work with no credentials.

**Independent Test**: with only the stub configured, request a completion at each tier and verify an ordered stream ending in one `done`; then the chat route behaves exactly as in spec 001.

### Tests for User Story 1 (write first, must fail)

- [X] T018 [P] [US1] Create `tests/unit/gateway/test_stub_provider.py`: every stub id of research R10 behaves as described (`stub/default` yields the placeholder text word by word, then a finish reason `stop`, then usage; `stub/empty` yields no text; `stub/blocked` finishes with `blocked`; `stub/slow` and `stub/stall` delay; `stub/fail-*` raise `ProviderError` with the matching category; `stub/fail-midstream` raises after some text); `stub/default` honors a delay setting and an injected `fail_after` hook that raises a plain `RuntimeError`; the stream can be closed early and the stub records that it observed the close.
- [X] T019 [P] [US1] Create `tests/unit/gateway/test_provider_conformance.py`: one shared test body run against both the stub and the LiteLLM adapter (with `litellm.acompletion` monkeypatched to return a fake async stream shaped like the real one: content deltas, then a `finish_reason` chunk, then a usage-only chunk) asserting identical normalised output: `ProviderChunk` text pieces in order, one finish reason, one usage; finish-reason mapping `stop` to `stop`, `length` to `length`, `content_filter` to `blocked`; missing usage yields null counts; this is SC-001.
- [X] T020 [P] [US1] Create `tests/unit/gateway/test_gateway_stream.py`: `Gateway.stream()` yields `(event, payload)` pairs `token` (consecutive `index` from 0), then one `usage`, then exactly one `done`; the finish reason is held until the provider stream ends so `usage` always precedes `done`; unknown tier raises `UnknownTierError` before any provider is called; an empty answer still yields `usage` and `done`; provider usage `None` yields `usage` with null counts; `Gateway.complete()` returns a `Completion` whose text, finish reason and token counts equal the collected stream (FR-023).
- [X] T021 [P] [US1] Create `tests/integration/test_chat_gateway.py`: with the default stub-only configuration the chat route returns the same deterministic stream as spec 001 (`token…`, `usage`, `done`); `app.state.gateway` exists and the route uses the configured `default_tier`; a request through each of the three tiers (via the facade, using a custom config with different stub models per tier) returns identical event shapes.

### Implementation for User Story 1

- [X] T022 [P] [US1] Create `src/ai_services/gateway/providers/base.py`: `ProviderChunk` (exactly one of `text`, `finish_reason` in `stop|length|blocked`, `usage` as `(input|None, output|None)`) and the `Provider` protocol: `stream(model_id, messages, settings) -> AsyncIterator[ProviderChunk]` that raises `ProviderError`.
- [X] T023 [P] [US1] Create `src/ai_services/gateway/providers/stub.py` with the stub ids of research R10; its default text is the sentence from `src/ai_services/placeholder.py` (`PLACEHOLDER_TEXT`), split into word tokens exactly as before; accepts `delay_ms` and a `fail_after` callable hook (raising `RuntimeError("injected fault")`) so spec 001's `PLACEHOLDER_TOKEN_DELAY_MS` and `app.state.fail_after_events` keep working; records when its stream is closed (makes T018 pass).
- [X] T024 [US1] Create `src/ai_services/gateway/providers/litellm_provider.py`, the only file that imports `litellm`: calls `litellm.acompletion(model=f"{provider}/{model_id}", messages=..., stream=True, stream_options={"include_usage": True}, api_key=<explicit>, max_tokens=..., temperature=...)`, consumes the stream inside `contextlib.aclosing`, maps chunks to `ProviderChunk` (text deltas, finish reason with `content_filter` mapped to `blocked`, usage from the final chunk), and maps LiteLLM exceptions to `ProviderError` categories per the table in research R4 (makes T019 pass). Never put provider message text into a `ProviderError`.
- [X] T025 [US1] Create `src/ai_services/gateway/config.py` with the pydantic models of data-model.md Configuration (`GatewayConfig`, `Tier`, `ModelCandidate`, `Timeouts`, `RetryPolicy`, `CooldownPolicy`, `GenerationLimits`) and the built-in default configuration: all three tiers served by `stub/default`, `default_tier: medium`, defaults as in the example file. YAML loading and validation come in US2.
- [X] T026 [US1] Create the `Gateway` facade in `src/ai_services/gateway/__init__.py` and the happy path in `src/ai_services/gateway/orchestrator.py`: `open(request)` resolves the tier (raising `UnknownTierError`), calls the first model's provider, returns a `CompletionStream` that yields `(event, payload)` pairs in the order `token…`, `usage`, `done`; `stream(request)` iterates it; `complete(request)` collects it into a `Completion` (FR-023). Retries, fallback, limits and timeouts are added by later tasks in the same file (makes T020 pass).
- [X] T027 [US1] Rewire the chat route: in `src/ai_services/main.py` build the gateway from settings and store it as `app.state.gateway`; in `src/ai_services/api/v1/chat.py` replace `placeholder_events` with the gateway at `default_tier`, keeping the `active_streams` counter, the `fail_after_events` hook (passed to the stub) and the mid-stream failure handling (any non-`ProviderError` exception becomes the `error` event with code `internal_error` and message `The stream failed.`). Then delete `src/ai_services/placeholder.py` (its text now lives in the stub). Makes T021 pass.
- [X] T028 [US1] Regression gate: run the whole existing suite (`uv run pytest`) and confirm that spec 001's tests pass without any edit to them; list any failing test in the task notes and fix the implementation, never the assertion (SC-009).

**Checkpoint**: US1 is a working increment: a stub-backed gateway serves the chat route and the helper, and nothing from spec 001 regressed.

---

## Phase 4: User Story 2 - Map tiers to pinned models through configuration (Priority: P1)

**Goal**: operators define which exact models serve each tier in a YAML file; invalid configuration is refused at startup with a message naming the entry; generation settings have per-tier defaults and ceilings.

**Independent Test**: change a tier's model in the file and restart to see it take effect; supply an alias, an empty tier, a duplicate or a missing credential and see startup refuse.

### Tests for User Story 2 (write first, must fail)

- [X] T029 [P] [US2] Create `tests/unit/gateway/test_gateway_config.py` covering every rule of data-model.md, each failure naming the offending entry: `tiers` "must contain `small`, `medium` and `large`"; each tier has a non-empty, duplicate-free `models` list; model entry is `provider/model-id` with provider in `anthropic`, `openai`, `stub`; "the id must not end in `latest`"; the id "must be in LiteLLM's model map for its provider, or carry an explicit `max_input_tokens` override"; "its provider must be enabled with a credential" (`anthropic` needs `ANTHROPIC_API_KEY`, `openai` needs `OPENAI_API_KEY`, `stub` needs none); `default_tier` "must be one of the configured tiers"; "`timeouts.*`, `retry.*`, `cooldown.*` positive numbers; `first_output_seconds <= pre_output_seconds <= total_seconds`; `idle_seconds <= total_seconds`"; "`0 < default <= ceiling`; temperature between 0 and 2"; YAML round trip; changing the models of a tier in the file changes the resolved tier; no credential value appears in any raised message.
- [X] T030 [P] [US2] Create `tests/integration/test_gateway_startup.py`: `create_app` with an invalid gateway configuration exits with a message naming the entry and does not start; with `GATEWAY_CONFIG` unset the built-in stub-only configuration is used; with a valid file the tiers resolve to its models; credentials supplied for a provider never appear in the startup log output.
- [X] T031 [P] [US2] Create `tests/unit/gateway/test_limits.py`: per-tier defaults apply when a caller passes nothing; a caller may lower `max_output_tokens` and `temperature`; a value above its ceiling raises `GenerationSettingError` naming the setting, before any provider is called; a model that does not support a parameter has it dropped explicitly (faked `litellm.get_supported_openai_params`) and the drop is logged once at startup with model and parameter only; an answer cut by the maximum length finishes with `length` (stub).
- [X] T032 [P] [US2] Create `tests/unit/gateway/test_example_config.py`: `config/gateway.example.yaml` loads with fake credentials for both providers and resolves to exactly the six pinned model ids of research R8, with the documented defaults.

### Implementation for User Story 2

- [X] T033 [US2] Extend `src/ai_services/gateway/config.py`: YAML loader (`yaml.safe_load`, never `yaml.load`) and all validation rules of T029, quoting each rule's wording in the error message; the loader takes the credentials from `Settings` and checks them; model existence uses LiteLLM's model map through a small helper in `providers/litellm_provider.py` (keeping the import there) so tests can fake it (makes T029 and T032 pass).
- [X] T034 [US2] Create `src/ai_services/gateway/limits.py`: `resolve_generation(tier_limits, requested)` returning the effective settings, rejecting values above the ceiling with `GenerationSettingError`; `supported_parameters(model)` helper (via the LiteLLM adapter) used at startup to drop unsupported parameters explicitly (makes T031 pass). Input-size estimation is added in US3.
- [X] T035 [US2] Wire configuration into startup in `src/ai_services/main.py`: load the YAML from `settings.gateway_config` (built-in default when unset), fail fast with `SystemExit` and the message from the loader, log once at startup the tier-to-model mapping (model ids only, no credentials) and any dropped parameters; pass the effective generation settings into every provider call from the orchestrator (makes T030 pass).

**Checkpoint**: configuration changes take effect on restart, invalid configurations are refused clearly, and ceilings protect cost.

---

## Phase 5: User Story 3 - Survive a provider failure with retries and fallback (Priority: P2)

**Goal**: temporary failures are retried briefly, then the gateway falls back within the tier; total failure is one fast, clear error; safety blocks and mid-stream failures are never worked around.

**Independent Test**: use stub models with injected failures and verify retry counts, fallback order and final outcomes, including the chat route's HTTP errors.

### Tests for User Story 3 (write first, must fail)

- [X] T036 [P] [US3] Create `tests/unit/gateway/test_cooldown.py` (fake clock): after "`failure_threshold` consecutive counted failures" a model is skipped for `seconds`; a success clears the counter; the first request after expiry is a trial; categories that count are `temporary`, `rate_limited`, `timeout`, `unavailable`, `auth`, and those that do not are `content_blocked`, `invalid_request`, `context_too_large`; when every model of a tier is cooling down the gateway still tries the one whose cool-down ends soonest (FR-013 exception) instead of failing without trying; no tenant data is stored.
- [X] T037 [P] [US3] Create `tests/unit/gateway/test_gateway_failover.py` (fake sleep and clock, stub models): `temporary`, `rate_limited` and `timeout` are retried up to `max_attempts_per_model` with backoff (base 0.25 s, cap 2.0 s, full jitter; a provider `retry_after` is honored but capped at 5 s) before falling back; `unavailable`, `auth` and `context_too_large` skip retries and fall back immediately; `invalid_request` neither retries nor falls back and ends as `upstream_error`; `content_blocked` neither retries nor falls back and ends as `done` with `blocked`; a failure after the first piece never retries or falls back and ends the stream with an `error` event; when every model fails the error code follows research R6 (`upstream_unavailable`, `upstream_timeout` or `upstream_error`); fallback never leaves the requested tier; a cooling-down model is skipped and tried again after expiry.
- [X] T038 [P] [US3] Create `tests/unit/gateway/test_input_size.py`: the estimate is `ceil(total_characters / 3)`; a model whose `max_input_tokens` cannot take the conversation is skipped in favor of the next; when no model in the tier can, `GatewayError` with code `input_too_large` is raised before any provider call; the check never truncates or alters the messages.
- [X] T039 [P] [US3] Create `tests/integration/test_gateway_failures.py` through the chat route with stub tiers set by custom configuration: `[stub/fail-temporary, stub/default]` returns a normal answer; `[stub/fail-temporary, stub/fail-rate-limited]` returns 503 `upstream_unavailable` with `Retry-After`; `[stub/fail-timeout]` returns 504 `upstream_timeout`; `[stub/fail-auth]` returns 502 `upstream_error`; a conversation too large for the tier's models returns 422 `input_too_large`; `[stub/fail-midstream, stub/default]` returns 200 with some `token` events then one `error` event and no fallback; `[stub/blocked, stub/default]` returns `usage` then `done` with `blocked` and never touches the second model; every HTTP error uses the standard shape with `request_id` and no stream is opened; failures before output complete within the overall wait limit, and a tier of slow failing stub models with a short `pre_output_seconds` returns 504 `upstream_timeout` and never opens a stream.
- [X] T040 [P] [US3] Extend `tests/contract/test_openapi_conformance.py`: add cases that produce `502`, `504`, `503` (upstream) and `422` (`input_too_large`) through the app using stub configurations and validate each body against the contract schemas.

### Implementation for User Story 3

- [X] T041 [P] [US3] Create `src/ai_services/gateway/cooldown.py` per research R15 (in-memory, per `provider/model_id`, injectable clock) (makes T036 pass).
- [X] T042 [US3] Extend `src/ai_services/gateway/orchestrator.py` with the attempt loop: model order from the tier, cool-down skipping, the classification table of research R4, retries with exponential backoff and full jitter, `retry_after` capped at 5 s, the rule that nothing is retried or replaced after the first piece, the `blocked` terminal path, and the final error code selection of research R6 (makes T037 pass). Dependencies injected (sleep, clock, random) for deterministic tests.
- [X] T043 [US3] Extend `src/ai_services/gateway/limits.py` with `estimate_tokens(messages)` and the model selection by input size, raising `GatewayError(input_too_large)` (makes T038 pass).
- [X] T044 [US3] Register a handler so `GatewayError` becomes the standard error response (with `Retry-After` for 503) in `src/ai_services/errors.py`; make `src/ai_services/api/v1/chat.py` call `gateway.open()` before building the `EventSourceResponse`, so failures before any output are HTTP errors and nothing streams (FR-024); keep mid-stream failures as `error` events (makes T039 pass).
- [X] T045 [US3] Remove the temporary `COVERED_ELSEWHERE` entry added in T010 so `test_every_documented_status_is_covered` requires the new cases of T040, and run `uv run pytest tests/contract tests/integration` until green.

**Checkpoint**: a provider outage costs retries and a fallback, not an outage of the service, and every failure is explicit.

---

## Phase 6: User Story 4 - Bounded time and no wasted work (Priority: P2)

**Goal**: every completion has time limits; abandoning a request stops the provider work.

**Independent Test**: stub models that never answer, stall or run slowly, plus a disconnect, show the limits firing and the provider stream being closed.

### Tests for User Story 4 (write first, must fail)

- [X] T046 [P] [US4] Create `tests/unit/gateway/test_gateway_timeouts.py` with millisecond-scale limits: a first-output timeout counts as a `timeout` attempt (retry then fallback applies); an idle stall after partial output ends with an `error` event (`upstream_timeout`) and no fallback; exceeding `total_seconds` ends the stream with an `error` event and closes the provider stream; backoff sleeps never exceed the remaining total time; the overall wait (`pre_output_seconds`) bounds the sum of all attempts, retries, backoff and fallbacks before the first piece: when it is reached with no output the request ends with `GatewayError` code `upstream_timeout` and the provider stream is closed; the four limits are read from the configuration.
- [X] T047 [P] [US4] Create `tests/integration/test_gateway_cancellation.py`: a client disconnect mid-stream makes the stub observe the close within 1 second (SC-005) and `active_streams` return to 0; a disconnect while the route is still waiting for the first output (before any response) also closes the provider stream; existing graceful-shutdown behavior is unchanged.

### Implementation for User Story 4

- [X] T048 [US4] Extend `src/ai_services/gateway/orchestrator.py` with `asyncio.timeout` around the first read of each attempt, a timeout on every later read, an overall deadline of `pre_output_seconds` over all attempts, retries, backoff and fallbacks until the first piece, a total deadline over the whole completion including backoff, passing the smallest of the first-output limit, the remaining overall wait and the remaining total as the LiteLLM `timeout`, and closing the provider stream (`aclosing`) on cancellation or deadline (makes T046 pass).
- [X] T049 [US4] Make `src/ai_services/api/v1/chat.py` safe against cancellation while awaiting `gateway.open()` and while streaming: always close the gateway stream and keep `active_streams` correct in every path (makes T047 pass). Depends on T044.

**Checkpoint**: nothing hangs, and abandoned requests stop costing money.

---

## Phase 7: User Story 5 - See what happened without exposing content (Priority: P3)

**Goal**: one content-free summary per completion and one entry per failed attempt, tied to request, tenant and user ids.

**Independent Test**: run a completion that needed one fallback, find its entries by request id, and confirm no message text appears.

### Tests for User Story 5 (write first, must fail)

- [X] T050 [P] [US5] Create `tests/integration/test_gateway_logs.py`: after a completion that needed one fallback, the logs for its request id contain exactly one `completion_finished` with `tier`, `model`, `attempts`, `fallback_used`, `first_output_ms`, `total_ms`, `finish_reason`, `input_tokens`, `output_tokens`, and one `completion_attempt_failed` per failed attempt with `model` and `category`; all carry `request_id`, `tenant_id` and `user_id`; completions made through the `complete()` helper are logged the same way.
- [X] T051 [P] [US5] Create `tests/integration/test_no_content_in_gateway_logs.py` (SC-007): across success, fallback, total failure, mid-stream failure, blocked, cancellation and an invalid configuration at startup, capture all log output and assert that no sentinel prompt text, no sentinel answer text (a stub answer variant containing a unique marker) and no credential value appears.

### Implementation for User Story 5

- [X] T052 [US5] Create `src/ai_services/gateway/logging.py` with the two log helpers (never accepting message or answer text as arguments) and call them from `src/ai_services/gateway/orchestrator.py` at the end of every completion path and for every failed attempt (makes T050 and T051 pass).

**Checkpoint**: operators can diagnose any completion from its request id, and logs stay content-free.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T053 [P] Create `tests/live/test_live_providers.py` (marker `live`, skipped unless `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set and `-m live` is passed): a short real completion through each configured provider has the normal event shape and a `stop` finish reason; a deliberately tiny output limit finishes with `length`; cancelling mid-stream closes the connection; the reasoning-budget check of research R13 (a small tier request on the OpenAI model returns non-empty text with the configured default budget). Document how to run it at the top of the file.
- [X] T054 Create `config/gateway.fallback-demo.yaml` (stub-only: `medium` = `[stub/fail-temporary, stub/default]`, other tiers `stub/default`) used for demos and the load test; run `docker compose up --build --wait` with `GATEWAY_CONFIG=config/gateway.fallback-demo.yaml`, run `uv run python scripts/load-test.py --streams 20` and `--streams 100`, and record the results (all streams end in one `done`, p95 time to first event under 500 ms) in the "Verified on" note of `specs/002-llm-gateway/quickstart.md` (constitution: the streaming load test applies because the SSE path changed).
- [X] T055 [P] Create `tests/integration/test_gateway_overhead.py` (SC-006): at 20 concurrent requests the 95th-percentile time to first output through the gateway with `stub/default` is at most 50 ms above iterating the stub provider directly.
- [X] T056 Run `quickstart.md` end to end (steps 1 to 12), fix any discrepancy between the guide and behavior, and add a "Verified on" section with dates and results.
- [X] T057 Final constitution check: re-read the plan's Constitution Check table, confirm each Pass row holds in the finished code and each Deferred row (II owner spec 004, VI owner spec 003) still names its owner on the roadmap; record any new deviation in the plan's Complexity Tracking.
- [X] T058 (done 2026-10-21, after the merge) Delete `contracts/oasdiff-ignore.txt` and the script's reference to it, because from 1.1.0 on the extensible error-code enum makes the exception unnecessary; confirm `scripts/contract-diff.sh` passes against the new baseline without it.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; BLOCKS all stories. Within it: T004 (constitution amendment) and T005 (roadmap note) first, committed before T011 applies the contract; then tests T006 to T010; T011 to T016 in order of their dependencies; T017 before any push, because applying contract 1.1.0 (T011) makes CI's contract gate fail without the exception.
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on Foundational and US1 (it extends `gateway/config.py` and wires startup).
- **US3 (Phase 5)**: depends on US1 and US2 (orchestrator and limits files, tier configuration for the integration tests).
- **US4 (Phase 6)**: depends on US3 (it extends the same orchestrator and the chat route's `open()` handling).
- **US5 (Phase 7)**: depends on US3 (it logs attempts and fallback); can run alongside US4.
- **Polish (Phase 8)**: after the stories you intend to ship; T058 only after merge.

### Within Each Story

- Tests first; confirm they fail for the right reason before implementation.
- Files touched by several tasks (`orchestrator.py`, `gateway/config.py`, `limits.py`, `chat.py`, `main.py`) are edited in task order and never in parallel.
- Commit after each task or logical group; run `uv run ruff check . && uv run mypy --strict src && uv run pyright && uv run pytest` at every checkpoint.

### Parallel Opportunities

- Setup: T002 and T003.
- Foundational tests: T006 to T010 together.
- US1 tests T018 to T021 together; T022 and T023 together.
- US2 tests T029 to T032 together.
- US3 tests T036 to T040 together; T041 alongside T043 only if `limits.py` is not being touched by another task.
- US4 tests T046 and T047 together; US5 tests T050 and T051 together; US4 and US5 implementation can proceed in parallel once US3 is done (different files, except both touch `orchestrator.py`: do T048 before T052).

---

## Parallel Example: User Story 1

```text
# Launch all US1 tests together:
Task: "Stub provider tests in tests/unit/gateway/test_stub_provider.py"
Task: "Provider conformance tests in tests/unit/gateway/test_provider_conformance.py"
Task: "Gateway stream tests in tests/unit/gateway/test_gateway_stream.py"
Task: "Chat route via gateway tests in tests/integration/test_chat_gateway.py"

# Then the two independent provider files:
Task: "Provider protocol in src/ai_services/gateway/providers/base.py"
Task: "Stub provider in src/ai_services/gateway/providers/stub.py"
```

---

## Implementation Strategy

### MVP First (US1 plus US2, both P1)

1. Phase 1 Setup, then Phase 2 Foundational (including the contract exception, T017).
2. Phase 3 US1: the gateway, the stub and the chat route working with no credentials.
3. Phase 4 US2: pinned models and validated configuration, so real providers can be switched on.
4. **Stop and validate**: quickstart steps 1, 7 and 8. You can already run real Anthropic and OpenAI answers, with no fallback yet.

### Incremental Delivery

1. Setup + Foundational → contract 1.1.0 live, spec 001 untouched.
2. US1 → uniform stream through the gateway (stub only).
3. US2 → real providers by configuration, ceilings on cost.
4. US3 → fallback and clear failures (motivation 2 of the project).
5. US4 → time limits and cancellation.
6. US5 → diagnosability.
7. Polish → live checks, load test, constitution and roadmap updates.

### Notes

- Every acceptance scenario maps to a test: US1 (T018 to T021), US2 (T029 to T032), US3 (T036 to T040), US4 (T046, T047), US5 (T050, T051).
- Functional requirements: FR-001 to FR-002 T020, T026; FR-003 to FR-006 T029, T033; FR-007 T018, T023; FR-008 T019, T024; FR-009 to FR-013 T009, T036, T037, T042; FR-014 and FR-015 T046 to T049; FR-016 T020; FR-017 T038, T043; FR-018 and FR-019 T050 to T052; FR-020 T021, T027; FR-021 T036, T041; FR-022 T004, T006 to T014, T017; FR-023 T020, T026; FR-024 T039, T044; FR-025 T031, T034.
- Success criteria: SC-001 T019; SC-002 T030; SC-003 T039; SC-004 T039; SC-005 T047; SC-006 T055; SC-007 T051; SC-008 T029; SC-009 T028; SC-010 T031.
- Not covered by an automated test: nothing in the default run contacts a real provider; T053 covers that opt-in.
