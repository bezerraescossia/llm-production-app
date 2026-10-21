# Data Model: LLM Gateway

Nothing is persisted. Entities are in-memory configuration or per-request objects, except the YAML
configuration file.

## Configuration (YAML, path in `GATEWAY_CONFIG`; built-in stub-only config when unset)

```yaml
default_tier: medium            # tier used by the chat route
timeouts:
  first_output_seconds: 15      # per attempt
  pre_output_seconds: 45        # overall wait for the first piece, across all attempts, retries and fallbacks
  idle_seconds: 20              # between streamed pieces
  total_seconds: 120            # whole completion, including retries and backoff
retry:
  max_attempts_per_model: 2     # one retry
  backoff_base_seconds: 0.25
  backoff_max_seconds: 2.0      # full jitter
cooldown:
  failure_threshold: 3          # consecutive counted failures
  seconds: 30
tiers:
  small:
    models: [anthropic/claude-haiku-5-5, openai/gpt-5-nano-2025-08-07]
    generation: {max_output_tokens: {default: 2048, ceiling: 4096}, temperature: {default: 0.3, ceiling: 1.0}}
  medium: { ... }
  large: { ... }
```

| Field | Rule |
|---|---|
| `tiers` | must contain `small`, `medium` and `large`; each has a non-empty, duplicate-free `models` list |
| model entry | `provider/model-id`; provider is `anthropic`, `openai` or `stub`; the model id is exact (see below) |
| `default_tier` | must be one of the configured tiers |
| `timeouts.*`, `retry.*`, `cooldown.*` | positive numbers; `first_output_seconds <= pre_output_seconds <= total_seconds`; `idle_seconds <= total_seconds` |
| `generation.*.default` | `0 < default <= ceiling`; temperature between 0 and 2 |
| optional `max_input_tokens` per model | override for models missing from LiteLLM's map (required for `stub/*`, defaulted to 100000) |

**Model id rules (startup refuses otherwise, naming the entry)**: the id must not end in `latest`; must be in
LiteLLM's model map for its provider, or carry an explicit `max_input_tokens` override; must not repeat
within a tier; its provider must be enabled with a credential (`anthropic` needs `ANTHROPIC_API_KEY`,
`openai` needs `OPENAI_API_KEY`; `stub` needs none).

**Environment (added to Settings)**: `GATEWAY_CONFIG` (optional path), `ANTHROPIC_API_KEY` and
`OPENAI_API_KEY` (optional secrets, never logged; empty string treated as unset).

## Tier
`name` (small|medium|large), ordered `models: list[ModelCandidate]`, `generation: GenerationLimits`.

## ModelCandidate
`provider`, `model_id` (exact), `max_input_tokens`. Identity is `provider/model_id`; unique within a tier.

## GenerationLimits / GenerationSettings
- **Limits** (config): per setting `default` and `ceiling`.
- **Settings** (per request): `max_output_tokens: int | None`, `temperature: float | None`. `None` means the
  tier default. A value above its ceiling raises `GenerationSettingError` (a programming error, not an HTTP
  code). Unsupported parameters for a model are dropped explicitly and logged once at startup.

## CompletionRequest
`tier: str`, `messages: list[Message]` (role user|assistant, content), `settings: GenerationSettings`,
`mode` implied by the call (`stream` or `complete`). Request context (request, tenant, user ids) is read from
the existing request context, not passed in. Unknown `tier` raises `UnknownTierError` before any provider is
contacted.

## ProviderChunk (provider adapter output)
Exactly one of: `text: str`, `finish_reason: "stop"|"length"|"blocked"`, `usage: (input|None, output|None)`.

## ProviderError
`category`: `temporary | rate_limited | timeout | unavailable | auth | context_too_large | content_blocked |
invalid_request`; optional `retry_after_seconds`. Carries no provider text.

## Attempt (internal, logged)
`model`, `number`, `outcome` (`success` or a ProviderError category), `started_at`, `first_output_ms`.

## Completion (result of the helper)
`text`, `finish_reason`, `input_tokens: int|None`, `output_tokens: int|None`, `model`, `attempts`,
`fallback_used`.

## FailureCooldown (in-memory)
Per `provider/model_id`: `consecutive_failures`, `skip_until`. Rules in research R15. No tenant data.

## Streams

```text
open() ── attempts ──► [first piece or terminal blocked] ──► CompletionStream
                                                              │
                                  token… ─► usage ─► done | error   (no retry/fallback after the first piece)
```

State of a completion: `selecting → attempting → streaming → finished | failed | cancelled`.
`failed` before streaming surfaces as a `ServiceError` (HTTP); after streaming begins it is an `error` event.

## Error mapping (see research R6)
`upstream_unavailable` 503, `upstream_timeout` 504 (also when the overall wait for the first output is reached),
`upstream_error` 502, `input_too_large` 422, unexpected exception `internal_error` 500; mid-stream codes reuse the same strings.
