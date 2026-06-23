from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "helmrail-test.sqlite")))
    return TestClient(app)


def test_root_landing_page(tmp_path):
    c = client(tmp_path)
    response = c.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Helmrail API" in response.text
    assert "/setup" in response.text
    assert "/health" in response.text


def test_health(tmp_path):
    c = client(tmp_path)
    response = c.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["service"] == "helmrail"


def test_models(tmp_path):
    c = client(tmp_path)
    response = c.get("/v1/models")
    assert response.status_code == 200
    model_ids = [model["id"] for model in response.json()["data"]]
    assert "helmrail-fast" in model_ids
    assert "helmrail-ultra" in model_ids


def test_subscriptions_page(tmp_path):
    c = client(tmp_path)
    response = c.get("/subscriptions")
    assert response.status_code == 200
    assert "Subscriptions" in response.text
    assert "/v1/subscriptions" in response.text


def test_setup_page_and_provider_presets(tmp_path):
    c = client(tmp_path)
    response = c.get("/setup")
    assert response.status_code == 200
    assert "OpenAI Subscription / Codex CLI" in response.text
    assert "GPT-5.5 Pro Oracle" in response.text
    assert "no OpenAI key field" in response.text
    assert "Paste an OpenAI API key" not in response.text
    presets = c.get("/v1/provider-presets")
    assert presets.status_code == 200
    body = presets.json()["data"]
    labels = [preset["label"] for preset in body]
    assert "OpenAI Subscription / Codex CLI" in labels
    assert "GPT-5.5 Pro / Oracle browser" in labels
    assert "Z.ai Coding Plan" in labels
    assert "Kimi Coding Plan" in labels
    assert "MiniMax Coding Plan" in labels
    assert "Anthropic API" in labels
    assert "Google Gemini API" in labels
    assert "OpenRouter" in labels
    openai = next(preset for preset in body if preset["id"] == "openai_codex_cli")
    assert openai["connector_type"] == "codex_cli"
    assert openai["requires_api_key"] is False
    assert openai["key_policy"] == "forbidden"


def test_subscription_registry_crud_and_model_alias(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_PROVIDER_KEY", "not-real")

    created = c.post(
        "/v1/subscriptions",
        json={
            "provider": "Anthropic",
            "account_label": "Peter Anthropic API",
            "plan": "Claude API",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_PROVIDER_KEY",
            "model_aliases": ["claude-test"],
        },
    )
    assert created.status_code == 200
    body = created.json()
    subscription = body["data"]
    assert subscription["provider"] == "anthropic"
    assert body["probe"]["ok"] is True
    assert body["probe"]["status"] == "ready"

    listed = c.get("/v1/subscriptions")
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == subscription["id"]

    models = c.get("/v1/models").json()["data"]
    assert "claude-test" in [model["id"] for model in models]

    probe = c.post(f"/v1/subscriptions/{subscription['id']}/probe")
    assert probe.status_code == 200
    assert probe.json()["data"]["status"] == "ready"

    deleted = c.delete(f"/v1/subscriptions/{subscription['id']}")
    assert deleted.status_code == 200
    assert c.get("/v1/subscriptions").json()["data"] == []


def test_local_api_key_is_masked_and_codex_dry_run_routes(tmp_path):
    c = client(tmp_path)
    created = c.post(
        "/v1/subscriptions",
        json={
            "provider": "kimi",
            "account_label": "Kimi Coding Plan",
            "plan": "Kimi K2.7 Code",
            "connector_type": "api_key_local",
            "base_url": "https://api.moonshot.ai/v1",
            "api_key": "LOCAL_TEST_KEY_VALUE",
            "model_aliases": ["kimi-k2.7-code"],
            "metadata": {"api_style": "openai_compatible"},
        },
    )
    assert created.status_code == 200
    data = created.json()["data"]
    assert data["has_secret"] is True
    assert data["secret_preview"].startswith("LOCA")
    assert "LOCAL_TEST_KEY_VALUE" not in str(created.json())
    assert created.json()["probe"]["status"] == "ready"

    status = c.get("/v1/codex/status")
    assert status.status_code == 200
    assert status.json()["data"]["coding_providers"][0]["provider"] == "kimi"

    dry = c.post(
        "/v1/codex/run",
        json={"subscription_id": data["id"], "model": "kimi-k2.7-code", "prompt": "review this", "dry_run": True},
    )
    assert dry.status_code == 200
    assert dry.json()["dry_run"] is True
    assert dry.json()["ready"] is True
    assert dry.json()["route"]["model"] == "kimi-k2.7-code"


def test_openai_subscription_uses_codex_cli_without_api_key(tmp_path):
    c = client(tmp_path)
    rejected = c.post(
        "/v1/subscriptions",
        json={
            "provider": "openai",
            "account_label": "Wrong OpenAI API path",
            "connector_type": "api_key_local",
            "api_key": "sk-not-allowed",
        },
    )
    assert rejected.status_code == 422
    assert "Codex CLI" in rejected.json()["detail"]

    created = c.post(
        "/v1/subscriptions",
        json={
            "provider": "openai",
            "account_label": "OpenAI Subscription",
            "plan": "ChatGPT/Codex subscription",
            "connector_type": "codex_cli",
            "credential_ref": "python3",
            "model_aliases": ["gpt-5.5"],
            "metadata": {"api_style": "codex_cli"},
        },
    )
    assert created.status_code == 200
    data = created.json()["data"]
    assert data["provider"] == "openai"
    assert data["connector_type"] == "codex_cli"
    assert data["has_secret"] is False
    assert created.json()["probe"]["status"] == "ready"

    dry = c.post(
        "/v1/codex/run",
        json={"subscription_id": data["id"], "model": "gpt-5.5", "prompt": "dry only", "dry_run": True},
    )
    assert dry.status_code == 200
    assert dry.json()["ready"] is True
    assert dry.json()["route"]["connector_type"] == "codex_cli"


def test_oracle_status_and_dry_run_endpoint(tmp_path):
    c = client(tmp_path)
    status = c.get("/v1/oracle/status")
    assert status.status_code == 200
    assert "oracle_helper_available" in status.json()["data"]

    dry = c.post(
        "/v1/oracle/run",
        json={"model": "gpt-5.5-pro", "prompt": "second opinion", "dry_run": True},
    )
    assert dry.status_code == 200
    assert dry.json()["dry_run"] is True
    assert dry.json()["route"]["model"] == "gpt-5.5-pro"


def test_subscription_endpoints_require_auth_when_enabled(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "subscriptions-auth.sqlite"), api_key="secret", require_auth=True))
    c = TestClient(app)
    assert c.get("/subscriptions").status_code == 200
    assert c.get("/setup").status_code == 200
    assert c.get("/v1/subscriptions").status_code == 401
    assert c.get("/v1/codex/status").status_code == 401
    assert c.get("/v1/oracle/status").status_code == 401
    assert c.get("/v1/subscriptions", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_chat_completion_creates_trace_and_contribution_preview(tmp_path):
    c = client(tmp_path)
    response = c.post(
        "/v1/chat/completions",
        json={
            "model": "helmrail-fast",
            "messages": [{"role": "user", "content": "Contact peter@example.com with token=not-a-real-test-token"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["role"] == "assistant"
    run_id = body["helmrail_trace_id"]
    assert response.headers["X-Helmrail-Trace-Id"] == run_id

    traces = c.get("/v1/traces").json()["data"]
    assert traces[0]["run_id"] == run_id

    preview = c.post("/v1/contributions/preview", json={"run_id": run_id})
    assert preview.status_code == 200
    preview_text = str(preview.json())
    assert "peter@example.com" not in preview_text
    assert "[EMAIL_REDACTED]" in preview_text
    assert "[SECRET_REDACTED]" in preview_text


def test_responses_endpoint(tmp_path):
    c = client(tmp_path)
    response = c.post("/v1/responses", json={"model": "helmrail-ultra", "input": "Say hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert "output_text" in body


def test_optional_auth(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "auth.sqlite"), api_key="secret", require_auth=True))
    c = TestClient(app)
    assert c.post("/v1/responses", json={"input": "x"}).status_code == 401
    assert c.post("/v1/responses", headers={"Authorization": "Bearer secret"}, json={"input": "x"}).status_code == 200
