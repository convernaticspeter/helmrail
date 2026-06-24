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
- `GET /v1/router/policies`
- `GET /v1/router/catalog`
- `POST /v1/router/plan`
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

The local build now proves the API surface, connector registry, deterministic router planning, Codex/Oracle dry-runs, OpenAI-compatible provider calls, OpenAI-compatible chat proxying for Hermes, trace store, and local redaction/contribution preview path.

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
    "base_url":"https://api.kimi.com/coding/v1",
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

Kimi coding-plan keys with the `sk-kimi-` prefix use `https://api.kimi.com/coding/v1`; legacy Moonshot API keys may still use `https://api.moonshot.ai/v1`. Helmrail adds the required Kimi Coding user-agent and normalizes temperature for that endpoint.

## Fugu-style coordinator model

Helmrail exposes coordinator aliases through the normal OpenAI-compatible `/v1/chat/completions` API:

- `helmrail-coordinator`
- `helmrail-auto`
- `helmrail-ultra`

These behave like regular models to API clients. The response body is a normal `chat.completion`; internal routing, planner JSON, worker plan, and training metadata are stored only in the local trace store and contribution-preview path.

Current coordinator flow:

1. Resolve the fixed coordinator model (`gpt-5.5` by default, usually via OpenRouter).
2. Run a hidden LLM planning pass — not keyword classification — to select task profile, mode, capabilities, tool affinity, and worker instructions.
3. Resolve that LLM-selected profile into runnable worker/subscription metadata.
4. Run the coordinator answer pass and return only the final model response.
5. Store local trace data for future coordinator training (`training_intent: future_coordinator_model`). Nothing uploads automatically.

This follows the Sakana Fugu interface idea: **multi-agent system as a model**. Raw linked provider aliases still work as direct proxy models when called explicitly.

## Router planning

Helmrail also keeps a **model-level** router for transparent planning/debugging. Policies reference real model IDs (e.g. `gpt-5.5`, `claude-opus-4.6`), not provider aliases. Helmrail then resolves each model to the best available subscription:

1. **OpenRouter** (priority 0) — one key, many models
2. **Special connectors** (priority 1) — Codex CLI, Oracle browser, Kimi Coding Plan
3. **Direct API** (priority 2) — provider-specific keys (Z.ai, Anthropic, etc.)

### Model catalog

The model catalog (`data/model_catalog.yaml`) defines capabilities grounded in 2026 benchmarks:

| Model | Provider | Capabilities | Top Benchmark |
|---|---|---|---|
| `gpt-5.5` | OpenAI | coding, reasoning, general, math | DeepSWE #1 (69.2%), LiveBench #1 (80.71) |
| `gpt-5.5-pro` | OpenAI | reasoning, coding | ARC-AGI-1 #1 (96.5%) |
| `claude-opus-4.6` | Anthropic | reasoning, general, creative_writing, coding, agentic | SWE-bench #4 (75.6%), Arena #4 |
| `claude-sonnet-4.6` | Anthropic | general, coding | Cost-effective all-rounder |
| `gemini-3-pro` | Google | general, creative_writing | Arena Creative Writing #4 |
| `glm-5.2` | ZHIPU | coding, general | LiveBench Coding 79.65 |
| `kimi-k2.7-code` | Moonshot | coding | Kimi Coding Plan specialist |

### Task profiles

The catalog now separates **model capabilities** from **task profiles**. Task profiles describe real work categories and map them to capability combinations + model mixes. The current catalog includes 32 profiles across:

- Architecture: `system_architecture`, `process_architecture`, `cloud_architecture`, `network_infrastructure`
- Development: `frontend_development`, `backend_development`, `ui_ux_design`
- Growth/marketing: `copywriting`, `conversion_optimization`, `strategy_positioning`, `ads_creative`
- Analytics/tracking: `data_analysis`, `conversion_tracking_setup`
- Paid media: `google_ads`, `meta_ads`, `bing_ads`, `tiktok_ads`
- Organic social: `linkedin_social`, `x_social`, `instagram_social`, `tiktok_social`, `youtube_social`, `facebook_social`, `pinterest_social`, `reddit_social`, `threads_social`, `bluesky_social`
- Editorial/research: `editorial_planning`, `journalistic_research`, `scientific_research`, `osint`, `market_research_forums`

Task profiles are deliberately marked with `evidence_level`. Benchmarked capabilities stay separate from heuristic domain profiles, so Helmrail does not pretend there is a public leaderboard for things like Google Ads account structure or Meta creative strategy.

Task-profile route plans now include orchestration metadata:

- `capability_weights` — normalized capability mix for the task (explicit per profile when curated, derived otherwise)
- `tool_affinity` — descriptive integration/tool needs such as `google_ads_api`, `browser_devtools`, `repo_inspection`, or `reddit_search`
- `orchestration_steps` — plan-only execution graph (`scope`, `produce`, `fallback_produce`, `verify`, `parallel_candidate`, `synthesize`, etc.) with resolved model workers

These fields are intentionally side-effect-free. They describe how a future `/v1/orchestrations/run` endpoint should execute; `/v1/router/plan` still only plans.

### Policy modes

```text
POST /v1/router/plan
{"prompt":"Fix a failing Python test and produce a patch."}
```

| Task type | Mode | Primary | Fallback | Verifier |
|---|---|---|---|---|
| `default` | `direct` | `gpt-5.5` | `claude-opus-4.6`, `gemini-3-pro` | — |
| `coding` | `worker_verifier` | `gpt-5.5` | `kimi-k2.7-code` | `claude-opus-4.6` |
| `reasoning` | `worker_verifier` | `gpt-5.5-pro` | `claude-opus-4.6` | `gpt-5.5` |
| `creative_writing` | `direct` | `claude-opus-4.6` | `gemini-3-pro`, `gpt-5.5` | — |
| `fast` | `race` | `glm-5.2`, `kimi-k2.7-code`, `claude-sonnet-4.6` | — | — |
| `cheap` | `direct` | `glm-5.2` | `kimi-k2.7-code`, `claude-sonnet-4.6` | — |
| `high_confidence` | `compare` | `gpt-5.5`, `claude-opus-4.6`, `glm-5.2` | — | `gpt-5.5-pro` |

### Endpoints

- `GET /v1/router/catalog` — list models, capabilities, and benchmark sources
- `GET /v1/router/policies` — list routing policies (model-level)
- `POST /v1/router/plan` — get a routing plan for a prompt

## Test through Hermes

A local Hermes custom provider can point at Helmrail's OpenAI-compatible endpoint:

```yaml
providers:
  helmrail:
    name: Helmrail Local
    base_url: http://127.0.0.1:8765/v1
    key_env: HELMRAIL_API_KEY
    api_mode: chat_completions
    model: helmrail-coordinator
    models:
      helmrail-coordinator: {context_length: 128000}
      helmrail-auto: {context_length: 128000}
      helmrail-ultra: {context_length: 128000}
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

```text
POST /v1/responses
Authorization: Bearer test-token
{"model":"helmrail-fast","input":"Hello"}
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
