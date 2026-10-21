# Implementation Plan: LLM Gateway

**Branch**: `002-llm-gateway` | **Date**: 2026-10-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-llm-gateway/spec.md`

## Summary

Add a gateway package that every later capability calls to get model output. A caller asks for a **tier**
(small, medium, large) and receives the service's existing event stream, or a collected full answer through
a helper built on that same stream. Tiers map to ordered lists of pinned models from Anthropic and OpenAI
(plus a built-in stub), defined in a YAML file; provider credentials come from the environment. The
gateway owns retries with backoff, in-tier fallback, a per-model failure cool-down, three time limits,
cancellation, per-tier generation ceilings and a content-free log summary. The chat route is rewired to
the gateway, waits for the first output so a total failure is a proper HTTP error, and the contract moves to
1.1.0 with four new error codes. LiteLLM performs the provider calls only; the retry, fallback and cool-down
logic is our own so the spec's exact rules are testable offline against the stub. Decisions are in
[research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (unchanged from spec 001)

**Primary Dependencies**: adds `litellm==1.106.2` (resolved 2026-10-21; large dependency tree, see
Complexity Tracking). Existing: FastAPI 0.156.8, Pydantic 2.14.1, sse-starlette 3.5.0, structlog 26.1.0,
pyyaml 6.0.3.

**Storage**: none. The gateway keeps only an in-memory, per-process failure cool-down table (FR-021).

**Testing**: pytest as in spec 001. All gateway tests run against the stub provider and fake LiteLLM
streams; real-provider checks live in a separate `live` marker, skipped unless explicitly selected and
credentials are present.

**Target Platform**: Linux container (unchanged)

**Project Type**: web-service (single project)

**Performance Goals**: gateway adds at most 50 ms at p95 to time to first output versus iterating the stub
directly, at 20 concurrent requests (SC-006); the spec 001 first-event limit (500 ms) still holds with the
stub.

**Constraints**: defaults, all configurable in the YAML file: first output 15 s per attempt, overall wait
for the first output 45 s across all attempts, idle 20 s between pieces, total 120 s per completion; 2 attempts per model (one retry) with exponential backoff
(0.25 s base, 2 s cap, full jitter); cool-down after 3 consecutive failures for 30 s; generation settings
per tier (see data-model.md). No prompt or answer text in logs.

**Scale/Scope**: one process, study-scale traffic; 3 tiers, 2 real providers plus the stub; 4 new error
codes; 1 new internal module tree (about 10 files).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan satisfies it |
|---|---|---|
| I. Contract-first boundary | Pass, with a recorded exception | Proposed contract 1.1.0 is in `contracts/v1.1/` before any code and was checked with `oasdiff`. Adding error codes is flagged breaking by the gate (strict enum), so this plan uses a one-time, reviewed exception chosen by the owner (it needs the constitution amendment of task T004 first): error codes become an extensible enum and the gate gets an exact ignore list. See Complexity Tracking |
| II. Eval-gated changes | Deferred (owner: spec 004) | The gateway introduces model tiers, but no eval set exists until spec 004 (phase-in rule). From spec 004 on, any change to which models serve a tier must pass the regression eval. Recorded in the roadmap |
| III. Test-first | Pass | Tasks put failing tests (stub-based unit, integration and contract tests) before each module |
| IV. Defense in depth | Pass | A provider safety block is never retried and never falls back to another model (so fallback cannot be used to route around a filter) and surfaces as `done` with `blocked`. No tools in this spec |
| V. Tenant isolation | Pass | The gateway keeps no per-tenant state and stores no messages or answers; the only shared state is per-model failure tracking, which holds no tenant data. An isolation test runs two tenants concurrently through the gateway |
| VI. Cost and observability by default | Deferred (owner: spec 003) | Persistent per-request records and traces belong to spec 003. This spec adds the content-free structured log summary (tier, model, attempts, fallback, timings, finish reason, tokens) as the input spec 003 will persist |
| VII. Reproducibility and simplicity | Pass | `litellm` pinned; model identifiers pinned (the loader rejects `latest` aliases and models unknown to the library's model map); stub-only default needs no credentials, so `docker compose up` still works with one command |
| Workflow gates | Pass | CI runs unchanged jobs; the streaming load test is re-run (the SSE path changes) including a fallback scenario using stub models |

**Post-design re-check (after Phase 1)**: unchanged. Phase 1 added no service or storage; the one new
runtime dependency (`litellm`) is mandated by roadmap C-03.

## Project Structure

### Documentation (this feature)

```text
specs/002-llm-gateway/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── README.md                           # how and when the proposed contract is applied
│   ├── oasdiff-ignore-1.0-to-1.1.txt       # the exact, one-time gate exception
│   └── v1.1/
│       ├── openapi.yaml                    # proposed contract 1.1.0
│       └── events.schema.json              # proposed event schema (nullable token counts)
├── checklists/requirements.md
└── tasks.md                                # created later by /speckit-tasks
```

### Source Code (repository root)

```text
config/
└── gateway.example.yaml          # real Anthropic + OpenAI tiers, documented defaults
src/ai_services/
├── config.py                     # + gateway_config path, provider API keys (secret)
├── gateway/
│   ├── __init__.py               # Gateway facade: open(), stream(), complete()
│   ├── config.py                 # GatewayConfig models + YAML loader + startup validation
│   ├── types.py                  # CompletionRequest, GenerationSettings, Completion, outcome
│   ├── errors.py                 # ProviderError(category), GatewayError -> ServiceError mapping
│   ├── orchestrator.py           # attempts, retries/backoff, fallback, deadlines, cancellation
│   ├── cooldown.py               # per-model consecutive-failure tracking
│   ├── limits.py                 # input size estimate, generation ceilings
│   ├── logging.py                # content-free completion summary
│   └── providers/
│       ├── base.py               # Provider protocol, ProviderChunk
│       ├── litellm_provider.py   # LiteLLM streaming call + exception/finish-reason mapping
│       └── stub.py               # deterministic stub with scripted faults
├── api/v1/chat.py                # rewired to the gateway; waits for first output
├── errors.py                     # + upstream_unavailable/_timeout/_error, input_too_large
├── events.py                     # usage token counts become nullable
├── schemas.py                    # (unchanged request model)
└── placeholder.py                # removed; its text moves into the stub provider
contracts/v1/                     # replaced by contracts/v1.1 content at implementation time
scripts/contract-diff.sh          # + optional --err-ignore file support
tests/
├── unit/gateway/                 # config, limits, cooldown, errors mapping, stub, orchestrator
├── integration/                  # chat via gateway, fallback, timeouts, cancellation, isolation, logs
├── contract/                     # updated for 1.1.0
└── live/                         # opt-in real-provider checks (marker `live`)
```

**Structure Decision**: a `gateway/` subpackage beside the foundation modules. The chat route depends only on
the facade, so specs 003 to 008 call the same facade. LiteLLM is imported in exactly one file, which keeps
the rest of the code and the tests provider-agnostic.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| One-time exception to "breaking changes MUST bump MAJOR" (principle I): contract 1.1.0 adds error codes, which the gate flags as breaking because 1.0.0 declared a strict enum | The new failure modes need stable, machine-readable codes. The owner chose a documented exception because contract 1.0.0 has no deployed consumer yet. Mitigation: error codes become an extensible enum from 1.1.0 on, so later additions pass the gate; the ignore list names exactly the seven flagged changes and expires once 1.1.0 is the baseline | A new major version (`/v2`) would double the API surface for a contract nobody uses; reusing `internal_error` would make the code field meaningless |
| Large dependency (`litellm` pulls about 58 packages) | Roadmap constraint C-03 chose it to hide provider differences | Calling each provider SDK directly would remove the dependency but reimplement exception mapping, streaming normalisation and model metadata that the library already maintains |
| Own retry, fallback and cool-down logic on top of LiteLLM instead of its Router | The spec's rules (tier-only fallback, no fallback after first output, no fallback on safety blocks, cool-down semantics, offline testing with the stub) are easiest to guarantee and test in code we own | LiteLLM's Router offers fallbacks and cool-downs, but matching these exact rules would mean working around it, and the stub could not drive it. Its mid-stream behavior was not evaluated in depth |
| Constitution amendment (prerequisite, task T004, committed before the contract change): exceptions to a MUST need a written reason, an owner decision and an expiry | Makes the exception above legitimate instead of silent | Leaving the exception undocumented would make the gate meaningless |
