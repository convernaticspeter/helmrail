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

## Link providers and API keys

Open the local setup page:

```text
http://127.0.0.1:8765/setup
```

The setup UI is meant for normal users:

1. Paste the local admin key once. It lives at `~/.hermes/secrets/helmrail-admin-api-key.txt`.
2. Pick a provider preset such as OpenAI / Codex, Anthropic, Gemini, OpenRouter, xAI, Mistral, Groq, DeepSeek, Together, Perplexity, or Custom OpenAI-compatible.
3. Paste the provider API key.
4. Save. Helmrail stores the key locally and only returns a masked preview.
5. Use the Codex workbench with an OpenAI/OpenAI-compatible provider and your chosen coding model.

Connector types:

- `api_key_local` for a pasted local API key
- `api_key_env` for an environment variable name such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- `codex_cli` for a local Codex CLI command when installed
- `browser_profile` for a local logged-in browser profile path
- `oauth` for a future OAuth account connection
- `manual` for a paid subscription that is registered but not automated yet

Example API call:

```bash
curl http://127.0.0.1:8765/v1/subscriptions \
  -H 'Content-Type: application/json' \
  -d '{
    "provider":"openai",
    "account_label":"OpenAI Codex",
    "plan":"Codex / OpenAI API",
    "connector_type":"api_key_local",
    "base_url":"https://api.openai.com/v1",
    "api_key":"sk-...",
    "model_aliases":["codex"]
  }'
```

Dry-run a Codex route without making a provider call:

```bash
curl http://127.0.0.1:8765/v1/codex/run \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Review this function","model":"codex","dry_run":true}'
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
