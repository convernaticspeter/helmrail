from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .config import Settings
from .connectors import (
    api_style_for,
    codex_cli_ready,
    codex_cli_run,
    codex_status,
    openai_compatible_chat,
    openai_compatible_chat_completion,
    oracle_status,
    pro_oracle_run,
    public_presets,
    resolve_secret,
)
from .redaction import redact_json, redact_text
from .store import TraceStore
from .ui import setup_page


ConnectorType = Literal["api_key_local", "api_key_env", "browser_profile", "oauth", "codex_cli", "oracle_browser", "manual"]


class ContributionPreviewRequest(BaseModel):
    run_id: str = Field(..., description="Local Helmrail trace id")


class SubscriptionCreate(BaseModel):
    provider: str = Field(..., min_length=2, max_length=64, description="Provider name, e.g. openai, anthropic, google")
    account_label: str = Field(..., min_length=1, max_length=120, description="Human-readable account name")
    plan: str = Field(default="", max_length=120, description="Subscription/plan label, e.g. ChatGPT Pro")
    connector_type: ConnectorType = Field(..., description="How Helmrail can use this subscription")
    credential_ref: str = Field(
        default="",
        max_length=500,
        description="Reference only: env var name, browser profile path, OAuth subject, CLI command, or manual note.",
    )
    base_url: str = Field(default="", max_length=500, description="Provider API base URL, if applicable")
    api_key: str = Field(default="", max_length=5000, description="Optional local API key. Stored locally and never returned.")
    enabled: bool = True
    model_aliases: list[str] = Field(default_factory=list, description="Model aliases exposed through Helmrail")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubscriptionUpdate(BaseModel):
    provider: str | None = Field(default=None, min_length=2, max_length=64)
    account_label: str | None = Field(default=None, min_length=1, max_length=120)
    plan: str | None = Field(default=None, max_length=120)
    connector_type: ConnectorType | None = None
    credential_ref: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=5000)
    enabled: bool | None = None
    status: str | None = Field(default=None, max_length=80)
    model_aliases: list[str] | None = None
    metadata: dict[str, Any] | None = None


class CodexRunRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=20000)
    subscription_id: str | None = None
    model: str = Field(default="", max_length=200)
    system_prompt: str = Field(
        default="You are Codex inside Helmrail. Focus on practical software engineering output: concise diagnosis, patch-ready steps, and code when useful.",
        max_length=4000,
    )
    dry_run: bool = False


class OracleRunRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=20000)
    model: str = Field(default="gpt-5.5-pro", max_length=200)
    wait_seconds: int = Field(default=45, ge=0, le=900)
    dry_run: bool = False


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            return str(content)
    return ""


def _prototype_answer(prompt: str) -> str:
    clean = redact_text(prompt).strip()
    preview = clean[:700] if clean else "(empty input)"
    return (
        "Helmrail prototype response. No upstream worker is configured in this build yet; "
        "this API is currently proving the OpenAI-compatible surface, local trace store, "
        "and anonymized contribution pipeline.\n\n"
        f"Received input preview: {preview}"
    )


def _subscription_for_model(store: TraceStore, requested_model: str) -> dict[str, Any] | None:
    subscriptions = [item for item in store.list_subscriptions() if item["enabled"]]
    for subscription in subscriptions:
        if requested_model in subscription["model_aliases"]:
            return subscription

    if requested_model in {"helmrail-fast", "helmrail-ultra"}:
        runnable = [
            item
            for item in subscriptions
            if api_style_for(item) == "openai_compatible"
            and item["connector_type"] in {"api_key_env", "api_key_local"}
        ]
        runnable.sort(key=lambda item: int((item.get("metadata") or {}).get("helmrail_priority", 100)))
        return runnable[0] if runnable else None

    return None


def _upstream_model_for(subscription: dict[str, Any], requested_model: str) -> str:
    metadata = subscription.get("metadata") or {}
    alias_map = metadata.get("model_alias_map") if isinstance(metadata, dict) else None
    if isinstance(alias_map, dict):
        mapped = alias_map.get(requested_model)
        if isinstance(mapped, str) and mapped.strip():
            return mapped.strip()
    upstream = metadata.get("upstream_model") if isinstance(metadata, dict) else None
    if isinstance(upstream, str) and upstream.strip() and requested_model.startswith("helmrail-"):
        return upstream.strip()
    return requested_model


def _safe_route(subscription: dict[str, Any], upstream_model: str) -> dict[str, Any]:
    return {
        "subscription_id": subscription["id"],
        "provider": subscription["provider"],
        "account_label": subscription["account_label"],
        "connector_type": subscription["connector_type"],
        "api_style": api_style_for(subscription),
        "base_url": subscription["base_url"],
        "upstream_model": upstream_model,
    }


def _require_auth(settings: Settings):
    async def dependency(authorization: str | None = Header(default=None)) -> None:
        if not settings.require_auth:
            return
        expected = f"Bearer {settings.api_key}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="Missing or invalid bearer token")

    return dependency


def _probe_subscription(subscription: dict[str, Any]) -> dict[str, Any]:
    connector_type = subscription["connector_type"]
    credential_ref = subscription["credential_ref"].strip()
    base = {
        "id": subscription["id"],
        "provider": subscription["provider"],
        "account_label": subscription["account_label"],
        "connector_type": connector_type,
        "enabled": subscription["enabled"],
        "ok": False,
        "status": "not_ready",
        "message": "Connector is not ready.",
    }

    if not subscription["enabled"]:
        return {**base, "status": "disabled", "message": "Subscription is disabled."}

    if connector_type == "api_key_local":
        if subscription.get("has_secret"):
            return {**base, "ok": True, "status": "ready", "message": "A local API key is stored for this provider."}
        return {**base, "status": "missing_api_key", "message": "Paste an API key or switch to an env-var connector."}

    if connector_type == "api_key_env":
        if not credential_ref:
            return {**base, "status": "missing_credential_ref", "message": "Set credential_ref to the env var name that holds the API key."}
        if os.getenv(credential_ref):
            return {**base, "ok": True, "status": "ready", "message": f"Environment variable {credential_ref} is present."}
        return {**base, "status": "missing_env", "message": f"Environment variable {credential_ref} is not set in this Helmrail runtime."}

    if connector_type == "codex_cli":
        ready = codex_cli_ready(subscription)
        if ready["ok"]:
            return {**base, "ok": True, "status": "ready", "message": f"Codex CLI found at {ready['path']}."}
        return {**base, "status": "cli_not_found", "message": f"Codex CLI command not found: {ready['command']}"}

    if connector_type == "oracle_browser":
        status = oracle_status()
        ok = bool(status["oracle_helper_available"] and status["node24_available"] and status["oracle_cli_available"])
        missing = [name for name, present in (
            ("Hermes pro_oracle helper", status["oracle_helper_available"]),
            ("Node 24", status["node24_available"]),
            ("Oracle CLI", status["oracle_cli_available"]),
        ) if not present]
        return {
            **base,
            "ok": ok,
            "status": "ready" if ok else "oracle_not_ready",
            "message": "Oracle browser connector is available." if ok else "Missing: " + ", ".join(missing),
        }

    if connector_type == "browser_profile":
        if not credential_ref:
            return {**base, "status": "missing_profile", "message": "Set credential_ref to the browser profile path."}
        profile_path = Path(credential_ref).expanduser()
        if profile_path.exists():
            return {**base, "ok": True, "status": "ready", "message": "Browser profile path exists on this host."}
        return {**base, "status": "profile_not_found", "message": "Browser profile path does not exist on this host."}

    if connector_type == "oauth":
        oauth_connected = bool(subscription.get("metadata", {}).get("oauth_connected"))
        return {
            **base,
            "ok": oauth_connected,
            "status": "ready" if oauth_connected else "oauth_pending",
            "message": "OAuth connection is marked connected." if oauth_connected else "OAuth handshake is not implemented yet; this link is registered as pending.",
        }

    if connector_type == "manual":
        return {
            **base,
            "ok": bool(credential_ref),
            "status": "registered" if credential_ref else "missing_note",
            "message": "Manual subscription reference is registered." if credential_ref else "Add a manual reference/note so the subscription is identifiable.",
        }

    return {**base, "status": "unknown_connector", "message": f"Unsupported connector type: {connector_type}"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = TraceStore(settings.db_path)
    auth = _require_auth(settings)

    app = FastAPI(
        title="Helmrail API",
        version=settings.version,
        description="Self-hosted switchboard prototype for subscription/API-based model access.",
    )
    app.state.settings = settings
    app.state.store = store

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    def root() -> str:
        return f"""
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Helmrail API</title>
          <style>
            :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
            body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: radial-gradient(circle at top left, #27345f, #080b15 52%, #05060a); color: #eef3ff; }}
            main {{ width: min(760px, calc(100vw - 40px)); padding: 42px; border: 1px solid rgba(255,255,255,.14); border-radius: 28px; background: rgba(10,14,27,.72); box-shadow: 0 24px 90px rgba(0,0,0,.42); }}
            .eyebrow {{ color: #ffd057; text-transform: uppercase; letter-spacing: .16em; font-size: 12px; font-weight: 800; }}
            h1 {{ margin: 12px 0 14px; font-size: clamp(36px, 8vw, 72px); line-height: .92; }}
            p {{ color: #b8c2dc; font-size: 18px; line-height: 1.6; max-width: 620px; }}
            .status {{ display: inline-flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 999px; background: rgba(73, 255, 170, .1); color: #83ffc2; font-weight: 700; }}
            .dot {{ width: 10px; height: 10px; border-radius: 999px; background: #4dffa6; box-shadow: 0 0 20px #4dffa6; }}
            .links {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }}
            a {{ color: #08101f; background: #ffd057; text-decoration: none; font-weight: 800; padding: 13px 16px; border-radius: 14px; }}
            a.secondary {{ color: #eef3ff; background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.15); }}
            code {{ color: #ffd057; }}
          </style>
        </head>
        <body>
          <main>
            <div class="eyebrow">Self-hosted model switchboard</div>
            <h1>Helmrail API</h1>
            <div class="status"><span class="dot"></span> online · v{settings.version}</div>
            <p>
              Functional prototype for one OpenAI-compatible gateway across model subscriptions and APIs.
              This deployment currently proves routing surface, local traces, and contribution preview plumbing.
            </p>
            <p>Base URL: <code>http://127.0.0.1:8765</code></p>
            <div class="links">
              <a href="/setup">Setup Providers</a>
              <a class="secondary" href="/setup#codex">Codex Workbench</a>
              <a class="secondary" href="/subscriptions">Legacy Subscriptions</a>
              <a class="secondary" href="/health">Health</a>
              <a class="secondary" href="/v1/models">Models</a>
            </div>
          </main>
        </body>
        </html>
        """

    @app.get("/setup", response_class=HTMLResponse)
    def provider_setup_page() -> str:
        return setup_page()

    @app.get("/subscriptions", response_class=HTMLResponse)
    def subscriptions_page() -> str:
        return """
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Helmrail Subscriptions</title>
          <style>
            :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
            body { margin: 0; min-height: 100vh; background: #070a12; color: #eef3ff; }
            main { width: min(1080px, calc(100vw - 36px)); margin: 0 auto; padding: 38px 0 60px; }
            a { color: #ffd057; }
            h1 { margin: 8px 0 8px; font-size: clamp(34px, 7vw, 64px); letter-spacing: -.04em; }
            p { color: #b8c2dc; line-height: 1.6; }
            .eyebrow { color: #ffd057; text-transform: uppercase; letter-spacing: .16em; font-size: 12px; font-weight: 800; }
            .grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, 420px); gap: 18px; align-items: start; }
            .card { border: 1px solid rgba(255,255,255,.12); border-radius: 22px; padding: 22px; background: rgba(255,255,255,.055); box-shadow: 0 20px 60px rgba(0,0,0,.28); }
            label { display: grid; gap: 7px; margin-bottom: 12px; color: #ccd5ed; font-weight: 700; }
            input, select, textarea { width: 100%; box-sizing: border-box; border: 1px solid rgba(255,255,255,.16); background: rgba(0,0,0,.28); color: #eef3ff; border-radius: 12px; padding: 12px 13px; font: inherit; }
            textarea { min-height: 86px; resize: vertical; }
            button { border: 0; border-radius: 12px; padding: 11px 14px; background: #ffd057; color: #08101f; font-weight: 900; cursor: pointer; }
            button.secondary { background: rgba(255,255,255,.11); color: #eef3ff; border: 1px solid rgba(255,255,255,.14); }
            button.danger { background: rgba(255, 92, 92, .16); color: #ff9b9b; border: 1px solid rgba(255,92,92,.32); }
            .toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin: 18px 0; }
            .toolbar label { flex: 1 1 320px; margin: 0; }
            .subscriptions { display: grid; gap: 12px; }
            .sub { display: grid; gap: 10px; border: 1px solid rgba(255,255,255,.12); border-radius: 18px; padding: 16px; background: rgba(255,255,255,.04); }
            .sub-head { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
            .name { font-size: 20px; font-weight: 900; }
            .meta { color: #9da9c5; font-size: 14px; }
            .pill { display: inline-flex; width: fit-content; padding: 5px 9px; border-radius: 999px; background: rgba(255,255,255,.1); color: #ccd5ed; font-size: 12px; font-weight: 800; }
            .ready { background: rgba(73,255,170,.12); color: #83ffc2; }
            .warn { background: rgba(255,208,87,.12); color: #ffd057; }
            .actions { display: flex; flex-wrap: wrap; gap: 8px; }
            pre { white-space: pre-wrap; overflow-wrap: anywhere; background: rgba(0,0,0,.32); border-radius: 14px; padding: 12px; color: #dfe7fb; }
            @media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }
          </style>
        </head>
        <body>
          <main>
            <a href="/">← Helmrail</a>
            <div class="eyebrow">Connector registry</div>
            <h1>Subscriptions</h1>
            <p>Link the subscriptions and API accounts Helmrail may route through. The registry stores references, not raw secrets: use env var names, browser-profile paths, OAuth status, or manual notes.</p>
            <div class="toolbar card">
              <label>Admin API key
                <input id="apiKey" type="password" placeholder="Bearer token for protected Helmrail endpoints">
              </label>
              <button id="saveKey">Save locally</button>
              <button class="secondary" id="reload">Reload</button>
            </div>
            <div class="grid">
              <section class="card">
                <h2>Linked subscriptions</h2>
                <div id="subscriptions" class="subscriptions">Loading…</div>
              </section>
              <aside class="card">
                <h2>Add subscription</h2>
                <form id="form">
                  <label>Provider
                    <input name="provider" placeholder="zai, kimi, minimax, anthropic, google, openrouter" required>
                  </label>
                  <label>Account label
                    <input name="account_label" placeholder="Kimi Coding Plan" required>
                  </label>
                  <label>Plan
                    <input name="plan" placeholder="Coding plan or official API product">
                  </label>
                  <label>Connector type
                    <select name="connector_type" required>
                      <option value="api_key_env">API key via env var</option>
                      <option value="browser_profile">Browser profile / logged-in subscription</option>
                      <option value="oauth">OAuth account</option>
                      <option value="manual">Manual / not automated yet</option>
                    </select>
                  </label>
                  <label>Credential reference
                    <input name="credential_ref" placeholder="KIMI_API_KEY or /path/to/profile">
                  </label>
                  <label>Model aliases
                    <input name="model_aliases" placeholder="glm-5.2, kimi-k2.7-code, MiniMax-M3">
                  </label>
                  <label>Metadata JSON
                    <textarea name="metadata" placeholder='{"notes":"optional"}'></textarea>
                  </label>
                  <button type="submit">Link subscription</button>
                </form>
                <pre id="status"></pre>
              </aside>
            </div>
          </main>
          <script>
            const keyInput = document.getElementById('apiKey');
            const statusBox = document.getElementById('status');
            const list = document.getElementById('subscriptions');
            keyInput.value = localStorage.getItem('helmrail_api_key') || '';
            document.getElementById('saveKey').onclick = () => {
              localStorage.setItem('helmrail_api_key', keyInput.value.trim());
              statusBox.textContent = 'Saved locally in this browser.';
              load();
            };
            document.getElementById('reload').onclick = () => load();

            function headers() {
              const token = keyInput.value.trim();
              const h = {'Content-Type': 'application/json'};
              if (token) h.Authorization = 'Bearer ' + token;
              return h;
            }
            async function api(path, options = {}) {
              const res = await fetch(path, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
              const body = await res.json().catch(() => ({}));
              if (!res.ok) throw new Error((body && body.detail) || res.statusText);
              return body;
            }
            function escapeHtml(value) {
              return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
            }
            async function load() {
              try {
                const body = await api('/v1/subscriptions');
                const items = body.data || [];
                if (!items.length) {
                  list.innerHTML = '<p>No subscriptions linked yet.</p>';
                  return;
                }
                list.innerHTML = items.map(item => `
                  <article class="sub" data-id="${escapeHtml(item.id)}">
                    <div class="sub-head">
                      <div>
                        <div class="name">${escapeHtml(item.provider)} · ${escapeHtml(item.account_label)}</div>
                        <div class="meta">${escapeHtml(item.plan || 'no plan label')} · ${escapeHtml(item.connector_type)} · ${escapeHtml(item.credential_ref || 'no credential ref')}</div>
                      </div>
                      <span class="pill ${item.enabled ? 'ready' : 'warn'}">${item.enabled ? 'enabled' : 'disabled'}</span>
                    </div>
                    <div class="meta">Models: ${(item.model_aliases || []).map(escapeHtml).join(', ') || 'none yet'}</div>
                    <div class="actions">
                      <button class="secondary" onclick="probe('${item.id}')">Probe</button>
                      <button class="danger" onclick="removeSub('${item.id}')">Delete</button>
                    </div>
                  </article>`).join('');
              } catch (err) {
                list.innerHTML = '<p class="warn">' + escapeHtml(err.message) + '</p>';
              }
            }
            async function probe(id) {
              try { statusBox.textContent = JSON.stringify(await api('/v1/subscriptions/' + id + '/probe', {method:'POST'}), null, 2); }
              catch (err) { statusBox.textContent = err.message; }
            }
            async function removeSub(id) {
              if (!confirm('Delete this subscription link?')) return;
              try { await api('/v1/subscriptions/' + id, {method:'DELETE'}); await load(); }
              catch (err) { statusBox.textContent = err.message; }
            }
            window.probe = probe;
            window.removeSub = removeSub;
            document.getElementById('form').onsubmit = async (event) => {
              event.preventDefault();
              const fd = new FormData(event.target);
              let metadata = {};
              const metadataText = String(fd.get('metadata') || '').trim();
              if (metadataText) metadata = JSON.parse(metadataText);
              const payload = {
                provider: String(fd.get('provider') || '').trim(),
                account_label: String(fd.get('account_label') || '').trim(),
                plan: String(fd.get('plan') || '').trim(),
                connector_type: String(fd.get('connector_type') || '').trim(),
                credential_ref: String(fd.get('credential_ref') || '').trim(),
                model_aliases: String(fd.get('model_aliases') || '').split(',').map(s => s.trim()).filter(Boolean),
                metadata
              };
              try {
                statusBox.textContent = JSON.stringify(await api('/v1/subscriptions', {method:'POST', body: JSON.stringify(payload)}), null, 2);
                event.target.reset();
                await load();
              } catch (err) {
                statusBox.textContent = err.message;
              }
            };
            load();
          </script>
        </body>
        </html>
        """

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "helmrail",
            "version": settings.version,
            "mode": "prototype-wrapper",
            "trace_store": "sqlite",
            "auth_required": settings.require_auth,
        }

    @app.get("/v1/models")
    def models() -> dict[str, Any]:
        created = 1760000000
        data = [
            {
                "id": "helmrail-fast",
                "object": "model",
                "created": created,
                "owned_by": "helmrail",
                "description": "Prototype single-worker/router-compatible model alias.",
            },
            {
                "id": "helmrail-ultra",
                "object": "model",
                "created": created,
                "owned_by": "helmrail",
                "description": "Prototype conductor-compatible model alias.",
            },
        ]
        for subscription in store.list_subscriptions():
            if not subscription["enabled"]:
                continue
            for alias in subscription["model_aliases"]:
                data.append(
                    {
                        "id": alias,
                        "object": "model",
                        "created": created,
                        "owned_by": subscription["provider"],
                        "subscription_id": subscription["id"],
                        "connector_type": subscription["connector_type"],
                        "description": f"Linked subscription alias for {subscription['account_label']}.",
                    }
                )
        return {"object": "list", "data": data}

    @app.get("/v1/provider-presets")
    def provider_presets() -> dict[str, Any]:
        return {"object": "list", "data": public_presets()}

    @app.get("/v1/codex/status", dependencies=[Depends(auth)])
    def codex_status_endpoint() -> dict[str, Any]:
        subscriptions = store.list_subscriptions()
        coding_ready = []
        for item in subscriptions:
            if not item["enabled"]:
                continue
            style = api_style_for(item)
            if item["connector_type"] == "codex_cli":
                ready = codex_cli_ready(item)
                coding_ready.append(
                    {
                        "id": item["id"],
                        "provider": item["provider"],
                        "account_label": item["account_label"],
                        "api_style": style,
                        "connector_type": item["connector_type"],
                        "models": item["model_aliases"],
                        "ready": ready["ok"],
                        "command": ready["command"],
                        "path": ready["path"],
                    }
                )
            elif style == "openai_compatible":
                coding_ready.append(
                    {
                        "id": item["id"],
                        "provider": item["provider"],
                        "account_label": item["account_label"],
                        "api_style": style,
                        "connector_type": item["connector_type"],
                        "models": item["model_aliases"],
                        "ready": bool(resolve_secret(item, store.get_subscription_secret(item["id"]))),
                    }
                )
        return {"object": "codex.status", "data": {**codex_status(), "coding_providers": coding_ready}}

    @app.post("/v1/codex/run", dependencies=[Depends(auth)])
    def codex_run(request: CodexRunRequest, response: Response) -> dict[str, Any]:
        subscriptions = store.list_subscriptions()
        subscription = None
        if request.subscription_id:
            subscription = store.get_subscription(request.subscription_id)
        else:
            subscription = next(
                (
                    item
                    for item in subscriptions
                    if item["enabled"] and (item["connector_type"] == "codex_cli" or api_style_for(item) == "openai_compatible")
                ),
                None,
            )
        if subscription is None:
            raise HTTPException(status_code=404, detail="No matching provider subscription found")
        if not subscription["enabled"]:
            raise HTTPException(status_code=422, detail="Selected provider is disabled")

        model = request.model.strip() or (subscription["model_aliases"][0] if subscription["model_aliases"] else "")
        style = api_style_for(subscription)
        route = {
            "subscription_id": subscription["id"],
            "provider": subscription["provider"],
            "account_label": subscription["account_label"],
            "connector_type": subscription["connector_type"],
            "api_style": style,
            "base_url": subscription["base_url"],
            "model": model,
        }

        if subscription["connector_type"] == "codex_cli":
            ready = codex_cli_ready(subscription)
            if request.dry_run:
                return {
                    "object": "codex.run",
                    "dry_run": True,
                    "route": {**route, "command": ready["command"], "path": ready["path"]},
                    "ready": bool(ready["ok"] and model),
                    "message": "Dry run only: no Codex CLI process was started.",
                }
            if not ready["ok"]:
                raise HTTPException(status_code=422, detail=f"Codex CLI command not found: {ready['command']}")
            if not model:
                raise HTTPException(status_code=422, detail="Choose a Codex model")
            result = codex_cli_run(subscription=subscription, model=model, prompt=request.prompt)
            run_id = store.save_trace(
                endpoint="/v1/codex/run",
                model=model,
                input_payload={"subscription_id": subscription["id"], "provider": subscription["provider"], "model": model, "prompt": request.prompt},
                output_payload=result,
                metadata={
                    "router_family": "codex-cli",
                    "workflow_shape": "single-provider",
                    "worker_classes": ["coding"],
                    "success_signal": "codex_cli_ok" if result.get("ok") else "codex_cli_error",
                },
            )
            response.headers["X-Helmrail-Trace-Id"] = run_id
            return {"object": "codex.run", "trace_id": run_id, "route": route, "result": result}

        secret = resolve_secret(subscription, store.get_subscription_secret(subscription["id"]))
        if request.dry_run:
            return {
                "object": "codex.run",
                "dry_run": True,
                "route": route,
                "ready": bool(secret) and bool(model) and style == "openai_compatible",
                "message": "Dry run only: no provider call was made.",
            }
        if style != "openai_compatible":
            raise HTTPException(status_code=501, detail="Codex workbench currently runs Codex CLI or OpenAI-compatible API providers. This provider key is stored but needs a native runner.")
        if not secret:
            raise HTTPException(status_code=422, detail="Selected provider has no usable API key or env var")
        if not model:
            raise HTTPException(status_code=422, detail="Choose a model for this provider")

        result = openai_compatible_chat(
            subscription=subscription,
            api_key=secret,
            model=model,
            prompt=request.prompt,
            system_prompt=request.system_prompt,
        )
        run_id = store.save_trace(
            endpoint="/v1/codex/run",
            model=model,
            input_payload={
                "subscription_id": subscription["id"],
                "provider": subscription["provider"],
                "model": model,
                "prompt": request.prompt,
            },
            output_payload=result,
            metadata={
                "router_family": "codex-workbench",
                "workflow_shape": "single-provider",
                "worker_classes": ["coding"],
                "success_signal": "provider_ok" if result.get("ok") else "provider_error",
            },
        )
        response.headers["X-Helmrail-Trace-Id"] = run_id
        return {"object": "codex.run", "trace_id": run_id, "route": route, "result": result}

    @app.get("/v1/oracle/status", dependencies=[Depends(auth)])
    def oracle_status_endpoint() -> dict[str, Any]:
        return {"object": "oracle.status", "data": oracle_status()}

    @app.post("/v1/oracle/run", dependencies=[Depends(auth)])
    def oracle_run(request: OracleRunRequest, response: Response) -> dict[str, Any]:
        status = oracle_status()
        route = {"connector_type": "oracle_browser", "provider": "chatgpt", "model": request.model, "status": status}
        if request.dry_run:
            ready = bool(status["oracle_helper_available"] and status["node24_available"] and status["oracle_cli_available"])
            return {"object": "oracle.run", "dry_run": True, "route": route, "ready": ready, "message": "Dry run only: no Oracle browser run was started."}
        result = pro_oracle_run(prompt=request.prompt, model=request.model, wait_seconds=request.wait_seconds, cwd=os.getcwd())
        run_id = store.save_trace(
            endpoint="/v1/oracle/run",
            model=request.model,
            input_payload={"model": request.model, "prompt": request.prompt, "wait_seconds": request.wait_seconds},
            output_payload=result,
            metadata={
                "router_family": "oracle-browser",
                "workflow_shape": "single-browser-session",
                "worker_classes": ["reasoning"],
                "success_signal": "oracle_ok" if result.get("ok") else "oracle_error",
            },
        )
        response.headers["X-Helmrail-Trace-Id"] = run_id
        return {"object": "oracle.run", "trace_id": run_id, "route": route, "result": result}

    @app.get("/v1/subscriptions", dependencies=[Depends(auth)])
    def list_subscriptions() -> dict[str, Any]:
        subscriptions = store.list_subscriptions()
        return {"object": "list", "data": subscriptions}

    @app.post("/v1/subscriptions", dependencies=[Depends(auth)])
    def create_subscription(payload: SubscriptionCreate) -> dict[str, Any]:
        provider = payload.provider.strip().lower()
        api_key = payload.api_key.strip()
        if provider == "openai" and payload.connector_type != "codex_cli":
            raise HTTPException(status_code=422, detail="OpenAI subscriptions must be linked through the Codex CLI connector, not API-key entry.")
        if api_key and payload.connector_type in {"codex_cli", "oracle_browser"}:
            raise HTTPException(status_code=422, detail="This connector does not accept API keys.")
        subscription = store.create_subscription(
            provider=provider,
            account_label=payload.account_label.strip(),
            plan=payload.plan.strip(),
            connector_type=payload.connector_type,
            credential_ref=payload.credential_ref.strip(),
            base_url=payload.base_url.strip(),
            secret_value=api_key,
            enabled=payload.enabled,
            model_aliases=[alias.strip() for alias in payload.model_aliases if alias.strip()],
            metadata=payload.metadata,
        )
        return {"object": "subscription", "data": subscription, "probe": _probe_subscription(subscription)}

    @app.get("/v1/subscriptions/{subscription_id}", dependencies=[Depends(auth)])
    def get_subscription(subscription_id: str) -> dict[str, Any]:
        subscription = store.get_subscription(subscription_id)
        if subscription is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return {"object": "subscription", "data": subscription}

    @app.patch("/v1/subscriptions/{subscription_id}", dependencies=[Depends(auth)])
    def update_subscription(subscription_id: str, payload: SubscriptionUpdate) -> dict[str, Any]:
        changes = payload.model_dump(exclude_unset=True)
        if "api_key" in changes:
            changes["secret_value"] = str(changes.pop("api_key") or "")
        if "provider" in changes and isinstance(changes["provider"], str):
            changes["provider"] = changes["provider"].strip().lower()
        if changes.get("provider") == "openai" and changes.get("connector_type") not in {None, "codex_cli"}:
            raise HTTPException(status_code=422, detail="OpenAI subscriptions must be linked through the Codex CLI connector, not API-key entry.")
        if changes.get("secret_value") and changes.get("connector_type") in {"codex_cli", "oracle_browser"}:
            raise HTTPException(status_code=422, detail="This connector does not accept API keys.")
        for key in ("account_label", "plan", "credential_ref", "base_url", "status", "secret_value"):
            if key in changes and isinstance(changes[key], str):
                changes[key] = changes[key].strip()
        if "model_aliases" in changes and changes["model_aliases"] is not None:
            changes["model_aliases"] = [alias.strip() for alias in changes["model_aliases"] if alias.strip()]
        subscription = store.update_subscription(subscription_id, changes)
        if subscription is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return {"object": "subscription", "data": subscription, "probe": _probe_subscription(subscription)}

    @app.delete("/v1/subscriptions/{subscription_id}", dependencies=[Depends(auth)])
    def delete_subscription(subscription_id: str) -> dict[str, Any]:
        deleted = store.delete_subscription(subscription_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Subscription not found")
        return {"object": "subscription.deleted", "id": subscription_id, "deleted": True}

    @app.post("/v1/subscriptions/{subscription_id}/probe", dependencies=[Depends(auth)])
    def probe_subscription(subscription_id: str) -> dict[str, Any]:
        subscription = store.get_subscription(subscription_id)
        if subscription is None:
            raise HTTPException(status_code=404, detail="Subscription not found")
        probe = _probe_subscription(subscription)
        store.update_subscription(subscription_id, {"status": probe["status"]})
        return {"object": "subscription.probe", "data": probe}

    @app.post("/v1/chat/completions", dependencies=[Depends(auth)])
    def chat_completions(payload: dict[str, Any], response: Response) -> dict[str, Any]:
        if payload.get("stream"):
            raise HTTPException(status_code=400, detail="Streaming is not implemented in the prototype")
        model = str(payload.get("model") or "helmrail-fast")
        messages = payload.get("messages") or []
        if not isinstance(messages, list):
            raise HTTPException(status_code=422, detail="messages must be a list")

        subscription = _subscription_for_model(store, model)
        if subscription is not None:
            style = api_style_for(subscription)
            upstream_model = _upstream_model_for(subscription, model)
            route = _safe_route(subscription, upstream_model)
            if style != "openai_compatible":
                raise HTTPException(
                    status_code=501,
                    detail=f"Model {model} is linked to {style}, but /v1/chat/completions currently runs OpenAI-compatible API providers only.",
                )
            secret = resolve_secret(subscription, store.get_subscription_secret(subscription["id"]))
            if not secret:
                raise HTTPException(status_code=422, detail=f"Model {model} has no usable API key or env var")
            result = openai_compatible_chat_completion(
                subscription=subscription,
                api_key=secret,
                payload=payload,
                upstream_model=upstream_model,
            )
            run_id = store.save_trace(
                endpoint="/v1/chat/completions",
                model=model,
                input_payload={**payload, "_helmrail_route": route},
                output_payload=result,
                metadata={
                    "router_family": "openai-compatible-proxy",
                    "workflow_shape": "single-provider",
                    "worker_classes": ["chat"],
                    "success_signal": "provider_ok" if result.get("ok") else "provider_error",
                    "provider": subscription["provider"],
                    "upstream_model": upstream_model,
                },
            )
            response.headers["X-Helmrail-Trace-Id"] = run_id
            if not result.get("ok"):
                raise HTTPException(status_code=int(result.get("status_code") or 502), detail=result.get("error") or result)
            raw = result.get("raw")
            if not isinstance(raw, dict):
                raise HTTPException(status_code=502, detail="Provider returned a non-object chat completion payload")
            raw["helmrail_trace_id"] = run_id
            raw["helmrail_route"] = route
            return raw

        prompt = _last_user_text(messages)
        answer = _prototype_answer(prompt)
        created = int(time.time())
        completion_id = f"chatcmpl_{uuid4().hex}"
        output = {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "system_fingerprint": "helmrail-prototype-v0.1",
        }
        run_id = store.save_trace(
            endpoint="/v1/chat/completions",
            model=model,
            input_payload=payload,
            output_payload=output,
            metadata={
                "router_family": "prototype-deterministic",
                "workflow_shape": "single",
                "worker_classes": [],
                "success_signal": "unknown",
            },
        )
        response.headers["X-Helmrail-Trace-Id"] = run_id
        output["helmrail_trace_id"] = run_id
        return output

    @app.post("/v1/responses", dependencies=[Depends(auth)])
    def responses(payload: dict[str, Any], response: Response) -> dict[str, Any]:
        if payload.get("stream"):
            raise HTTPException(status_code=400, detail="Streaming is not implemented in the prototype")
        model = str(payload.get("model") or "helmrail-fast")
        raw_input = payload.get("input", "")
        prompt = raw_input if isinstance(raw_input, str) else str(raw_input)
        answer = _prototype_answer(prompt)
        created = int(time.time())
        response_id = f"resp_{uuid4().hex}"
        output = {
            "id": response_id,
            "object": "response",
            "created_at": created,
            "status": "completed",
            "model": model,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": answer}],
                }
            ],
            "output_text": answer,
        }
        run_id = store.save_trace(
            endpoint="/v1/responses",
            model=model,
            input_payload=payload,
            output_payload=output,
            metadata={
                "router_family": "prototype-deterministic",
                "workflow_shape": "single",
                "worker_classes": [],
                "success_signal": "unknown",
            },
        )
        response.headers["X-Helmrail-Trace-Id"] = run_id
        output["helmrail_trace_id"] = run_id
        return output

    @app.get("/v1/traces", dependencies=[Depends(auth)])
    def traces(limit: int = 25) -> dict[str, Any]:
        return {"object": "list", "data": store.list_traces(limit=limit)}

    @app.get("/v1/traces/{run_id}", dependencies=[Depends(auth)])
    def trace_detail(run_id: str) -> dict[str, Any]:
        trace = store.get_trace(run_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        return trace

    @app.post("/v1/contributions/preview", dependencies=[Depends(auth)])
    def contribution_preview(request: ContributionPreviewRequest) -> dict[str, Any]:
        trace = store.get_trace(request.run_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Trace not found")
        created_at = trace["created_at"]
        month_bucket = created_at[:7] if created_at else datetime.now(timezone.utc).strftime("%Y-%m")
        input_redacted = redact_json(trace["input"])
        output_redacted = redact_json(trace["output"])
        metadata = trace.get("metadata") or {}
        sample = {
            "schema_version": "0.1",
            "sample_id": f"sample_{uuid4().hex}",
            "created_at_bucket": month_bucket,
            "source": {
                "helmrail_version": settings.version,
                "contribution_mode": "manual-export-preview",
                "consent_version": "draft-0.1",
            },
            "task": {
                "category": "unknown",
                "language": "unknown",
                "sensitivity_after_redaction": "medium-review-required",
                "input_redacted": input_redacted,
            },
            "routing": {
                "router_family": metadata.get("router_family", "prototype-deterministic"),
                "worker_classes": metadata.get("worker_classes", []),
                "workflow_shape": metadata.get("workflow_shape", "single"),
            },
            "observations": {
                "latency_bucket": "unknown",
                "cost_bucket": "none",
                "tool_use_shape": "none",
                "success_signal": metadata.get("success_signal", "unknown"),
                "failure_mode": "unknown",
            },
            "outputs": {
                "output_redacted": output_redacted,
            },
            "warnings": [
                "Preview only: no data has been uploaded.",
                "Human review is required before contribution.",
            ],
        }
        return sample

    return app


app = create_app()
