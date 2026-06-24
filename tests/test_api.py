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
    assert c.get("/v1/router/policies").status_code == 401
    assert c.get("/v1/router/catalog").status_code == 401
    assert c.post("/v1/router/plan", json={"prompt": "hi"}).status_code == 401
    assert c.get("/v1/subscriptions", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/v1/router/policies", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/v1/router/catalog", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_router_plan_selects_coding_worker_verifier_flow(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_KIMI_KEY", "local-test-key")
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "local-test-key")
    monkeypatch.setenv("TEST_ZAI_KEY", "local-test-key")

    for payload in [
        {
            "provider": "openai",
            "account_label": "OpenAI Subscription via Codex CLI",
            "connector_type": "codex_cli",
            "credential_ref": "python3",
            "model_aliases": ["helmrail-codex", "gpt-5.5"],
            "metadata": {"api_style": "codex_cli"},
        },
        {
            "provider": "kimi",
            "account_label": "Kimi Coding Plan",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_KIMI_KEY",
            "base_url": "https://api.kimi.com/coding/v1",
            "model_aliases": ["helmrail-kimi", "kimi-k2.7-code"],
            "metadata": {
                "api_style": "openai_compatible",
                "upstream_model": "kimi-k2.7-code",
                "model_alias_map": {"helmrail-kimi": "kimi-k2.7-code"},
            },
        },
        {
            "provider": "openrouter",
            "account_label": "OpenRouter API",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_OPENROUTER_KEY",
            "base_url": "https://openrouter.ai/api/v1",
            "model_aliases": ["helmrail-openrouter"],
            "metadata": {
                "api_style": "openai_compatible",
                "upstream_model": "openrouter/auto",
                "model_alias_map": {"helmrail-openrouter": "openrouter/auto"},
            },
        },
        {
            "provider": "zai",
            "account_label": "Z.ai Coding Plan",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_ZAI_KEY",
            "base_url": "https://api.z.ai/api/coding/paas/v4",
            "model_aliases": ["helmrail-zai"],
            "metadata": {
                "api_style": "openai_compatible",
                "upstream_model": "glm-5.2",
                "model_alias_map": {"helmrail-zai": "glm-5.2"},
            },
        },
    ]:
        assert c.post("/v1/subscriptions", json=payload).status_code == 200

    plan = c.post("/v1/router/plan", json={"prompt": "Fix this Python bug and produce a patch."})
    assert plan.status_code == 200
    body = plan.json()
    assert body["object"] == "router.plan"
    assert body["task_type"] == "coding"
    assert body["mode"] == "worker_verifier"
    assert body["ready"] is True
    # Policies refer model IDs, not subscription aliases
    assert body["selected_worker"]["model_id"] == "gpt-5.5"
    # OpenRouter should be preferred (priority 0) over Codex (priority 1)
    assert body["selected_worker"]["route_via"] == "openrouter"
    workers = {(worker["role"], worker["model_id"]): worker for worker in body["workers"]}
    # kimi-k2.7-code resolved via OpenRouter (priority 0), so upstream is prefixed
    assert workers[("fallback_worker", "kimi-k2.7-code")]["route_via"] == "openrouter"
    assert "kimi-k2.7-code" in workers[("fallback_worker", "kimi-k2.7-code")]["upstream_model"]
    assert workers[("verifier", "claude-opus-4.6")]["route_via"] == "openrouter"
    assert plan.headers["X-Helmrail-Trace-Id"] == body["trace_id"]


def test_router_plan_fast_mode_races_ready_api_workers(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_KIMI_KEY", "local-test-key")
    monkeypatch.setenv("TEST_ZAI_KEY", "local-test-key")
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "local-test-key")
    for payload in [
        {
            "provider": "kimi",
            "account_label": "Kimi Coding Plan",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_KIMI_KEY",
            "base_url": "https://api.kimi.com/coding/v1",
            "model_aliases": ["helmrail-kimi"],
            "metadata": {"api_style": "openai_compatible", "upstream_model": "kimi-k2.7-code"},
        },
        {
            "provider": "zai",
            "account_label": "Z.ai Coding Plan",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_ZAI_KEY",
            "base_url": "https://api.z.ai/api/coding/paas/v4",
            "model_aliases": ["helmrail-zai"],
            "metadata": {"api_style": "openai_compatible", "upstream_model": "glm-5.2"},
        },
        {
            "provider": "openrouter",
            "account_label": "OpenRouter API",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_OPENROUTER_KEY",
            "base_url": "https://openrouter.ai/api/v1",
            "model_aliases": ["helmrail-openrouter"],
            "metadata": {"api_style": "openai_compatible", "upstream_model": "openrouter/auto"},
        },
    ]:
        assert c.post("/v1/subscriptions", json=payload).status_code == 200

    plan = c.post("/v1/router/plan", json={"task_type": "fast", "prompt": "quick summary"})
    assert plan.status_code == 200
    body = plan.json()
    assert body["task_type"] == "fast"
    assert body["mode"] == "race"
    # Candidates are model IDs, not aliases
    assert body["selected_worker"]["model_id"] == "glm-5.2"
    candidate_models = [worker["model_id"] for worker in body["workers"] if worker["role"] == "candidate"]
    assert candidate_models == ["glm-5.2", "kimi-k2.7-code", "claude-sonnet-4.6"]


def test_router_catalog_exposes_task_profiles(tmp_path):
    c = client(tmp_path)
    response = c.get("/v1/router/catalog")
    assert response.status_code == 200
    body = response.json()
    profile_ids = {profile["id"] for profile in body["task_profiles"]}
    assert "system_architecture" in profile_ids
    assert "conversion_tracking_setup" in profile_ids
    assert "google_ads" in profile_ids
    assert "meta_ads" in profile_ids
    assert "linkedin_social" in profile_ids
    assert "scientific_research" in profile_ids
    assert "market_research_forums" in profile_ids
    assert "growth_marketing" in body["capability_taxonomy"]
    assert len(profile_ids) >= 30


def test_router_auto_classifies_domain_task_profiles(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "local-test-key")
    assert c.post(
        "/v1/subscriptions",
        json={
            "provider": "openrouter",
            "account_label": "OpenRouter API",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_OPENROUTER_KEY",
            "base_url": "https://openrouter.ai/api/v1",
            "model_aliases": ["helmrail-openrouter"],
            "metadata": {"api_style": "openai_compatible", "upstream_model": "openrouter/auto"},
        },
    ).status_code == 200

    cases = [
        ("Bitte erstelle eine Google Ads Keyword Strategie mit RSA Ideen.", "google_ads", "paid_media"),
        ("Wir brauchen ein UI/UX Konzept für die neue Checkout-Seite.", "ui_ux_design", "design"),
        ("Plane organischen LinkedIn Content für B2B Founder.", "linkedin_social", "organic_social"),
        ("Mach Market Research in Reddit und Foren zu diesem Problem.", "market_research_forums", "research"),
    ]
    for prompt, expected_task, expected_domain in cases:
        response = c.post("/v1/router/plan", json={"prompt": prompt})
        assert response.status_code == 200
        body = response.json()
        assert body["task_type"] == expected_task
        assert body["task_profile"]["id"] == expected_task
        assert body["task_profile"]["domain"] == expected_domain
        assert body["ready"] is True
        assert body["selected_worker"]["route_via"] == "openrouter"


def test_router_explicit_profile_for_conversion_tracking(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "local-test-key")
    assert c.post(
        "/v1/subscriptions",
        json={
            "provider": "openrouter",
            "account_label": "OpenRouter API",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_OPENROUTER_KEY",
            "base_url": "https://openrouter.ai/api/v1",
            "model_aliases": ["helmrail-openrouter"],
            "metadata": {"api_style": "openai_compatible", "upstream_model": "openrouter/auto"},
        },
    ).status_code == 200

    response = c.post(
        "/v1/router/plan",
        json={"task_type": "conversion_tracking_setup", "prompt": "GA4 + GTM + Meta Pixel sauber einrichten"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task_type"] == "conversion_tracking_setup"
    assert body["mode"] == "worker_verifier"
    assert body["policy"]["required_capabilities"] == ["conversion_tracking_setup", "analytics_instrumentation", "coding"]
    assert [worker["model_id"] for worker in body["workers"]] == ["gpt-5.5", "kimi-k2.7-code", "claude-opus-4.6"]


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


def test_chat_completion_routes_linked_openai_compatible_provider(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_KIMI_KEY", "local-test-key")
    created = c.post(
        "/v1/subscriptions",
        json={
            "provider": "kimi",
            "account_label": "Kimi Coding Plan",
            "plan": "Kimi K2.7 Code",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_KIMI_KEY",
            "base_url": "https://api.moonshot.ai/v1",
            "model_aliases": ["helmrail-kimi", "kimi-k2.7-code"],
            "metadata": {
                "api_style": "openai_compatible",
                "upstream_model": "kimi-k2.7-code",
                "model_alias_map": {"helmrail-kimi": "kimi-k2.7-code"},
            },
        },
    )
    assert created.status_code == 200

    calls = []

    def fake_forward(*, subscription, api_key, payload, upstream_model, timeout=120):
        calls.append({"subscription": subscription, "api_key": api_key, "payload": payload, "upstream_model": upstream_model})
        return {
            "ok": True,
            "status_code": 200,
            "provider": subscription["provider"],
            "upstream_model": upstream_model,
            "raw": {
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "created": 1760000000,
                "model": upstream_model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "PONG"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        }

    monkeypatch.setattr("app.main.openai_compatible_chat_completion", fake_forward)
    response = c.post(
        "/v1/chat/completions",
        json={
            "model": "helmrail-kimi",
            "messages": [{"role": "user", "content": "Say PONG only"}],
            "temperature": 0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "PONG"
    assert body["helmrail_route"]["provider"] == "kimi"
    assert body["helmrail_route"]["upstream_model"] == "kimi-k2.7-code"
    assert calls[0]["api_key"] == "local-test-key"
    assert calls[0]["payload"]["model"] == "helmrail-kimi"
    assert calls[0]["upstream_model"] == "kimi-k2.7-code"


def test_chat_completion_rejects_native_provider_alias(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "local-test-key")
    created = c.post(
        "/v1/subscriptions",
        json={
            "provider": "anthropic",
            "account_label": "Anthropic API",
            "plan": "Claude API",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_ANTHROPIC_KEY",
            "base_url": "https://api.anthropic.com",
            "model_aliases": ["helmrail-claude"],
            "metadata": {"api_style": "anthropic_native", "upstream_model": "claude-sonnet-4.6"},
        },
    )
    assert created.status_code == 200
    response = c.post(
        "/v1/chat/completions",
        json={"model": "helmrail-claude", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 501
    assert "OpenAI-compatible" in response.json()["detail"]


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
