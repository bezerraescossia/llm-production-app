#!/usr/bin/env bash
# Smoke test against a running stack (docker compose up --wait).
# Usage: SERVICE_TOKEN=... [BASE_URL=http://localhost:8080] scripts/smoke.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
: "${SERVICE_TOKEN:?SERVICE_TOKEN must be set to one of the configured service tokens}"

fail() { echo "SMOKE FAILED: $*" >&2; exit 1; }

for _ in $(seq 1 30); do
  curl -fsS "$BASE_URL/v1/health/live" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "$BASE_URL/v1/health/live" >/dev/null || fail "liveness check did not pass"

body="$(curl -fsSN "$BASE_URL/v1/chat/stream" \
  -H "Authorization: Bearer $SERVICE_TOKEN" -H "X-Tenant-Id: smoke" -H "X-User-Id: smoke-user" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"smoke test"}]}')" || fail "streaming request failed"

last_event="$(printf '%s\n' "$body" | tr -d '\r' | grep '^event:' | tail -n1 | cut -d' ' -f2)"
[[ "$last_event" == "done" ]] || fail "last event was '$last_event', expected 'done'"
[[ "$(printf '%s\n' "$body" | tr -d '\r' | grep -c '^event: done')" == "1" ]] || fail "expected exactly one done event"

ready="$(curl -sS -H "Authorization: Bearer $SERVICE_TOKEN" "$BASE_URL/v1/health/ready")"
[[ "$ready" == *'"status":"ready"'* ]] || fail "readiness not ready: $ready"

echo "smoke ok: streamed answer ended in done, readiness ready"
