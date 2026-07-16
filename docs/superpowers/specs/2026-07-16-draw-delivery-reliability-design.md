# Draw Delivery Reliability Design

## Goal

Make the QQ `/draw` command reliably deliver a generated image instead of reporting failure or timeout while the Right Codes asynchronous task continues and later succeeds.

Completion requires a real end-to-end run in which a QQ `/draw` message produces an image message in the original private chat or group. Paid API calls are authorized for verification.

## Observed Failure

The latest `nano-banana-2` task completed successfully in Right Codes after 81 seconds and returned an HTTPS image URL. The local bridge stopped polling earlier after a transient task-query failure and sent `画图失败了，稍后再试。` instead.

The current implementation treats every polling network error, non-2xx response, and unexpected intermediate status as terminal. It also has a 90-second deadline, while observed provider tasks may take more than 130 seconds.

## Chosen Approach

Keep `nano-banana-2` as the primary model because it has already generated a valid result. Harden its asynchronous polling and add `gpt-image-2` as an automatic fallback when the primary task reaches a genuine terminal failure or exhausts the extended deadline.

This preserves the existing Gemini-compatible request and reference-image support while providing a second provider path when Banana cannot complete. A timeout fallback may create a second billable task if the primary task later completes; the user has authorized API charges in favor of reliable delivery.

## Configuration

Add explicit settings with conservative defaults:

- `DRAW_TIMEOUT_SECONDS=240`
- `DRAW_POLL_MAX_TRANSIENT_ERRORS=6`
- `DRAW_FALLBACK_MODEL=gpt-image-2`
- `DRAW_FALLBACK_ENABLED=true`

`DRAW_API_KEY` continues to fall back to `VISION_API_KEY`. No secret value is committed or logged.

## Components

### Primary Gemini-compatible submission

Continue submitting:

`POST /draw/v1beta/models/nano-banana-2:generateContent`

The payload keeps `async: true`, the prompt, optional inline reference image, aspect ratio, and image size.

### Resilient task polling

Continue querying:

`GET /v1/tasks/{task_id}`

Polling behavior changes as follows:

- `queued`, `pending`, `processing`, `running`, and `in_progress` remain non-terminal.
- connection failures, timeouts, HTTP 408, 409, 425, 429, and 5xx responses consume a bounded transient-error budget and then retry after the configured interval;
- any successful task response resets the consecutive transient-error count;
- `completed` returns the image URL from either Images-style `data[].url` or Gemini-style `candidates[].content.parts[].text`;
- `failed` remains terminal and preserves the provider error message;
- the overall deadline is checked independently of individual HTTP retries.

### Image2 fallback

When enabled, terminal primary failure, exhausted transient retries, malformed terminal output, or overall timeout submits:

`POST /draw/v1/images/generations`

with:

- `model: gpt-image-2`
- `prompt`
- `n: 1`
- `size` from the configured aspect ratio
- `imageSize` from the configured image size
- `async: true`
- optional reference image as a data URL array

The returned task is polled through the same resilient task-query implementation. The fallback result uses the same `DrawResult` contract, with provider/model metadata for logging and tests.

### QQ delivery

The draw worker remains responsible for delivery:

1. Send the existing queued acknowledgement.
2. Generate through the primary path and optional fallback.
3. Send the completed URL as a OneBot image segment.
4. If NapCat rejects the image segment, send the URL as text.
5. Only send a failure message after all configured providers have failed.

## Safe Observability

Add draw-specific event logs for:

- provider/model and submission outcome;
- a shortened task identifier;
- polling state changes rather than every identical poll;
- transient HTTP/network failures and retry count;
- fallback activation and reason;
- final status, duration, and whether QQ image delivery succeeded.

Logs must not contain authorization headers, API keys, base64 image data, or full provider response bodies.

## Error Handling

- Missing key or empty prompt fails before submission.
- Reference-image preparation failure is reported without falling back to text-only generation, preserving user intent.
- Primary provider content rejection may fall back to Image2.
- Fallback failure returns a concise QQ error while retaining safe diagnostic details in bridge logs.
- Unhandled worker exceptions are caught and logged so the user receives a terminal response.

## Testing

Add focused regression tests for:

- transient polling HTTP/network errors followed by success;
- pending/running aliases continuing to poll;
- extended deadline behavior;
- transient retry-budget exhaustion;
- OpenAI Images fallback payload, including optional reference image;
- primary failure activating Image2 exactly once;
- primary success avoiding fallback;
- final QQ private/group image delivery and text-URL fallback;
- safe logs excluding keys and base64 data.

Run the focused draw, NapCat, configuration, and runtime-resource tests, followed by the repository's relevant lint commands.

## End-to-End Verification

After restarting the bridge with the new configuration:

1. Send a neutral `/draw` prompt through QQ.
2. Confirm Right Codes records the task.
3. Confirm polling reaches a completed response.
4. Confirm NapCat records a successful image outbound event for the real QQ target.
5. Confirm the image is visible in the originating QQ conversation.

The task is not complete if only unit tests pass or the provider dashboard shows success without QQ delivery.

