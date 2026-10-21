# Implementation Plan: Service Foundation

**Branch**: `001-service-foundation` | **Date**: 2026-10-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-service-foundation/spec.md`

## Summary

Stand up the AI-services skeleton that every later spec plugs into: an authenticated, tenant-aware, versioned
HTTP service whose chat route streams a deterministic placeholder answer as typed SSE events. The contract
(OpenAPI plus an SSE event schema) is written first and enforced by contract tests and a CI breaking-change
gate. Operability comes with it: structured logs keyed by request, tenant and user; liveness and readiness
checks; one-command Compose stack; GitHub Actions pipeline. No model, cache, RAG, guardrail or tool logic
exists yet. Technical approach and decisions are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (pinned in `.python-version`; 3.14 is installed locally but 3.12 has the widest wheel and library support)

**Primary Dependencies**: FastAPI 0.156.8, Uvicorn 0.54.0, Pydantic 2.14.1, pydantic-settings 2.16.1, sse-starlette 3.5.0, structlog 26.1.0 (all versions resolved on 2026-10-21 and locked with uv)

**Storage**: None used by this spec's logic (stateless, FR-019). Postgres, Redis Stack and Qdrant are started by Compose and probed by readiness only.

**Testing**: pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1 (ASGI transport), asgi-lifespan 2.1.0, jsonschema 4.26.0, openapi-spec-validator 0.9.0; lint and types with ruff 0.17.1 and mypy 2.4.0 (strict)

**Target Platform**: Linux container (Docker Compose locally and in CI)

**Project Type**: web-service (single project)

**Performance Goals**: first SSE event within 500 ms of acceptance for the placeholder answer (SC-006), where "normal load" is 20 concurrent streams (load test T058); stack healthy within 3 minutes of one command (SC-002)

**Constraints**: stateless per request; no secret in any log (SC-008); contract served under `/v1/`; defaults for request size (256 KiB), message count (100), shutdown grace (20 s), rotation tokens (up to 2) are configurable through the environment

**Scale/Scope**: study-scale traffic; one service process; 5 routes; 7 event types; ~12 error codes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan satisfies it |
|---|---|---|
| I. Contract-first boundary | Pass | `contracts/v1/` written before code; contract tests plus drift test; `oasdiff` breaking-change gate in CI; `/v1` path versioning |
| II. Eval-gated changes | Deferred (owner: spec 004) | No prompt, router, cache, retrieval or guardrail exists in 001, so nothing is evaluable. Spec 004 adds the first eval set and CI eval job (constitution 1.2.0 phase-in rule; roadmap 1.3.0) |
| III. Test-first | Pass | Tasks order tests before code per story; contract and unit tests derive from acceptance scenarios |
| IV. Defense in depth | N/A | No LLM call or tools yet. Request validation and size limits are the only guards here. Guardrails arrive in spec 005 |
| V. Tenant isolation | Pass | Tenant and user identity carried in a per-request context and logged; concurrent two-tenant isolation test |
| VI. Cost and observability by default | Deferred (owner: spec 003) | Record fields (tokens, cost, route, cache, guard verdicts) do not exist until specs 002–007. 001 delivers the prerequisites: request id, tenant and user context, structured logs, no secrets in logs. Spec 003 owns the record and trace gate (constitution 1.2.0 phase-in rule; roadmap 1.3.0) |
| Workflow gates (CI, load test) | Pass | CI jobs in R15; a streaming load test is built and run in this spec (task T058), as the constitution requires for any spec that builds the SSE path |
| VII. Reproducibility and simplicity | Pass | uv lockfile, pinned Python, one-command Compose, clean-checkout CI smoke test |

**Post-design re-check (after Phase 1)**: unchanged. Phase 1 added no new dependency or service beyond the
Compose components the constitution already names.

## Project Structure

### Documentation (this feature)

```text
specs/001-service-foundation/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and alternatives
├── data-model.md        # Phase 1: entities, validation, state
├── quickstart.md        # Phase 1: run and validate guide
├── contracts/
│   └── README.md        # Pointer: the contract lives at repo-root contracts/v1/
├── checklists/
│   └── requirements.md
└── tasks.md             # Created later by /speckit-tasks
```

### Source Code (repository root)

```text
contracts/v1/            # source of truth for the HTTP and SSE contract (read by the service and CI)
├── openapi.yaml         # routes, requests, responses, errors
└── events.schema.json   # SSE event payloads
pyproject.toml           # dependencies, ruff, mypy, pytest config
uv.lock
.python-version
Dockerfile
compose.yaml             # service + postgres + redis-stack + qdrant
.env.example
src/ai_services/
├── main.py              # app factory, lifespan, router mounting
├── config.py            # settings from environment, fail-fast
├── logging.py           # structlog setup, redaction, context binding
├── context.py           # RequestContext (request id, tenant, user) via contextvars
├── errors.py            # error codes, exception types, error handlers
├── auth.py              # service-token check, identity header validation
├── middleware.py        # request id, body size limit, shutdown gate
├── api/
│   └── v1/
│       ├── chat.py      # POST /v1/chat/stream
│       ├── health.py    # GET /v1/health/live, /v1/health/ready
│       └── contract.py  # GET /v1/contract
├── events.py            # typed SSE events and encoder
├── placeholder.py       # deterministic placeholder answer stream
├── readiness.py         # dependency registry and TCP checks
└── schemas.py           # request/response/error pydantic models
tests/
├── unit/
├── contract/            # conformance and drift tests against contracts/v1
└── integration/         # ASGI-level flows, isolation, shutdown, disconnect
scripts/
├── smoke.sh             # compose smoke test used locally and in CI
├── contract-diff.sh     # oasdiff breaking-change gate
└── load-test.py         # concurrent SSE streams, checks time to first event
README.md
.github/workflows/ci.yml
```

**Structure Decision**: a single Python project (`src/ai_services`) with the API layer in `api/v1/`, so a
future `v2` is a sibling package sharing core modules. Later specs add siblings (`gateway/`, `cache/`,
`guardrails/`, …) beside the foundation modules.

## Complexity Tracking

No principle is violated. The two deferred gates (II and VI) are governed by the phase-in rule in
constitution 1.2.0, each with a named owner spec on the roadmap. The rows below are other deliberate
complications.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Compose starts Qdrant and Redis Stack though 001 does not use them | FR-014 requires the whole declared stack from one command, and readiness needs real dependencies to prove User Story 3 scenarios 2 and 3 | Starting only Postgres would leave the later specs to rework Compose and the readiness wiring |
| Readiness probes dependencies this spec does not functionally use (Postgres, Redis, Qdrant), which stretches the spec Assumption that readiness reports only dependencies in use | Without a probed dependency the "dependency down" scenarios are untestable | An empty dependency list would pass the scenarios vacuously. The list is environment-configured so it can be reduced |
| GitHub Actions are referenced by major version tag (`actions/checkout@v4`, `astral-sh/setup-uv@v6`), not by commit SHA | The repository has not been created on GitHub yet, so the SHAs could not be looked up and verified | Pinning to an unverified SHA would be a guess. Pin them to SHAs (constitution VII) once the repository exists |
