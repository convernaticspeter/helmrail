# Helmrail

Self-hosted switchboard for your model subscriptions and APIs.

Connect the accounts you already pay for, route tasks through one OpenAI-compatible endpoint, and keep orchestration, traces, and data policies under your control.

Helmrail is public source and self-hosted first. It is **not accepting pull requests, feature requests, or public support issues yet** while the architecture, connector policy, and anonymized contribution pipeline stabilize.

## Prototype status

This repository currently contains a functional API prototype:

- `GET /health`
- `GET /v1/models`
- `GET /subscriptions`
- `GET /v1/subscriptions`
- `POST /v1/subscriptions`
- `GET /v1/subscriptions/{subscription_id}`
- `PATCH /v1/subscriptions/{subscription_id}`
- `DELETE /v1/subscriptions/{subscription_id}`
- `POST /v1/subscriptions/{subscription_id}/probe`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/traces`
- `GET /v1/traces/{run_id}`
- `POST /v1/contributions/preview`

The first build does not call upstream model providers yet. It proves the API surface, subscription registry, trace store, Docker deployment, and local redaction/contribution preview path.

## Link subscriptions

Open `/subscriptions` in a browser or use the API directly. Helmrail stores connector references, not raw secrets. Use:

- `api_key_env` for an environment variable name such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- `browser_profile` for a local logged-in browser profile path
- `oauth` for an OAuth account placeholder/status
- `manual` for a paid subscription that is registered but not automated yet

Example:

```bash
curl http://localhost:8000/v1/subscriptions \
  -H 'Content-Type: application/json' \
  -d '{
    "provider":"openai",
    "account_label":"Peter ChatGPT Pro",
    "plan":"ChatGPT Pro",
    "connector_type":"api_key_env",
    "credential_ref":"OPENAI_API_KEY",
    "model_aliases":["gpt-5.5-pro"]
  }'
```

Probe the connector reference:

```bash
curl -X POST http://localhost:8000/v1/subscriptions/sub_.../probe
```

Linked `model_aliases` appear in `GET /v1/models` while the subscription is enabled.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Or with Docker:

```bash
docker compose up --build
```

Then:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"helmrail-fast","messages":[{"role":"user","content":"Hello"}]}'
```

## Optional API auth

By default the prototype is open on localhost. To require bearer auth for mutable `/v1/*` endpoints:

```bash
export HELMRAIL_API_KEY='test-token'
export HELMRAIL_REQUIRE_AUTH=true
```

Then call:

```bash
curl http://localhost:8000/v1/responses \
  -H 'Authorization: Bearer test-token' \
  -H 'Content-Type: application/json' \
  -d '{"model":"helmrail-fast","input":"Hello"}'
```

## Local traces and contribution preview

Raw traces are stored locally in SQLite. Nothing is uploaded by default.

The contribution preview endpoint returns an anonymized/detached draft bundle. It is intentionally preview-only in v0.1.

```bash
RUN_ID="run_..."
curl http://localhost:8000/v1/contributions/preview \
  -H 'Content-Type: application/json' \
  -d "{\"run_id\":\"$RUN_ID\"}"
```

See [`docs/data-contribution.md`](docs/data-contribution.md).

## Governance

Helmrail is public source, not open contribution yet.

We are not accepting:

- pull requests
- feature requests
- support issues
- roadmap requests
- connector requests

See [`CONTRIBUTING.md`](CONTRIBUTING.md).
