# Project Context

## Repo Shape

- This workspace is primarily a Python repo. The root entrypoint files are driven by `pyproject.toml`, shell scripts, and Python modules.
- Do not assume the workspace root contains a `package.json`.
- The main application areas are `qq-ai-bridge` and `pc-agent`.

## Working Style

- Prefer surgical fixes over broad rewrites.
- Prefer `rg` or other targeted search before broad directory walks.
- Avoid spending extra turns proving the absence of files that are clearly not part of the root project structure.

## Repo-Specific Hints

- For QQ bridge routing, keyword matching, schedule behavior, and chat handling, inspect `qq-ai-bridge/apps/qq_ai_bridge`.
- For desktop automation and OCR matching, inspect `pc-agent/apps/pc_agent`.
- When validating the schedule service in this repo, a focused command is:
  `PYTHONPATH=qq-ai-bridge python3 qq-ai-bridge/tests/test_schedule_service.py`
- For Python tooling in this repo, do not assume `ruff` is globally available.
- Prefer the repo-local virtualenv: `source qq-ai-bridge/venv/bin/activate && <command>`.
- If you need linting for QQ bridge services, prefer `bash run_ruff.sh`.
- If you need linting for QQ bridge skills, prefer `bash run_ruff_2.sh`.
- If a shell script returns permission denied, retry it with `bash <script>` before exploring other options.
