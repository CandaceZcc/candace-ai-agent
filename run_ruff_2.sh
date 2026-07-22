#!/usr/bin/env bash
set -euo pipefail

RUFF_BIN="${RUFF_BIN:-.venv/bin/ruff}"
if [[ ! -x "$RUFF_BIN" ]]; then
  printf 'Ruff executable not found: %s\n' "$RUFF_BIN" >&2
  exit 2
fi
"$RUFF_BIN" check qq-ai-bridge/apps/qq_ai_bridge/skills/
