# Helmrail

Self-hosted switchboard for your model subscriptions and APIs.

Connect the accounts you already pay for, route tasks through one OpenAI-compatible endpoint, and keep orchestration, traces, and data policies under your control.

Helmrail is public source and self-hosted first. It is **not accepting pull requests, feature requests, or public support issues yet** while the architecture, connector policy, and anonymized contribution pipeline stabilize.

## Prototype status

This repository currently contains a functional API prototype:

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `GET /v1/traces`
- `GET /v1/traces/{run_id}`
- `POST /v1/contributions/preview`

The first build does not call upstream model providers yet. It proves the API surface, trace store, Docker deployment, and local redaction/contribution preview path.

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
