<!--
SYNC IMPACT REPORT
==================
Version change: 1.3.1 → 1.3.2
Bump rationale: PATCH — status transition and clarifying notes only, from the spec 001 debrief
  (specs/001-service-foundation/roadmap-reviews/debrief-20261021-103530.md, findings F2 and F3)

Changes this revision:
  - Spec 001: in-progress → implemented (verified is withheld until the CI gate is proven, task T049)
  - C-11 annotated: the CI eval gate starts in spec 004; the streaming load test was delivered in 001
  - Spec 001 Notes: final error codes, MAX_MESSAGES cap, health route paths, request summary log

Specs affected: 001
Open questions added/resolved: none
Not applied: debrief F4 (readiness probes dependencies 001 does not use) is a spec assumption to
  decide, not a roadmap change; F1 needs the repository on GitHub.

Previous (1.3.1): spec 001 in-progress; (1.3.0): scope of 003/004 extended with gates deferred from 001;
  (1.2.0): rate-limit contract; (1.1.0): tools widened; (1.0.0): initial creation
-->

# AI-Services — Spec Roadmap

Living, non-binding map of the specs planned for AI-Services. It is **not a
commitment to order or scope** — it captures the spec-specific discussion,
decisions, technology choices, outcomes, and constraints surfaced during the
constitution and grilling phases so they are not lost before the spec that needs
them is written. Specs are scoped and clarified when they are actually started.
Foundations: the project [constitution](constitution.md).

Status legend (lifecycle): **undecided** · **needs-info** · **planned** ·
**specced** · **in-progress** · **implemented** · **verified** · **deferred** ·
**abandoned**.

---

## Vision & End States

- A separately deployable AI-services layer (FastAPI + SSE) that an API gateway and client call.
- A Docs Q&A assistant with RAG, citations and streamed answers.
- Production capabilities in place: guardrails, prompt router, semantic cache, cost and eval
  logging, read-only tools.
- Reproducible: `docker compose up` brings the stack up, and CI gates on a regression eval.

## Constraints & Decisions

- **C-01 — Separate HTTP service:** consumed by the gateway over HTTP/SSE with a versioned
  contract. Keeps AI concerns independently deployable and scalable.
- **C-02 — Python + async FastAPI:** best ecosystem for RAG, evals and guardrails; native SSE.
- **C-03 — LiteLLM multi-provider gateway:** small/medium/large tiers with a fallback chain.
- **C-04 — Redis Stack cache:** exact-match layer plus semantic vector layer.
- **C-05 — Qdrant knowledge base:** populated by an offline ingestion CLI/worker in this repo;
  the gateway may trigger re-index through an admin endpoint.
- **C-06 — Rules-then-classifier router:** cheap rules first, small-LLM classifier for ambiguous
  cases; accuracy measured on the eval set.
- **C-07 — Safety pipeline:** input guardrails block before any LLM call; output is checked in
  chunks while streaming, and a violation cuts the stream.
- **C-08 — Postgres records + OpenTelemetry traces:** one record per request (tokens, cost,
  latency, route, cache outcome, guard verdicts).
- **C-09 — Tools executed in this service:** ~~read-only and docs-scoped in v1~~ (superseded in
  1.1.0). Now: read-only, no side effects, allow-listed, each with a declared schema, timeout and
  permitted external hosts; tool output is untrusted and guardrailed. The client never executes
  tools. This goes against the "gateway executes" recommendation from the grilling and blurs the
  service boundary. State-changing or business-system tools need an ADR.
- **C-10 — Service token + `X-User-Id` / `X-Tenant-Id` headers:** cache, KB, cost and logs scoped
  per tenant.
- **C-11 — Docker Compose + GitHub Actions:** CI runs a regression eval gate; a streaming load
  test covers the SSE path. Kubernetes is out of scope for now.
  _Annotation (1.3.2): the CI eval gate starts in spec 004, the first spec with evaluable behavior
  (constitution 1.2.0 phase-in rule). The streaming load test was delivered in spec 001._

## Planned Specs

### 001 — Foundation  [status: implemented]

- **Description:** FastAPI skeleton with config, auth headers, health, error model and SSE
  event schema, plus the Compose stack and CI.
- **Outcome:** a gateway can call a versioned, authenticated streaming endpoint and the stack
  starts with one command.
- **Scope (in):** service skeleton, rate-limit contract reservation (`rate_limited` error, retry hint), repo-root `contracts/v1/`, SSE load test,
  tenant/user header handling, error model, SSE events
  (`token`, `tool_call`, `tool_result`, `citation`, `usage`, `done`, `error`), Compose services,
  CI, contract tests.
- **Scope (out):** any LLM call, caching, RAG, guardrails, rate-limit enforcement.
- **Depends on:** none
- **Governed by:** C-01, C-02, C-10, C-11
- **Spec dir:** specs/001-service-foundation/
- **Notes:** the contract here fixes the SSE schema that every later spec emits. Build-time decisions
  later specs inherit: the error model also has `not_found` (404) and `method_not_allowed` (405);
  `MAX_MESSAGES` can only be lowered from the contract cap of 100; health routes are
  `/v1/health/live` and `/v1/health/ready`; every request logs one `request_finished` line (method,
  path, status, duration). Not yet `verified`: the CI gate has never run on GitHub (task T049).

### 002 — LLM gateway  [status: planned]

- **Description:** LiteLLM wrapper with model tiers, timeouts, retries, fallback and streaming
  normalisation.
- **Outcome:** any component can request a completion by tier and receive a uniform stream.
- **Scope (in):** tier config, pinned model IDs, retries and fallback, stream normalisation,
  stubbed provider for tests.
- **Scope (out):** routing decisions (spec 006), cost recording (spec 003).
- **Depends on:** 001
- **Governed by:** C-03

### 003 — Cost tracker + eval logger  [status: planned]

- **Description:** Postgres schema and writers for per-request records, plus OTel spans.
- **Outcome:** every request path (hit, miss, blocked, error) leaves a record and a trace.
- **Scope (in):** schema and migrations, token and cost computation, OTel instrumentation,
  PII-safe logging, and the constitution principle VI gate deferred from spec 001 (an integration test
  asserts the record and trace exist for hit, miss, blocked and error paths).
- **Scope (out):** dashboards (spec 009).
- **Depends on:** 001, 002
- **Governed by:** C-08

### 004 — Knowledge base + RAG  [status: planned]

- **Description:** ingestion CLI, chunking, embeddings, Qdrant retrieval and citations.
- **Outcome:** a question returns a grounded streamed answer with citations from the tenant's KB.
- **Scope (in):** ingestion, chunking, embedding, tenant-scoped retrieval, citation events,
  retrieval eval set, admin re-index endpoint, and the first CI regression eval job (constitution II,
  deferred from spec 001 because no evaluable behavior exists before this spec).
- **Scope (out):** upload API with async jobs.
- **Depends on:** 001, 002
- **Governed by:** C-05
- **Notes:** needs a corpus and an embedding model (Q1, Q2).

### 005 — Guardrails  [status: planned]

- **Description:** input checks (injection, PII, off-topic, length) and chunked output checks.
- **Outcome:** unsafe input is blocked before any LLM call and unsafe output cuts the stream.
- **Scope (in):** input pipeline, streaming output scanner, replacement message, eval fixtures.
- **Scope (out):** human review workflow.
- **Depends on:** 001, 002
- **Governed by:** C-07
- **Notes:** implementation choice and chunk window are open (Q3, Q4).

### 006 — Prompt router  [status: planned]

- **Description:** rules plus small-LLM classifier choosing the model tier.
- **Outcome:** simple queries go to the small tier with measured routing accuracy and lower cost.
- **Scope (in):** rules, classifier, route logging, routing eval.
- **Scope (out):** learned or trained routers.
- **Depends on:** 002, 003
- **Governed by:** C-06

### 007 — Semantic cache  [status: planned]

- **Description:** Redis exact and semantic cache layers with hit replay over SSE.
- **Outcome:** repeated or similar questions are served from cache at zero LLM cost, with no
  cross-tenant hits.
- **Scope (in):** exact and semantic layers, tenant/KB-version/prompt-version keys, TTL,
  invalidation on re-index, SSE replay.
- **Scope (out):** cache warming.
- **Depends on:** 003, 004
- **Governed by:** C-04, C-10
- **Notes:** similarity threshold is set from eval results (Q5).

### 008 — Tools  [status: planned]

- **Description:** tool schemas, registry and execution loop, run inside this service.
- **Outcome:** the model can call allow-listed read-only tools (`search_docs`, `get_doc`) within
  per-request limits, and `get_weather` exists as the documented template for external tools.
- **Scope (in):** schemas, allow-list, host allow-list and timeouts per tool, execution loop, call
  limits, guardrail pass on tool output, optional `tool_call`/`tool_result` events.
- **Scope (out):** state-changing tools or business-system access (needs an ADR).
- **Depends on:** 002, 004, 005
- **Governed by:** C-09
- **Notes:** `tool_call`/`tool_result` events are informational so a UI can show progress. Whether
  `get_weather` ships enabled in v1 or only as an example is decided when 008 is specified.
  ~~Docs-scoped read-only tools only~~ (superseded in 1.1.0).

### 009 — Eval & ops hardening  [status: planned]

- **Description:** regression eval gate in CI, streaming load test, rate limits, dashboards.
- **Outcome:** CI blocks regressions and the stack's behaviour is observable under load.
- **Scope (in):** eval gate thresholds, load test, per-user rate limit enforcement (builds on the
  contract reserved in 001), Grafana dashboards.
- **Scope (out):** Kubernetes deployment.
- **Depends on:** 001–008
- **Governed by:** C-11

## Open Questions

- Q1 — Which document set is the KB corpus? Resolved when 004 is specified.
- Q2 — Which embedding model and provider? Resolved by a retrieval-quality comparison in 004.
- Q3 — Guardrails: own rules vs an existing library? Resolved when 005 is specified.
- Q4 — Output-guard chunk window size? Resolved by latency and catch-rate measurements in 005.
- Q5 — Cache similarity threshold? Resolved from false-hit rate on the eval set in 007.
- Q6 — What does a rate limit count (requests, tokens or cost) and at what scope (user, tenant or both)?
  Resolved when 009 is specified; cost-based limits need spec 003's records.

## Cross-Cutting Notes

- The SSE event schema from 001 is shared by cache replay (007), tools (008) and guardrails (005).
- `tool_call` and `tool_result` SSE events are informational; the tool loop runs server-side.
- Every spec that changes prompts, thresholds or retrieval must pass the eval gate
  (constitution principle II).

---

**Version**: 1.3.2 | **Ratified**: 2026-10-21 | **Last Amended**: 2026-10-21
