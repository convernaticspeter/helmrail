# Helmrail

Self-hosted switchboard for your model subscriptions and APIs.

Connect the accounts you already pay for, route tasks through one OpenAI-compatible endpoint, and keep orchestration, traces, and data policies under your control.

Helmrail is public source and self-hosted first. It is **not accepting pull requests, feature requests, or public support issues yet** while the architecture, connector policy, and anonymized contribution pipeline stabilize.

## Prototype status

This repository currently contains a functional API prototype:

- `GET /health`
- `GET /v1/models`
- `GET /subscriptions`
- `GET /setup`
- `GET /v1/provider-presets`
- `GET /v1/codex/status`
- `POST /v1/codex/run`
- `GET /v1/oracle/status`
- `POST /v1/oracle/run`
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

The local build now proves the API surface, connector registry, Codex/Oracle dry-runs, OpenAI-compatible provider calls, OpenAI-compatible chat proxying for Hermes, trace store, and local redaction/contribution preview path.

## Link subscriptions and API providers

Open the local setup page:

```text
http://127.0.0.1:8765/setup
```

Provider policy:

- **OpenAI subscription:** no key entry. Use `codex_cli` and log in through the local Codex CLI/OAuth flow.
- **GPT-5.5 Pro:** use `oracle_browser`, which wraps the existing Hermes `/pro` Oracle browser connector.
- **Anthropic / Google consumer subscriptions:** not bridged. Use official API products only.
- **API-key providers:** Z.ai Coding Plan, Kimi Coding Plan, MiniMax Coding Plan, Anthropic API, Google Gemini API, and OpenRouter.

Connector types:

- `codex_cli` for OpenAI subscription access through the local Codex CLI command
- `oracle_browser` for GPT-5.5 Pro via Hermes `/pro` Oracle browser automation
- `api_key_local` for supported API providers with a pasted local API key
- `api_key_env` for an environment variable such as `KIMI_API_KEY` or `ANTHROPIC_API_KEY`
- `manual` for a subscription/account that is registered but not automated yet

Example: link OpenAI subscription through Codex CLI, without an API key:

```bash
curl http://127.0.0.1:8765/v1/subscriptions \
  -H 'Content-Type: application/json' \
  -d '{
    "provider":"openai",
    "account_label":"OpenAI Subscription",
    "plan":"ChatGPT/Codex subscription",
    "connector_type":"codex_cli",
    "credential_ref":"codex",
    "model_aliases":["gpt-5.5","gpt-5.4"]
  }'
```

Example: link Kimi Coding Plan via API key:

```bash
curl http://127.0.0.1:8765/v1/subscriptions \
  -H 'Content-Type: application/json' \
  -d '{
    "provider":"kimi",
    "account_label":"Kimi Coding Plan",
    "plan":"Kimi K2.7 Code",
    "connector_type":"api_key_local",
    "base_url":"https://api.moonshot.ai/v1",
    "api_key":"***",
    "model_aliases":["kimi-k2.7-code","kimi-k2.7-code-highspeed"],
    "metadata":{"api_style":"openai_compatible"}
  }'
```

Dry-run a Codex route without starting Codex or making an API call:

```bash
curl http://127.0.0.1:8765/v1/codex/run \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Review this function","model":"gpt-5.5","dry_run":true}'
```

Dry-run a GPT-5.5 Pro Oracle consult:

```bash
curl http://127.0.0.1:8765/v1/oracle/run \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Give me a second opinion","model":"gpt-5.5-pro","dry_run":true}'
```

Linked `model_aliases` appear in `GET /v1/models` while the connector is enabled. OpenAI-compatible aliases can be called through `POST /v1/chat/completions`; Helmrail replaces the public alias with the configured upstream model before forwarding.

## Test through Hermes

A local Hermes custom provider can point at Helmrail's OpenAI-compatible endpoint:

```yaml
providers:
  helmrail:
    name: Helmrail Local
    base_url: http://127.0.0.1:8765/v1
    key_env: HELMRAIL_API_KEY
    api_mode: chat_completions
    model: helmrail-openrouter
    models:
      helmrail-openrouter: {context_length: 128000}
      helmrail-kimi: {context_length: 262144}
```

Run a smoke test without switching Hermes' default provider:

```bash
hermes chat -q 'Reply with exactly: HERMES_HELMRAIL_OK' \
  --provider custom:helmrail \
  -m helmrail-openrouter \
  --toolsets safe \
  -Q
```

The local launchd wrapper should load the existing provider keys from `~/.hermes/.env` and keep Helmrail bound to `127.0.0.1:8765`. `HELMRAIL_API_KEY` is the bearer token Hermes uses when calling Helmrail.

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
