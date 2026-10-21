# Research: LLM Gateway

All items resolve choices the spec left to the plan. Facts about LiteLLM below were checked on 2026-10-21
against `litellm==1.106.2` in a throwaway environment (not added to the repository).

## R1 — How to call providers: LiteLLM for calls only
- **Decision**: use `litellm.acompletion(..., stream=True, stream_options={"include_usage": True})` inside one
  file (`providers/litellm_provider.py`). Everything else talks to our own `Provider` protocol.
- **Rationale**: roadmap C-03. Confining the import keeps tests provider-agnostic and lets the stub implement
  the same protocol. Explicit `api_key=` per call (from our settings) avoids ambient credentials.
- **Alternatives**: direct Anthropic and OpenAI SDKs (more code, no shared exception model); LiteLLM proxy
  server (another service to run, not needed).

## R2 — Retry, fallback and cool-down: our own orchestrator
- **Decision**: the orchestrator implements attempts, backoff, in-tier fallback, cool-down and deadlines.
- **Rationale**: the spec's rules are specific and must be testable offline: tier-only fallback, no fallback
  after first output, no fallback on safety blocks, cool-down after repeated failure. See Complexity
  Tracking in the plan for the rejected alternative (LiteLLM Router; its mid-stream behavior was not
  evaluated in depth).

## R3 — Stream shape from LiteLLM and the ordering consequence
- **Finding** (mocked stream, checked): chunks carry `delta.content` pieces; a chunk with
  `finish_reason="stop"` arrives **before** a final chunk with `usage` and no choices.
- **Decision**: the provider adapter yields `ProviderChunk(text | finish_reason | usage)`; the orchestrator
  holds the finish reason until the stream ends so the service's order is always `token…`, then `usage`, then
  `done`. If a provider sends no usage, `usage` is emitted with null counts (FR edge case).
- **Alternatives**: emitting `done` first (violates the contract's order).

## R4 — Error classification
| Provider signal (LiteLLM exception) | Category | Retry on same model | Fallback to next model |
|---|---|---|---|
| connection error, internal server error, bad gateway | `temporary` | yes | yes |
| rate limit | `rate_limited` | yes (honors a short `retry-after`, capped at 5 s) | yes |
| timeout (ours or the provider's) | `timeout` | yes | yes |
| service unavailable, model not found | `unavailable` | no | yes |
| authentication, permission denied | `auth` | no | yes (specific to that provider) |
| context window exceeded | `context_too_large` | no | yes (next model may accept more) |
| content policy violation, finish reason `content_filter` | `content_blocked` | no | **no**; ends as `done` with `blocked` |
| bad request, unprocessable, anything else invalid | `invalid_request` | no | no; surfaces as `upstream_error` |

Failures that count toward the cool-down: `temporary`, `rate_limited`, `timeout`, `unavailable`, `auth`.
`content_blocked`, `invalid_request` and `context_too_large` do not (they say nothing about model health).

## R5 — Mid-stream rule and the first-output wait
- **Decision**: the orchestrator's `open()` runs attempts until one produces its first piece (or a terminal
  `blocked`), then returns a stream object holding that first piece. After that, no retry or fallback.
  The chat route calls `open()` before building the response (FR-024), so pre-output failures raise a
  `ServiceError` handled by the existing error handlers; mid-stream failures become an `error` event.
- **Rationale**: matches the clarified spec; keeps the HTTP error contract meaningful.

## R6 — Error codes and statuses (contract 1.1.0)
| Situation | Code | HTTP | Mid-stream `error` event code |
|---|---|---|---|
| all models failed: temporary, rate-limited or unavailable | `upstream_unavailable` | 503 (+ `Retry-After`) | same |
| all attempts timed out | `upstream_timeout` | 504 | same (idle stall or total limit) |
| provider rejected the request in a way retries cannot fix (auth on every model, invalid request) | `upstream_error` | 502 | same |
| history too large for every model of the tier | `input_too_large` | 422 | not applicable (checked before any call) |
| unexpected exception (including the spec 001 injected fault) | `internal_error` | 500 | `internal_error` |
Messages are generic; provider text never leaves the service.

## R7 — Contract change and the gate (verified)
- **Finding**: `oasdiff` flags added response enum values as breaking, and converting the enum to
  `x-extensible-enum` is flagged too (one-time "became not enum").
- **Decision** (owner's choice): ship 1.1.0 with `x-extensible-enum` and a single-use ignore file naming the
  seven findings; delete the file once 1.1.0 is the baseline. Constitution note for exceptions (plan,
  Complexity Tracking). Alternatives (major bump to 2.0.0; no new codes) were offered and declined.

## R8 — Pinned model identifiers and defaults
- **Finding**: LiteLLM's model map has exact entries for Anthropic `claude-haiku-5-5`, `claude-sonnet-5-5`,
  `claude-opus-5-5`, and dated OpenAI entries `gpt-5-nano-2025-08-07`, `gpt-5-mini-2025-08-07`,
  `gpt-5-2025-08-07`, each with input and output limits. No `gpt-5.x` entries exist yet.
- **Decision**: the example config (not the default) maps small = haiku then gpt-5-nano, medium = sonnet
  then gpt-5-mini, large = opus then gpt-5, alternating providers so fallback crosses providers.
  The loader rejects ids ending in `latest`, ids not present in the library's model map (unless a
  `max_input_tokens` override is given, as the stub needs), duplicates inside a tier, and empty tiers.
- **Alternatives**: floating aliases (forbidden by the spec); hard-coding limits (stale quickly).

## R9 — Default configuration is stub-only
- **Decision**: with no `GATEWAY_CONFIG`, a built-in config maps all three tiers to `stub/default`. The stack
  needs no credentials and the chat route behaves like spec 001's placeholder (FR-020). A real setup copies
  `config/gateway.example.yaml`, edits it and sets the path. Keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`.
- **Rationale**: one-command start (principle VII) and zero cost for development and CI.

## R10 — The stub provider doubles as the fault-injection tool
- **Decision**: stub model ids select behavior: `stub/default`, `stub/slow`, `stub/empty`, `stub/blocked`,
  `stub/fail-temporary`, `stub/fail-rate-limited`, `stub/fail-timeout`, `stub/fail-auth`,
  `stub/fail-invalid`, `stub/fail-midstream`, `stub/stall`. A YAML tier such as
  `[stub/fail-temporary, stub/default]` demonstrates fallback end to end, offline.
- **Compatibility**: `stub/default` honors spec 001's `PLACEHOLDER_TOKEN_DELAY_MS` and the test hook
  `app.state.fail_after_events` (raising a plain `RuntimeError`, which the gateway maps to
  `internal_error`), so spec 001's tests keep passing unchanged (SC-009).

## R11 — Time limits
- **Decision**: first-output limit per attempt (15 s) via `asyncio.timeout` around the first read; an overall
  wait for the first piece (45 s) across all attempts, retries, backoff and fallbacks, which ends the request with
  `upstream_timeout` (504) and cancels the provider call; idle limit
  (20 s) via a timeout on each subsequent read; total limit (120 s) as a deadline over the whole completion
  including retries and backoff. LiteLLM's own `timeout` is set to the smaller of first-output and the
  remaining total.
- **Rationale**: all four exist in the spec (FR-014; the overall wait bounds the worst case, which would otherwise be
  models × attempts × 15 s plus backoff); asyncio timeouts are deterministic in tests.

## R12 — Cancellation
- **Decision**: the provider stream is consumed inside `contextlib.aclosing`; cancelling the consumer (client
  disconnect, total limit) closes the upstream stream, which closes the HTTP connection. A test asserts the
  stub observes the close within 1 s (SC-005). A live check confirms the same with LiteLLM.

## R13 — Generation settings and unsupported parameters
- **Decision**: per tier, `max_output_tokens` and `temperature` each have a default and a ceiling. A caller may
  lower a value; asking for more than the ceiling raises a programming error. At startup the loader asks
  LiteLLM which parameters each configured model supports and drops unsupported ones (for example a model
  that accepts no temperature) explicitly, logging the model and parameter once, never silently.
- **Verified offline (T033-T035)**: LiteLLM's own parameter mapping raises `UnsupportedParamsError` for any
  temperature other than 1 on `gpt-5-nano-2025-08-07`, `gpt-5-2025-08-07` and `claude-haiku-5-5`, although
  `get_supported_openai_params` lists `temperature` as supported. So "is the parameter listed" is the wrong
  check; the adapter asks the library whether the model accepts a probe value (`default_params_check`),
  caches the answer per model, omits the parameter explicitly and logs `gateway_params_dropped` at startup.
- **Risk to verify with a live check**: reasoning-style models can spend the output budget on hidden
  reasoning and return little or no text with finish reason `length`. Defaults are therefore generous
  (small 2048, medium 4096, large 8192; ceilings 4096, 8192, 16384). Revisit after the live check.

## R14 — Input size check (FR-017)
- **Decision**: estimate tokens as `ceil(total_characters / 3)` (deliberately pessimistic for English),
  compare with the model's `max_input_tokens` (from LiteLLM's map or a config override), skip models that
  cannot take the conversation, and raise `input_too_large` before any provider call if none can.
- **Alternatives**: a real tokenizer per provider (heavy, provider-specific, still approximate for chat
  formatting).

## R15 — Cool-down
- **Decision**: in-memory, per process, keyed by model id: after 3 consecutive counted failures the model is
  skipped for 30 s; the first request after expiry is a trial, and a success clears the counter. With all
  models of a tier cooling down, the gateway still tries the one whose cool-down ends soonest instead of
  failing instantly.
- **Rationale**: matches FR-013 (amended in analysis to allow this one exception) without shared state (single instance for now, a deferred plan item from the
  clarification).

## R16 — Logging
- **Decision**: one `completion_finished` entry per completion (tier, serving model, attempts, fallback used,
  time to first output, total time, finish reason, token counts) and one `completion_attempt_failed` per
  failed attempt (model, category), through the existing structlog setup so request, tenant and user ids are
  attached. Message and answer text are never passed to the logger; a test scans all log output for sentinel
  strings (SC-007).

## R17 — Dependency weight and typing
- **Decision**: pin `litellm==1.106.2`; configure mypy `ignore_missing_imports` for it only if it ships no
  usable types; Pyright stays at basic. The Docker image grows; acceptable for the study project and recorded
  in Complexity Tracking.
