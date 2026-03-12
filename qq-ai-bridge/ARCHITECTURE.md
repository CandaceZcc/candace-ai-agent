# Architecture

## Overview

This repository now follows a layered structure that separates:

- application entrypoints
- adapters
- services
- shared utilities
- runtime data
- automation runtimes

The current system has two main applications:

- `qq-ai-bridge`: receives QQ webhook events, routes messages, coordinates AI, vision, file handling, and desktop-agent integration
- `pc-agent`: exposes local desktop automation and OCR actions over HTTP

## Top-Level Layout

```text
qq-ai-bridge/
├── apps/
├── shared/
├── vision/
├── config/
├── data/
├── tmp/
├── bridge.py
├── image_utils.py
├── storage_utils.py
└── ARCHITECTURE.md

pc-agent/
├── apps/
├── agent.py
└── start.sh
```

## Application Boundaries

### `apps/qq_ai_bridge`

This package contains the QQ-facing application structure.

- `app.py`
  - exposes the Flask app entrypoint
- `runtime.py`
  - current compatibility runtime containing the existing integrated logic
- `adapters/`
  - webhook and message/NapCat integration boundaries
- `services/`
  - chat, file, agent, prompt, and vision service boundaries
- `config/`
  - application-level settings access
- `logging/`
  - logging policy helpers

The long-term direction is to keep shrinking `runtime.py` as logic moves fully into adapters and services.

### `apps/pc_agent`

This package contains the automation runtime structure.

- `app.py`
  - exposes the Flask app entrypoint
- `adapters/http_api.py`
  - HTTP API boundary
- `desktop/`
  - mouse, keyboard, screen, OCR, and text-matching capabilities
- `browser/`
  - browser runtime boundary
  - `playwright_runtime.py` is reserved for future browser automation
- `runtime/actions.py`
  - compatibility exports for action handlers

The long-term direction is to move route logic out of `agent.py` into these modules incrementally.

## Shared Layer

### `shared/ai`

- `llm_client.py`
- `vision_client.py`

These provide compatibility wrappers around current AI and vision clients so they can be reused across applications.

### `shared/storage`

- `workspaces.py`

This layer is the shared storage boundary for user/group workspace access and lightweight persistence helpers.

### `shared/utils`

- `text.py`
- `files.py`

This layer collects reusable utility helpers that should not belong to one app only.

## Runtime Data Boundary

Runtime data remains outside application code.

- `data/private_users/`
  - per-user memory, history, and style samples
- `data/groups/`
  - per-group logs and style samples
- `data/private_uploads/`
  - current private file upload area
- `data/group_uploads/`
  - current group file upload area
- `tmp/images/`
  - temporary image downloads for vision processing

This separation allows code refactors without moving runtime state.

## Request Flow

### QQ text or image message

1. NapCat sends webhook request to `bridge.py`
2. `bridge.py` loads `apps.qq_ai_bridge.app`
3. Webhook route in `apps.qq_ai_bridge.runtime` parses the message
4. Request is routed to:
   - private chat handling
   - group chat handling
   - file handling
   - image understanding
   - desktop-agent command handling
5. Response is sent back through NapCat HTTP API

### Desktop automation

1. QQ bridge creates an agent plan or direct agent action
2. QQ bridge calls `pc-agent` over HTTP
3. `pc-agent` executes desktop/browser/OCR actions locally
4. Result is returned as text to the QQ bridge

## Design Principles

The refactor follows these principles:

- keep runtime data separate from code
- add modular boundaries before deep rewrites
- preserve existing functionality through compatibility wrappers
- avoid large all-at-once rewrites
- prepare explicit extension points for:
  - browser automation
  - task memory
  - skills
  - richer storage and learning

## Current Transitional State

The architecture is intentionally transitional.

Important points:

- `apps/qq_ai_bridge/runtime.py` still contains most existing bridge logic
- `agent.py` still contains most existing pc-agent runtime logic
- new packages currently act as stable boundaries and compatibility wrappers

This was done to avoid breaking current behavior while creating a clean path for future extraction.

## Recommended Next Steps

1. Move QQ webhook parsing out of `runtime.py` into `apps/qq_ai_bridge/adapters/webhook.py`
2. Move NapCat sender/client logic into `adapters/napcat_client.py`
3. Move prompt construction into `services/prompt_service.py`
4. Move file extraction into `services/file_service.py`
5. Move agent planning/execution into `services/agent_service.py`
6. Move pc-agent route handlers into `apps/pc_agent/adapters/http_api.py`
7. Move mouse/keyboard/OCR implementations out of `agent.py`
8. Add Playwright implementation under `apps/pc_agent/browser/playwright_runtime.py`

## Run Commands

QQ bridge:

```bash
cd /home/cancade/qq-ai-bridge
python3 bridge.py
```

pc-agent:

```bash
cd /home/cancade/pc-agent
PC_AGENT_PORT=5050 python3 agent.py
```
