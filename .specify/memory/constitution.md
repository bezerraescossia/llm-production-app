<!--
Sync Impact Report
Version change: 1.2.0 → 1.3.0
Modified principles: none
Added sections: Exceptions rule (under Governance)
Removed sections: none
Invalidates: nothing. Gives a legitimate path for the one exception already decided for spec 002:
  contract 1.1.0 adds error codes that the automated breaking-change check flags. Without this rule
  that exception would be a silent violation of principle I.
Follow-up TODOs: none

Previous (1.2.0): phase-in rule for capability-dependent gates
Previous (1.1.0): tool rule widened to read-only, allow-listed (principle IV)
Previous (1.0.0): initial ratification of Core Principles I–VII, Technology Constraints,
  Development Workflow & Quality Gates, Governance
-->
# AI-Services Constitution

## Core Principles

### I. Contract-First Service Boundary
This service is a separately deployable HTTP service consumed by an API gateway. Its HTTP and SSE
contract (routes, request and response schemas, SSE event types: `token`, `tool_call`,
`tool_result`, `citation`, `usage`, `done`, `error`) MUST be defined in a versioned schema before
implementation. A cache hit MUST emit the same event schema as a live LLM response. Breaking
changes MUST bump the contract's MAJOR version and keep the previous version served until the
gateway migrates.
**Gate:** every endpoint has a contract test against the published schema; plan and implement
fail if a schema change lacks a version bump.

### II. Eval-Gated Changes (NON-NEGOTIABLE)
Any change to prompts, model tiers, router rules or classifier, cache similarity thresholds,
chunking or retrieval, or guardrail rules MUST pass the regression eval set. Thresholds for
answer quality, routing accuracy, retrieval recall, cache false-hit rate and guardrail catch rate
MUST be defined in the spec that introduces the capability, never guessed.
**Gate:** CI runs the eval suite and blocks merge below threshold.

### III. Test-First
Failing tests derived from a spec's acceptance criteria MUST exist before the implementation they
cover. LLM calls in unit tests MUST be stubbed; live-provider tests are limited to a separate,
explicitly invoked suite.
**Gate:** implement refuses to start a component whose acceptance criteria have no failing tests.

### IV. Defense in Depth for Safety
Input guardrails MUST run and be able to block before any LLM call. Output MUST be scanned in
chunks while streaming, and a violation MUST cut the stream and emit a replacement message plus
an `error` or `done` event with the verdict. Tools run inside this service, and the client never
executes them. In v1, every tool MUST be read-only with no side effects, registered in an
allow-list, and declare its schema, timeout and the external hosts it may call; calls to any
other host MUST be refused. Tool output is untrusted and MUST pass through guardrails before it
re-enters the LLM context. Per-request tool call limits apply. A tool that changes state or
touches a business system requires a new spec and an ADR.
**Gate:** injection, PII and unsafe-output and untrusted-tool-output fixtures are part of the eval suite and MUST be
blocked or cut.

### V. Tenant Isolation
Every request carries a service token plus `X-User-Id` and `X-Tenant-Id`. Cache entries,
knowledge-base queries, cost records and logs MUST be scoped by tenant. Semantic cache keys MUST
include tenant, KB version and prompt/model version. A cross-tenant cache or KB hit is a
release-blocking defect.
**Gate:** an isolation test with two tenants and identical queries MUST show zero cross-tenant
hits.

### VI. Cost and Observability by Default
Every request MUST write one Postgres record with tokens, cost, latency, route, model tier,
cache outcome and guardrail verdicts, and MUST emit OpenTelemetry traces covering each pipeline
stage. Secrets and raw PII MUST NOT appear in logs, traces or records.
**Gate:** an integration test asserts the record and trace exist for hit, miss, blocked and
error paths.

### VII. Reproducibility and Simplicity
Dependencies and model IDs MUST be pinned. The full stack MUST start with one command
(`docker compose up`). Complexity beyond the current spec MUST be justified in the plan
(YAGNI).
**Gate:** CI builds from a clean checkout and runs the Compose smoke test.

## Technology Constraints

- Language and framework: Python with async FastAPI.
- LLM access: LiteLLM, multi-provider, with small, medium and large tiers and a fallback chain.
- Semantic cache: Redis Stack (exact-match layer plus vector layer).
- Knowledge base: Qdrant, populated by an offline ingestion CLI or worker in this repo.
- Records and evals: Postgres. Traces: OpenTelemetry with Jaeger or Grafana locally.
- Deployment: Docker Compose and GitHub Actions. Kubernetes is out of scope until a later
  amendment.
- Deviating from this list requires an ADR and a constitution amendment.

## Development Workflow & Quality Gates

- Work follows the Spec Kit flow: specify, plan, tasks, implement, one component at a time.
- Each plan MUST include a Constitution Check against principles I–VII.
- CI MUST run lint, type checks, unit and contract tests, the regression eval, and the
  Compose smoke test. A streaming load test MUST run before a component touching the SSE path
  is marked done.
- Prompts and eval datasets are versioned in the repo and reviewed like code.
- **Phase-in rule:** a gate that depends on a capability that does not exist yet (for example the
  per-request record fields of principle VI, or evaluable model behavior for the regression eval)
  takes effect in the spec that introduces that capability. The roadmap MUST name the owning spec
  for each deferred gate, and a plan MUST mark the principle `Deferred (owner: spec NNN)` rather
  than `Pass`. A deferred gate MUST NOT be deferred past its owning spec. The streaming load test
  is not deferrable: it applies to any spec that builds or changes the SSE path.

## Governance

This constitution supersedes other practices. Amendments require a written rationale, a version
bump, and a note of which specs or plans they invalidate. Versioning: MAJOR for removed or
redefined principles, MINOR for added principles or materially expanded guidance, PATCH for
clarifications. Compliance is checked in every plan (Constitution Check) and again before a
component is marked implemented; unjustified violations block merge.

**Exceptions.** A single, bounded exception to a MUST is allowed only when all of the following are
written down before the exceptional change is applied: the reason, the owner's explicit decision, the
exact scope (which check or rule, which change), and an expiry condition after which the exception
is removed. The exception is recorded in the plan's Complexity Tracking and in the artifact that
implements it. An exception never widens: a different violation needs its own record. Example: the
contract 1.1.0 error-code exception of spec 002 (reason: new failure codes; decision: owner, during
planning; scope: seven named findings of the breaking-change check; expiry: delete
`contracts/oasdiff-ignore.txt` once 1.1.0 is the baseline on the default branch).

**Version**: 1.3.0 | **Ratified**: 2026-10-21 | **Last Amended**: 2026-10-21
