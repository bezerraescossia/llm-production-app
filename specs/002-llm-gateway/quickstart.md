# Quickstart: LLM Gateway

Validation guide for spec 002 after implementation. Field detail: [data-model.md](data-model.md). Contract:
[contracts/](contracts/README.md). Prerequisites are those of spec 001's quickstart.

## 1. Default: stub only, no credentials (US1)
```bash
docker compose up --build --wait
SERVICE_TOKEN=<token from .env> scripts/smoke.sh
```
Expected: unchanged behavior from spec 001: a streamed deterministic answer ending in one `done`. The chat
route now goes through the gateway at the default tier (`medium`, served by `stub/default`).

## 2. Fallback you can watch, offline (US3)
Create `config/gateway.local.yaml` with a small tier of `[stub/fail-temporary, stub/default]`, set
`GATEWAY_CONFIG=config/gateway.local.yaml` and `LOG_LEVEL=INFO`, restart, and call the chat route.
Expected: a normal answer. The logs for that request id show two failed attempts on `stub/fail-temporary`
(category `temporary`), then success on `stub/default` with `fallback_used=true`, and contain no message text.

## 3. Every model fails (US3)
Set a tier to `[stub/fail-temporary, stub/fail-rate-limited]` and call it.
Expected: HTTP 503 `upstream_unavailable` in the standard error shape with `Retry-After`, no stream opened,
within the total time limit. `[stub/fail-timeout]` gives 504 `upstream_timeout`; `[stub/fail-auth]` gives
502 `upstream_error`.

## 4. Failure after output has started (US3)
Use `[stub/fail-midstream]`.
Expected: 200 with some `token` events, then one `error` event, and no fallback to the next model.

## 5. Safety block (US1, US3)
Use `[stub/blocked, stub/default]`.
Expected: `usage`, then `done` with `finish_reason` `blocked`; the second model is not tried.

## 6. Time limits and disconnect (US4)
With `stub/stall` and short limits in the config, expect a timeout error; with a tier of slow failing models and a short `pre_output_seconds`, expect HTTP 504 `upstream_timeout` once that overall wait is reached; with `stub/slow`, close the
connection mid-stream and confirm in the logs that the stub observed the close within a second.

## 7. Configuration refusals (US2)
Start with a tier containing `anthropic/claude-haiku-latest`, an empty tier, a duplicate model, or an
Anthropic model with no `ANTHROPIC_API_KEY`.
Expected: the service exits immediately with a message naming the entry. Changing a tier's model in the file
and restarting changes which model serves it, with no code change.

## 8. Real providers (opt-in, costs a little)
Copy `config/gateway.example.yaml` to `config/gateway.local.yaml`, export `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY`, set `GATEWAY_CONFIG`, restart, call the chat route, and run `uv run pytest -m live`.
Expected: a real streamed answer; the live tests pass (stream shape, finish reason, cancellation, and the
reasoning-budget check from research R13).

## 9. Complete answer helper (US1, FR-023)
Covered by unit and integration tests (`uv run pytest tests/unit/gateway tests/integration`): the helper returns
the same text, finish reason and token counts as the collected stream.

## 10. Logs contain no content (US5)
```bash
docker compose logs service | grep completion_finished
```
Expected: tier, model, attempts, fallback, timings, finish reason and token counts; never message or answer
text. The automated scan test covers success, fallback, failure and cancellation.

## 11. Contract and gate
```bash
uv run pytest tests/contract
BASE_FILE=<copy of the 1.0.0 openapi.yaml> OASDIFF_ERR_IGNORE=specs/002-llm-gateway/contracts/oasdiff-ignore-1.0-to-1.1.txt scripts/contract-diff.sh
```
Expected: contract tests pass against 1.1.0; the gate passes with the one-time ignore file and still fails on
any other breaking change.

## 12. Regression and load
```bash
uv run pytest
SERVICE_TOKEN=... uv run python scripts/load-test.py --streams 20
```
Expected: all spec 001 tests still pass unchanged (SC-009); p95 time to first event under 500 ms with the
stub, and the gateway adds under 50 ms (SC-006).

## Verified on

**2026-10-21, local Docker Compose and local Uvicorn.** Not run: step 8 (real providers) and the `live` tests,
because this machine has no provider credentials; the live tests exist and skip cleanly without keys.

- **Step 1** (default, stub only): the real image starts healthy, `gateway_ready` lists `stub/default` for all
  three tiers, `scripts/smoke.sh` passes.
- **Step 2** (offline fallback): with `config/gateway.fallback-demo.yaml` the logs for one request show a
  `completion_attempt_failed` on `stub/fail-temporary` (category `temporary`) and a `completion_finished`
  on `stub/default` with `fallback_used: true`, tenant and user attached, and no prompt text.
- **Step 3** (every model fails): `[fail-temporary, fail-rate-limited]` gives 503 `upstream_unavailable` with
  `Retry-After: 5`; `[fail-timeout]` gives 504 `upstream_timeout`; `[fail-auth]` gives 502 `upstream_error`;
  all as `application/json` in the standard error shape, no stream opened.
- **Step 4** (failure after output): `[fail-midstream, default]` gives 200 with `token`, `token`, `error` and
  no fallback.
- **Step 5** (safety block): `[blocked, default]` gives `usage` then `done` with `blocked`.
- **Step 6** (limits): a model that never answers with `pre_output_seconds: 1.2` returns 504 after 1.21 s,
  with both attempts logged; a client that gives up while waiting for the first output is covered by the
  automated test `test_gateway_cancellation.py` (provider stream closed within 1.5 s).
- **Step 7** (refusals): a moving alias, a duplicate model, a missing `ANTHROPIC_API_KEY`, an unknown model
  and an empty tier each stop startup with a message naming the entry; the credential value appeared in none
  of them.
- **Step 9**: the full-answer helper is covered by `test_gateway_stream.py` and `test_gateway_failover.py`.
- **Step 10** (no content in logs): `test_no_content_in_gateway_logs.py` scans success, fallback, total
  failure, failure after output, safety block, rejected request, cancellation, the helper and an invalid
  startup for prompt text, answer text and credentials; none appear. The container logs of the demo run
  contained no prompt text either.
- **Step 11** (contract gate): the gate passes 1.0.0 to 1.1.0 with the single-use ignore file, fails without it,
  and still fails on an unrelated breaking change (task T017).
- **Step 12** (regression and load): all spec 001 tests still pass unchanged; under the fallback demo config
  `load-test.py` completed 20 of 20 streams (first event p95 31 ms) and 100 of 100 (p95 224 ms), each stream
  ending in exactly one `done`. Under the default config: 20 streams p95 27 ms, 100 streams p95 205 ms.

