# Quickstart: Service Foundation

Validation guide for spec 001. It describes what to run and what to expect once the feature is implemented. For
field-level detail see [data-model.md](data-model.md) and [contracts/v1/](../../contracts/v1/).

## Prerequisites
- Docker with Compose, `uv`, and `curl`.
- A clean checkout.

## 1. Configure
```bash
cp .env.example .env
# set SERVICE_TOKENS to one or two random strings of at least 32 characters
```
Expected: starting without `SERVICE_TOKENS` fails fast with a message naming the missing variable.

## 2. Start the whole stack with one command (US3)
```bash
docker compose up --wait
```
Expected: service, Postgres, Redis Stack and Qdrant report healthy within 3 minutes (SC-002).

## 3. Health checks (US3)
```bash
curl -s localhost:8080/v1/health/live
curl -s localhost:8080/v1/health/ready
curl -s -H "Authorization: Bearer $TOKEN" localhost:8080/v1/health/ready
```
Expected: liveness `{"status":"ok"}`. Readiness without the token returns only `{"status":"ready"}`; with the
token it adds each dependency as `up`. Stop one dependency (`docker compose stop qdrant`): readiness returns 503
`not_ready` (dependency named only with the token) while liveness stays `ok`; starting it again recovers
readiness without restarting the service.

## 4. Authenticated streaming call (US1)
```bash
curl -N -i localhost:8080/v1/chat/stream \
  -H "Authorization: Bearer $TOKEN" -H "X-Tenant-Id: acme" -H "X-User-Id: u-1" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```
Expected: `200`, `X-Request-Id` and `X-Contract-Version` headers, `token` events with ids 0, 1, 2…, then `usage`,
then exactly one `done` as the last event. The first event arrives in under 500 ms (SC-006).

## 5. Rejections (US1)
| Try | Expect |
|---|---|
| no or wrong token | 401 `unauthorized`, no stream |
| valid token, no `X-Tenant-Id` | 400 `invalid_identity`, `details.field` = `X-Tenant-Id` |
| body over 256 KiB | 413 `payload_too_large` |
| 101 messages | 422 `history_too_long` |
| last message role `assistant` | 422 `validation_error` |

Every error body carries `request_id`, matching the `X-Request-Id` header.

## 6. Contract (US2)
```bash
uv run pytest tests/contract
```
Expected: all routes and event types conform; the drift test passes. Changing a response field without editing
`contracts/v1/` makes it fail. In CI, `oasdiff breaking` fails a breaking change that lacks a new major version.

## 7. Diagnose a request (US5)
```bash
docker compose logs service | grep <request-id-from-step-4>
```
Expected: JSON log lines for that request, each with `tenant_id` and `user_id`, and no token value anywhere.

## 8. Rotation (FR-018)
Add a second token to `SERVICE_TOKENS`, restart the service, call with each token (both succeed), remove the
old token, restart, and confirm the old token now returns 401.

## 9. Load test
```bash
uv run python scripts/load-test.py --streams 20
```
Expected: all 20 concurrent streams end in exactly one `done`, and the 95th-percentile time to first event is under 500 ms.

## 10. Automated checks (US4)
```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run pytest tests/unit tests/contract tests/integration
scripts/smoke.sh
```
Expected: all pass locally and in the GitHub Actions workflow. A deliberately failing test blocks the pipeline.

## Verified on

- **2026-10-21, local Docker Compose v5.6.0 (T045):**
  - `docker compose up --wait` brought service, Postgres, Redis Stack and Qdrant to healthy in about 20 s (SC-002 target: 3 minutes).
  - Steps 3 and 4: liveness, anonymous and credentialed readiness, a streamed answer (`token` events, `usage`, `done`) and a 401 all behaved as described.
  - `docker compose stop qdrant` made readiness return 503 `not_ready` (qdrant `down` with the token) while liveness stayed `ok`; `docker compose start qdrant` restored 200 without restarting the service.
  - SIGTERM with a stream in flight: the stream completed with `done`, the container exited 0, and new connections were refused during the drain (real Uvicorn graceful shutdown, not the in-process flag).
- **2026-10-21, rebuilt image (T053, T058):**
  - Step 5 rejections returned `unauthorized` 401, `invalid_identity` 400 (`details.field` = `X-Tenant-Id`), `payload_too_large` 413, `history_too_long` 422 and `validation_error` 422, each with a `request_id`.
  - Step 7: the logs for one streamed request had `request_id`, `tenant_id` and `user_id` on every line (started, completed, `request_finished` with method, path, status and duration), and the service token appeared in none of them.
  - Step 8 rotation: with two tokens both returned 200; after removing the old one it returned 401 and the new one 200.
  - Step 9 load test (T058): 20 concurrent streams, p95 time to first event 27 ms; 100 concurrent streams, p95 137 ms (limit 500 ms). All streams ended in exactly one `done`.
  - `scripts/smoke.sh` passes against the rebuilt stack.
