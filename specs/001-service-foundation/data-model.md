# Data Model: Service Foundation

No data is persisted by this spec (FR-019). The entities below are in-memory and per request, except
`Contract` and `Configuration`, which are files and environment.

## Caller identity
| Field | Type | Rules |
|---|---|---|
| `service_credential` | secret string | Matches one of 1–2 configured tokens; never logged or stored beyond the check |
| `tenant_id` | string | Required; `^[A-Za-z0-9._:@-]{1,128}$`; no lookup in any tenant list |
| `user_id` | string | Required; same pattern |

Validation order: credential first (401 `unauthorized`), then identity headers (400 `invalid_identity`,
`details.field` names the first failing header), then body.

## RequestContext
Created by middleware for every request; stored in a context variable.

| Field | Type | Rules |
|---|---|---|
| `request_id` | string | Client value if it matches `^[A-Za-z0-9._-]{8,128}$`, else UUIDv4 |
| `tenant_id`, `user_id` | string | From Caller identity once validated |
| `received_at` | timestamp | Set at acceptance |
| `contract_version` | string | Semantic version of the served contract |

Bound onto every log entry and echoed in the `X-Request-Id` response header and the error shape.

## Request lifecycle
```text
accepted ──► streaming ──► completed
   │             ├───────► failed      (error event emitted)
   │             └───────► cancelled   (client disconnected; no event can be delivered)
   └─► rejected (any error before streaming starts; HTTP error response, no stream)
```
Exactly one terminal state per request. `rejected` never opens a stream.

## ChatRequest (body)
| Field | Type | Rules |
|---|---|---|
| `messages` | array of Message | 1–100 items (configurable); last item has role `user` |
| Message `role` | enum | `user` or `assistant` |
| Message `content` | string | 1–32,000 characters |

Total body limit 256 KiB (configurable). Unknown fields are rejected so the contract stays strict.

## StreamEvent
Common envelope: SSE `id` = sequence number from 0, `event` = type, `data` = JSON payload.

| Type | Payload | In 001 |
|---|---|---|
| `token` | `{index, text}` | emitted |
| `tool_call` | `{id, name, arguments}` informational | defined only |
| `tool_result` | `{id, name, status: ok\|error, content?}` informational | defined only |
| `citation` | `{source_id, title, uri?, snippet?}` | defined only |
| `usage` | `{input_tokens, output_tokens, cost_usd}` (cost nullable) | emitted, zeros and null cost |
| `done` | `{finish_reason: stop\|length\|blocked\|cancelled}` | emitted with `stop` |
| `error` | `{code, message}` | emitted on mid-stream failure |

Rules: a stream has exactly one terminal event (`done` or `error`), which is last; `usage` precedes `done`
when present; sequence numbers have no gaps.

## Error
`{error: {code, message, request_id, details?, retry_after_seconds?}}`

| Code | HTTP | Meaning |
|---|---|---|
| `unauthorized` | 401 | Missing or invalid service credential |
| `invalid_identity` | 400 | Tenant or user header missing, empty, too long or bad characters (`details.field`) |
| `validation_error` | 422 | Body fails schema validation (`details.errors`) |
| `history_too_long` | 422 | More messages than the limit |
| `payload_too_large` | 413 | Body over the size limit |
| `rate_limited` | 429 | Reserved (FR-020); never emitted in 001 |
| `shutting_down` | 503 | Service draining; has `Retry-After` |
| `not_found` | 404 | Unknown route |
| `method_not_allowed` | 405 | Route exists but not for this method |
| `internal_error` | 500 | Unexpected failure; message is generic, detail only in logs |

## Dependency (readiness)
| Field | Type | Rules |
|---|---|---|
| `name` | string | From `READINESS_DEPENDENCIES` |
| `status` | enum | `up` or `down` (TCP connect within 1 s) |

Overall readiness is `ready` only if every configured dependency is `up`.

## Contract
Files `contracts/v1/openapi.yaml` and `contracts/v1/events.schema.json` at the repository root, versioned with semantic versioning.
Major version = URL prefix. Initial version `1.0.0`.

## Configuration (environment)
| Variable | Default | Rule |
|---|---|---|
| `SERVICE_TOKENS` | none (required) | 1–2 comma-separated tokens, each ≥ 32 chars; service fails to start otherwise |
| `READINESS_DEPENDENCIES` | empty | `name=host:port,…` |
| `MAX_REQUEST_BYTES` | 262144 | positive integer |
| `MAX_MESSAGES` | 100 | positive integer |
| `SHUTDOWN_GRACE_SECONDS` | 20 | positive integer |
| `PLACEHOLDER_TOKEN_DELAY_MS` | 0 | non-negative integer |
| `LOG_LEVEL` | `INFO` | standard levels |
