# AI-Services

The AI-services layer of an LLM production app (a docs Q&A assistant). A client and an API gateway live
elsewhere; the gateway calls this service over HTTP and receives answers as server-sent events (SSE).
It is built for study, to production-grade standards, one spec at a time.

- Governance: [constitution](.specify/memory/constitution.md) and [roadmap](.specify/memory/roadmap.md)
- Current spec: [001 Service Foundation](specs/001-service-foundation/spec.md). The chat route returns a
  deterministic placeholder answer; models, RAG, cache, guardrails and tools arrive in later specs.

## Run it

```bash
cp .env.example .env        # set SERVICE_TOKENS to 1-2 random strings of at least 32 characters
docker compose up --wait    # service + Postgres + Redis Stack + Qdrant
SERVICE_TOKEN=<one of your tokens> scripts/smoke.sh
```

A streaming call:

```bash
curl -N localhost:8080/v1/chat/stream \
  -H "Authorization: Bearer $SERVICE_TOKEN" -H "X-Tenant-Id: acme" -H "X-User-Id: u-1" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

Full validation steps are in the [quickstart](specs/001-service-foundation/quickstart.md).

## Models and the LLM gateway

Every completion goes through the gateway: callers ask for a **tier** (`small`, `medium`, `large`) and
never for a specific model. Which exact models serve each tier, in fallback order, is configuration.

- **Default:** with nothing configured every tier is served by a built-in stub, so the stack runs with no
  credentials and no cost.
- **Real models:** copy `config/gateway.example.yaml` to `config/gateway.local.yaml`, edit it, then set
  `GATEWAY_CONFIG=config/gateway.local.yaml`, `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` in `.env`.
  Model ids must be exact (no `latest` aliases); an invalid file stops startup with a message naming the entry.
- **Fallback demo, offline:** `GATEWAY_CONFIG=config/gateway.fallback-demo.yaml docker compose up --build --wait`
  makes every request fail over from a failing stub model to a healthy one; watch it with
  `docker compose logs service | grep completion_`.
- **Failure behavior:** retries, then fallback within the tier only; a failure before any output is an HTTP error
  (503, 504, 502, 422), after output an `error` event; limits on waiting and total time; no prompt or answer
  text in logs. Details in [specs/002-llm-gateway](specs/002-llm-gateway/spec.md).
- **Real-provider checks** cost a little and are opt-in: `uv run pytest -m live tests/live`.

## Contract and versioning

The HTTP and SSE contract is in [`contracts/v1/`](contracts/v1/) (`openapi.yaml`, `events.schema.json`).
The major version is in every route path (`/v1/...`). A breaking change needs a new major version
(`contracts/v2/`) while the previous one keeps being served. `scripts/contract-diff.sh` enforces this in CI.

## Run the checks locally

```bash
uv sync --frozen
uv run ruff check . && uv run ruff format --check .      # lint (CI job: lint)
uv run mypy --strict src && uv run pyright                # types, mypy + Pyright/Pylance (CI job: types)
uv run pytest tests/unit tests/contract tests/integration # tests (CI job: tests)
scripts/contract-diff.sh origin/main                     # breaking-change gate (CI job: contract-breaking)
docker compose up --wait && SERVICE_TOKEN=... scripts/smoke.sh   # smoke (CI job: smoke)
SERVICE_TOKEN=... uv run python scripts/load-test.py --streams 20  # streaming load test
```

## Required status checks

Branch protection is a repository setting, not code. After pushing this repository to GitHub, mark all five
jobs of `.github/workflows/ci.yml` as **required status checks** on the default branch so a failing check
blocks the merge: `lint`, `types`, `tests`, `contract-breaking`, `smoke`.

## Layout

```text
src/ai_services/   service code (api/v1 routes, auth, middleware, events, readiness, config, logging)
contracts/v1/      the published contract
tests/             unit, contract, integration
scripts/           smoke.sh, contract-diff.sh, load-test.py
specs/             Spec Kit specs, plans and tasks
```
