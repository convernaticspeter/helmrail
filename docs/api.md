# Helmrail API

Base URL: self-hosted instance root. Internal pilot default: `http://127.0.0.1:8765`.

## Health

```http
GET /health
```

Returns service status, auth state, and runtime caps:

```json
{
  "ok": true,
  "service": "helmrail",
  "mode": "prototype-wrapper",
  "trace_store": "sqlite",
  "auth_required": true,
  "limits": {
    "max_provider_calls": 8,
    "max_parallel_workers": 3,
    "provider_timeout_seconds": 120,
    "max_output_tokens": 4096
  }
}
```

## Models

```http
GET /v1/models
```

Returns OpenAI-style model list including direct aliases and coordinator aliases:

- `helmrail-fast`
- `helmrail-coordinator`
- `helmrail-auto`
- `helmrail-ultra`
- linked provider aliases such as `helmrail-openrouter`, `helmrail-kimi`, etc.

## Chat completions

```http
POST /v1/chat/completions
Authorization: Bearer ***
Content-Type: application/json
```

Request shape follows the OpenAI chat-completions convention:

```json
{
  "model": "helmrail-coordinator",
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}
```

Response is a normal `chat.completion` and includes `X-Helmrail-Trace-Id` in the response header. Direct linked OpenAI-compatible provider aliases may also include route metadata in the body; coordinator aliases keep orchestration internals in the local trace only.

When `stream:true` is supplied, Helmrail executes the same non-streaming internal graph and returns an OpenAI-compatible `text/event-stream` with the final answer as a single delta chunk. This is a compatibility stream for clients such as Hermes, not token-by-token upstream passthrough.

## Responses

```http
POST /v1/responses
Authorization: Bearer ***
Content-Type: application/json
```

```json
{
  "model": "helmrail-fast",
  "input": "Hello"
}
```

Returns an OpenAI Responses-style object with `output_text` and `helmrail_trace_id`. This endpoint is still the simple prototype path.

## Router

```http
GET /v1/router/policies
GET /v1/router/catalog
POST /v1/router/plan
```

`/v1/router/plan` is side-effect-free. Coordinator aliases in `/v1/chat/completions` execute the hidden graph.

## Subscriptions

```http
GET /v1/subscriptions
POST /v1/subscriptions
GET /v1/subscriptions/{subscription_id}
PATCH /v1/subscriptions/{subscription_id}
DELETE /v1/subscriptions/{subscription_id}
POST /v1/subscriptions/{subscription_id}/probe
```

API responses mask local secrets and expose only `has_secret` / `secret_preview`.

## Traces

```http
GET /v1/traces
GET /v1/traces/{run_id}
```

Raw traces are local-only by default. They may contain operational debugging details and should not be exported blindly.

## Training samples and feedback

```http
GET /v1/training-samples
GET /v1/training-samples/{sample_id}
GET /v1/training-samples/{sample_id}/feedback
POST /v1/training-samples/{sample_id}/feedback
GET /v1/training-exports/jsonl
```

Training samples are anonymized/local records derived from raw traces. Feedback labels are redacted before storage and embedded back into the sample.

## Preference pairs

```http
GET /v1/training-preference-pairs
GET /v1/training-preference-exports/jsonl
GET /v1/training-samples/{sample_id}/preference-pairs
```

Preference pairs are derived only from anonymized samples:

- verifier accepted output over rejected output
- synthesizer output over individual candidates
- race winner over other race candidates as an operational signal
- human corrected output over selected/final model output

## Contribution preview

```http
POST /v1/contributions/preview
Authorization: Bearer ***
Content-Type: application/json
```

```json
{"run_id":"run_..."}
```

Returns the stored anonymized sample for a run when available. It does not upload data.
