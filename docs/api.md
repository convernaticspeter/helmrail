# Helmrail API

Base URL: self-hosted instance root.

## Health

```http
GET /health
```

Returns service status and prototype mode.

## Models

```http
GET /v1/models
```

Returns OpenAI-style model list with:

- `helmrail-fast`
- `helmrail-ultra`

## Chat completions

```http
POST /v1/chat/completions
Content-Type: application/json
```

Request shape follows the OpenAI chat-completions convention:

```json
{
  "model": "helmrail-fast",
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}
```

Response is OpenAI-compatible enough for early client integration and includes `helmrail_trace_id` plus the `X-Helmrail-Trace-Id` header.

Streaming is intentionally not implemented yet.

## Responses

```http
POST /v1/responses
Content-Type: application/json
```

```json
{
  "model": "helmrail-fast",
  "input": "Hello"
}
```

Returns an OpenAI Responses-style object with `output_text` and `helmrail_trace_id`.

## Traces

```http
GET /v1/traces
GET /v1/traces/{run_id}
```

Raw traces are local-only by default.

## Contribution preview

```http
POST /v1/contributions/preview
Content-Type: application/json
```

```json
{"run_id":"run_..."}
```

Returns a redacted, detached preview bundle. It does not upload data.
