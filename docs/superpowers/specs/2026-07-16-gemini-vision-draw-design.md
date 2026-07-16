# Gemini Vision and `/draw` Design

## Goal

Use the RightCodes relay for Gemini image understanding and add QQ image generation triggered by messages containing `/draw`.

## Scope

- Configure image understanding with `gemini-3-flash-preview` through the RightCodes Gemini native API.
- Add text-to-image generation using the RightCodes asynchronous Gemini drawing API.
- Support `/draw` in private chats and in groups already allowed by the bridge whitelist and group configuration.
- If a `/draw` message contains an image, use the first image as an optional reference image.
- Send the generated image back to the same private chat or group.
- Keep the existing DeepSeek text-model configuration unchanged.

## External APIs

### Image understanding

- Endpoint: `https://right.codes/gemini/v1beta/models/gemini-3-flash-preview:generateContent`
- Authentication: `x-goog-api-key: <key>`
- Request format: Gemini `generateContent` with text plus an `inline_data` image part.
- Response text: concatenate text from `candidates[].content.parts[].text`.

### Image generation

- Submit endpoint: `POST https://www.right.codes/draw/v1beta/models/nano-banana-2:generateContent`
- Authentication: `Authorization: Bearer <key>`
- Required request field: `"async": true`
- Default image settings: aspect ratio `1:1`, image size `1K`.
- Task endpoint: `GET https://www.right.codes/v1/tasks/{task_id}`
- Poll interval: 2 seconds.
- Maximum wait: 90 seconds.
- Completed image URL: extract text URLs from `candidates[].content.parts[]`; retain support for an Images-style `data[].url` response.

## Configuration

The machine-local secret file remains the source of real credentials.

- `VISION_API_URL`: full Gemini `generateContent` endpoint.
- `VISION_API_KEY`: RightCodes API key.
- `VISION_MODEL`: `gemini-3-flash-preview`.
- `DRAW_API_KEY`: optional override; when empty, drawing reuses `VISION_API_KEY`.
- `DRAW_BASE_URL`: defaults to `https://www.right.codes`.
- `DRAW_MODEL`: defaults to `nano-banana-2`.
- `DRAW_ASPECT_RATIO`: defaults to `1:1`.
- `DRAW_IMAGE_SIZE`: defaults to `1K`.
- `DRAW_POLL_INTERVAL_SECONDS`: defaults to `2`.
- `DRAW_TIMEOUT_SECONDS`: defaults to `90`.

The committed `.env.example` documents the variables but contains no real key.

## Components

### Vision client adaptation

The existing `vision/client.py` remains the single image-understanding client. It will build the Gemini-native payload, use `x-goog-api-key`, and parse Gemini candidates. Existing image normalization, error mapping, and `VisionResult` behavior remain intact.

### Drawing client

A focused drawing service will:

1. Validate the prompt and configuration.
2. Build the Gemini asynchronous generation payload.
3. Optionally download and Base64-encode the first reference image.
4. Submit the task and require a non-empty `task_id`.
5. Poll until completed, failed, or timed out.
6. Return a structured result containing status, image URL, task ID, and safe error text.

The service will not expose credentials in logs, exceptions, or user-visible replies.

### Draw skill

`DrawSkill` will be registered before `ImageUnderstandingSkill` and `ChatSkill`, ensuring `/draw` wins even when the message includes a reference image.

- Trigger: case-sensitive occurrence of `/draw` anywhere in normalized message text.
- Prompt: text after the first `/draw`, trimmed.
- Empty prompt: send `用法：/draw 你想画的内容` without calling the API.
- Valid prompt: send a short progress message, start a daemon worker, and return control to the webhook immediately.
- Completion: the worker sends the generated image to the original private chat or group.
- Failure or timeout: the worker sends a concise failure message without provider internals or secrets.

The command follows existing repository access boundaries: groups must be whitelisted, enabled, and allowed to reply. No new user-level authorization policy is introduced.

### NapCat image sending

Add private and group image helpers that send a OneBot image segment:

```json
[{"type": "image", "data": {"file": "https://example.com/result.png"}}]
```

The group helper can include a reply segment for the triggering message. If NapCat rejects the image segment, the draw worker sends the result URL as a text fallback.

## Data Flow

1. Webhook parses the incoming message and any attached image URL.
2. `DrawSkill` detects `/draw` before normal image understanding or chat routing.
3. The skill acknowledges the request and launches a background worker.
4. The worker submits the asynchronous RightCodes draw request.
5. The worker polls the task endpoint until a terminal result.
6. The worker sends the result image through NapCat, replying to the triggering group message when possible.

Ordinary image messages without `/draw` continue through `ImageUnderstandingSkill` and Gemini Vision.

## Error Handling

- Missing Vision configuration keeps the existing Vision fallback behavior.
- Missing Draw key/model returns a configuration error without starting a task.
- Authentication failures produce a short configuration/authentication reply.
- Missing task IDs and malformed responses are treated as provider response failures.
- `queued`, `processing`, and `in_progress` continue polling.
- `failed` stops polling and uses `error.message` only after sanitization.
- Timeout stops polling after 90 seconds.
- Network errors are logged without headers or request credentials.
- NapCat image-send failure falls back to sending the image URL as text.

## Testing Strategy

Implementation follows red-green-refactor TDD.

- Vision client tests verify Gemini headers, `inline_data` payload shape, and candidate text extraction.
- Draw service tests verify submission payload, task polling, completed URL extraction, failed tasks, and timeout behavior.
- Draw skill tests verify command detection, prompt extraction, empty-prompt handling, precedence over image understanding, and private/group delivery selection.
- NapCat tests verify private/group image message payloads and group reply segments.
- Configuration tests verify Gemini Vision defaults, Draw defaults, and absence of real keys in `.env.example`.
- Focused existing Vision, skill registry, webhook, and NapCat tests run after the new tests pass.

## Non-Goals

- No image history gallery, admin UI, quota system, or per-user concurrency controls.
- No changes to the DeepSeek text model.
- No support for multiple generated images per command.
- No user-selectable aspect ratio or resolution syntax in the first version.
