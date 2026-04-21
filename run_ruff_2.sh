#!/usr/bin/env bash
set -euo pipefail

source qq-ai-bridge/venv/bin/activate
ruff check qq-ai-bridge/apps/qq_ai_bridge/skills/ --fix
