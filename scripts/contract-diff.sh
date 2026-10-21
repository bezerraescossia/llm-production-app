#!/usr/bin/env bash
# Breaking-change gate for the HTTP contract.
#
# Usage:
#   scripts/contract-diff.sh [BASE_REF]          compare against BASE_REF (default origin/main)
#   BASE_FILE=path scripts/contract-diff.sh      compare against a file instead of a git ref
#
# Fails when contracts/v1/openapi.yaml has a breaking change relative to the base, unless a new
# major version exists: contracts/v2/openapi.yaml with a higher major `info.version`
# (constitution principle I: breaking changes MUST bump the MAJOR version).
#
# Error codes are an extensible enum since contract 1.1.0, so adding a code is not a breaking change.
# (The one-time exception that allowed 1.0.0 -> 1.1.0 expired and was removed; constitution 1.3.0.)
set -euo pipefail

OASDIFF_IMAGE="tufin/oasdiff@sha256:0d91f61ec0f2fae305f492a2d5b553938871da22ed6965c6a914e73416b0d4d2"
HEAD_FILE="contracts/v1/openapi.yaml"
BASE_REF="${1:-origin/main}"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

if [[ -n "${BASE_FILE:-}" ]]; then
  cp "$BASE_FILE" "$workdir/base.yaml"
elif git cat-file -e "$BASE_REF:$HEAD_FILE" 2>/dev/null; then
  git show "$BASE_REF:$HEAD_FILE" >"$workdir/base.yaml"
else
  echo "No baseline contract at $BASE_REF:$HEAD_FILE; nothing to compare."
  exit 0
fi
cp "$HEAD_FILE" "$workdir/head.yaml"

major() { sed -n 's/^  version: *\([0-9]*\)\..*/\1/p' "$1" | head -n1; }

if docker run --rm -v "$workdir:/w:ro" "$OASDIFF_IMAGE" breaking /w/base.yaml /w/head.yaml --fail-on ERR; then
  echo "No breaking changes."
  exit 0
fi

base_major="$(major "$workdir/base.yaml")"
if [[ -f contracts/v2/openapi.yaml ]] && (( "$(major contracts/v2/openapi.yaml)" > base_major )); then
  echo "Breaking change accepted: contracts/v2 declares a new major version."
  exit 0
fi
echo "ERROR: breaking contract change without a new major version (contracts/v2/openapi.yaml)." >&2
exit 1
