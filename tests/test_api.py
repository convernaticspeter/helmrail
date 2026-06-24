import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _raw_chat(text, model="test"):
    return {
        "id": "chatcmpl_test",
        "object": "chat.completion",
        "created": 1760000000,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


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
    assert body["limits"]["max_output_tokens"] == 16384


def test_models(tmp_path):
    c = client(tmp_path)
    response = c.get("/v1/models")
    assert response.status_code == 200
    model_ids = [model["id"] for model in response.json()["data"]]
    assert "helmrail-fast" in model_ids
    assert "helmrail-ultra" in model_ids
    assert "helmrail-coordinator" in model_ids
    assert "helmrail-auto" in model_ids


def test_chat_completion_streaming_compatibility(tmp_path):
    c = client(tmp_path)
    response = c.post(
        "/v1/chat/completions",
        json={"model": "helmrail-fast", "messages": [{"role": "user", "content": "Say hi"}], "stream": True},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["X-Helmrail-Trace-Id"].startswith("run_")
    assert "chat.completion.chunk" in response.text
    assert "data: [DONE]" in response.text


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
    assert c.get("/v1/training-samples").status_code == 401
    assert c.get("/v1/training-exports/jsonl").status_code == 401
    assert c.get("/v1/training-preference-pairs").status_code == 401
    assert c.get("/v1/training-preference-exports/jsonl").status_code == 401
    assert c.post("/v1/training-samples/sample_missing/feedback", json={"outcome": "accepted"}).status_code == 401
    assert c.get("/v1/training-samples/sample_missing/preference-pairs").status_code == 401
    assert c.post("/v1/router/plan", json={"prompt": "hi"}).status_code == 401
    assert c.get("/v1/subscriptions", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/v1/router/policies", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/v1/router/catalog", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/v1/training-samples", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/v1/training-exports/jsonl", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/v1/training-preference-pairs", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/v1/training-preference-exports/jsonl", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.post(
        "/v1/training-samples/sample_missing/feedback",
        headers={"Authorization": "Bearer secret"},
        json={"outcome": "accepted"},
    ).status_code == 404
    assert c.get(
        "/v1/training-samples/sample_missing/preference-pairs",
        headers={"Authorization": "Bearer secret"},
    ).status_code == 404


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
    assert body["capability_weights"]["conversion_tracking_setup"] == 0.38
    assert body["capability_weights"]["analytics_instrumentation"] == 0.24
    assert "tag_manager" in body["tool_affinity"]
    assert "network_inspector" in body["tool_affinity"]
    assert [step["id"] for step in body["orchestration_steps"]] == ["scope", "produce", "fallback_produce", "verify"]
    assert body["orchestration_steps"][-1]["worker"]["model_id"] == "claude-opus-4.6"


def test_router_direct_profile_can_plan_review_step(tmp_path, monkeypatch):
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
        json={"task_type": "ui_ux_design", "prompt": "Audit this checkout UI/UX."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "direct"
    assert body["selected_worker"]["model_id"] == "claude-opus-4.6"
    assert [step["id"] for step in body["orchestration_steps"]] == ["execute", "review"]
    assert body["orchestration_steps"][1]["worker"]["role"] == "verifier"
    assert body["orchestration_steps"][1]["worker"]["model_id"] == "gpt-5.5-pro"
    assert body["capability_weights"]["ui_ux_design"] == 0.35
    assert "browser_qa" in body["tool_affinity"]
    assert "design_reference_search" in body["tool_affinity"]


def test_router_compare_profile_plans_parallel_candidates(tmp_path, monkeypatch):
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
        json={"task_type": "conversion_optimization", "prompt": "Run a CRO audit."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "compare"
    assert [step["type"] for step in body["orchestration_steps"]] == [
        "parallel_candidate",
        "parallel_candidate",
        "parallel_candidate",
        "parallel_candidate",
        "synthesis",
    ]
    assert body["orchestration_steps"][-1]["worker"]["role"] == "synthesizer"


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
    preview_body = preview.json()
    preview_text = str(preview_body)
    assert "peter@example.com" not in preview_text
    assert run_id not in preview_text
    assert "[EMAIL_REDACTED]" in preview_text
    assert "[SECRET_REDACTED]" in preview_text
    assert preview_body["source"]["contribution_mode"] == "local-auto-anonymized"
    assert preview_body["privacy"]["raw_trace_included"] is False
    assert preview_body["privacy"]["contains_local_run_id"] is False

    samples = c.get("/v1/training-samples").json()["data"]
    assert len(samples) == 1
    sample_id = samples[0]["sample_id"]
    detail = c.get(f"/v1/training-samples/{sample_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    detail_text = str(detail_body)
    assert "peter@example.com" not in detail_text
    assert run_id not in detail_text
    assert "[EMAIL_REDACTED]" in detail_text
    assert detail_body["sample"]["sample_id"] == sample_id

    feedback = c.post(
        f"/v1/training-samples/{sample_id}/feedback",
        json={
            "outcome": "user_corrected",
            "rating": 4,
            "corrected_output": "Use the corrected answer for peter@example.com with token=should-hide",
            "notes": "Useful but needed edit. Call +43 660 1234567 if unclear.",
            "metadata": {"reviewer_email": "reviewer@example.com"},
        },
    )
    assert feedback.status_code == 200
    feedback_body = feedback.json()
    feedback_text = str(feedback_body)
    assert feedback_body["outcome"] == "user_corrected"
    assert feedback_body["rating"] == 4
    assert "peter@example.com" not in feedback_text
    assert "reviewer@example.com" not in feedback_text
    assert "should-hide" not in feedback_text
    assert "+43 660 1234567" not in feedback_text
    assert "[EMAIL_REDACTED]" in feedback_text
    assert "[SECRET_REDACTED]" in feedback_text

    listed_feedback = c.get(f"/v1/training-samples/{sample_id}/feedback")
    assert listed_feedback.status_code == 200
    assert listed_feedback.json()["data"][0]["feedback_id"] == feedback_body["feedback_id"]

    updated_detail = c.get(f"/v1/training-samples/{sample_id}").json()
    updated_sample = updated_detail["sample"]
    assert updated_sample["feedback"]["labels"] == {
        "outcome": "user_corrected",
        "rating": 4,
        "has_correction": True,
    }
    updated_text = str(updated_sample)
    assert run_id not in updated_text
    assert "peter@example.com" not in updated_text
    assert "should-hide" not in updated_text

    export = c.get("/v1/training-exports/jsonl")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in export.text.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["sample_id"] == sample_id
    assert lines[0]["feedback"]["latest"]["outcome"] == "user_corrected"
    export_text = export.text
    assert run_id not in export_text
    assert "peter@example.com" not in export_text
    assert "should-hide" not in export_text
    assert "[EMAIL_REDACTED]" in export_text

    sample_pairs = c.get(f"/v1/training-samples/{sample_id}/preference-pairs")
    assert sample_pairs.status_code == 200
    pair_data = sample_pairs.json()["data"]
    assert len(pair_data) == 1
    assert pair_data[0]["source"] == "human_feedback"
    assert pair_data[0]["chosen"]["text"].startswith("Use the corrected")
    assert pair_data[0]["rejected"]["text"].startswith("Helmrail prototype response")

    all_pairs = c.get("/v1/training-preference-pairs")
    assert all_pairs.status_code == 200
    assert all_pairs.json()["data"][0]["pair_id"] == pair_data[0]["pair_id"]

    pair_export = c.get("/v1/training-preference-exports/jsonl")
    assert pair_export.status_code == 200
    assert pair_export.headers["content-type"].startswith("application/x-ndjson")
    pair_lines = [json.loads(line) for line in pair_export.text.splitlines() if line.strip()]
    assert len(pair_lines) == 1
    assert pair_lines[0]["source"] == "human_feedback"
    pair_export_text = pair_export.text
    assert run_id not in pair_export_text
    assert "peter@example.com" not in pair_export_text
    assert "should-hide" not in pair_export_text
    assert "[EMAIL_REDACTED]" in pair_export_text


def test_chat_completion_coordinator_behaves_like_model_and_collects_training_trace(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "local-test-key")
    created = c.post(
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
    )
    assert created.status_code == 200

    calls = []

    def fake_forward(*, subscription, api_key, payload, upstream_model, timeout=120):
        calls.append({"subscription": subscription, "api_key": api_key, "payload": payload, "upstream_model": upstream_model})
        system = payload["messages"][0]["content"]
        if "Coordinator Planner" in system:
            content = (
                '{"task_profile":"google_ads","mode":"worker_verifier","confidence":"high",'
                '"capabilities":["google_ads","conversion_optimization"],'
                '"tool_affinity":["google_ads_api","analytics_api"],'
                '"worker_instructions":[{"role":"worker","goal":"Create strategy","expected_output":"plan"}],'
                '"missing_context":["account data"],"rationale":"Google Ads task"}'
            )
        elif "quality verifier" in system:
            content = '{"approved": true, "confidence": 93, "issues": [], "suggestion": ""}'
        elif "Helmrail Coordinator" in system:
            content = "Hier ist die finalisierte Strategie basierend auf dem Worker-Output."
        else:
            content = "WORKER: Google Ads Strategie mit Kampagnenstruktur, Keywords und Landingpage-Hinweisen."
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
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        }

    monkeypatch.setattr("app.orchestration.openai_compatible_chat_completion", fake_forward)
    monkeypatch.setattr("app.engine.openai_compatible_chat_completion", fake_forward)
    response = c.post(
        "/v1/chat/completions",
        json={
            "model": "helmrail-coordinator",
            "messages": [{"role": "user", "content": "Erstelle eine Google Ads Strategie für peter@example.com token=abc123"}],
            "temperature": 0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "helmrail-coordinator"
    assert body["choices"][0]["message"]["content"].startswith("Hier ist die finalisierte")
    assert "helmrail_route" not in body
    assert "orchestration_steps" not in body
    assert len(calls) == 4
    assert calls[0]["api_key"] == "local-test-key"
    assert all(call["payload"]["max_tokens"] == 16384 for call in calls)
    assert calls[0]["upstream_model"] == "openai/gpt-5.5"

    run_id = response.headers["X-Helmrail-Trace-Id"]
    trace = c.get(f"/v1/traces/{run_id}").json()
    metadata = trace["metadata"]
    assert metadata["router_family"] == "llm-coordinator"
    assert metadata["workflow_shape"] == "fugu-style-executed-multi-agent-as-model"
    assert metadata["paper_alignment"]["sakana_fugu"].startswith("API-facing model")
    assert metadata["paper_alignment"]["deterministic_classifier"] is False
    assert metadata["paper_alignment"]["worker_execution"] is True
    assert metadata["coordinator_decision"]["task_profile"] == "google_ads"
    assert metadata["worker_plan"]["task_type"] == "google_ads"
    assert metadata["execution_result"]["mode"] == "worker_verifier"
    assert metadata["execution_result"]["success"] is True
    assert [obs["step_id"] for obs in metadata["execution_result"]["observations"]] == ["produce", "verify"]
    assert metadata["execution_result"]["selected_output"].startswith("WORKER:")
    assert metadata["training_intent"] == "future_coordinator_model"

    preview = c.post("/v1/contributions/preview", json={"run_id": run_id})
    assert preview.status_code == 200
    preview_body = preview.json()
    preview_text = str(preview_body)
    assert "peter@example.com" not in preview_text
    assert run_id not in preview_text
    assert "[EMAIL_REDACTED]" in preview_text
    assert "[SECRET_REDACTED]" in preview_text
    assert "future_coordinator_model" in preview_text
    assert preview_body["routing"]["workflow_shape"] == "fugu-style-executed-multi-agent-as-model"
    assert preview_body["execution"]["success"] is True
    assert preview_body["execution"]["selected_output_redacted"].startswith("WORKER:")
    assert preview_body["privacy"]["raw_trace_included"] is False


def test_coordinator_budget_cap_blocks_hidden_finalizer(tmp_path, monkeypatch):
    app = create_app(Settings(db_path=str(tmp_path / "budget.sqlite"), max_provider_calls=3, provider_timeout_seconds=19))
    c = TestClient(app)
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "local-test-key")
    created = c.post(
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
    )
    assert created.status_code == 200
    calls = []

    def fake_forward(*, subscription, api_key, payload, upstream_model, timeout=120):
        calls.append({"timeout": timeout, "upstream_model": upstream_model, "payload": payload, "system": payload["messages"][0]["content"]})
        system = payload["messages"][0]["content"]
        if "Coordinator Planner" in system:
            content = (
                '{"task_profile":"google_ads","mode":"worker_verifier","confidence":"high",'
                '"capabilities":["google_ads"],"tool_affinity":[],"worker_instructions":[],'
                '"missing_context":[],"rationale":"test"}'
            )
        elif "quality verifier" in system:
            content = '{"approved": true, "confidence": 90, "issues": [], "suggestion": ""}'
        else:
            content = "WORKER OUTPUT"
        return {
            "ok": True,
            "status_code": 200,
            "provider": subscription["provider"],
            "upstream_model": upstream_model,
            "raw": _raw_chat(content, upstream_model),
        }

    monkeypatch.setattr("app.orchestration.openai_compatible_chat_completion", fake_forward)
    monkeypatch.setattr("app.engine.openai_compatible_chat_completion", fake_forward)
    response = c.post(
        "/v1/chat/completions",
        json={"model": "helmrail-coordinator", "messages": [{"role": "user", "content": "Budget cap test"}]},
    )
    assert response.status_code == 429
    assert len(calls) == 3
    assert {call["timeout"] for call in calls} == {19}
    assert all(call["payload"]["max_tokens"] == 16384 for call in calls)
    run_id = response.headers["X-Helmrail-Trace-Id"]
    trace = c.get(f"/v1/traces/{run_id}").json()
    assert trace["metadata"]["budget"]["provider_calls_used"] == 3
    assert trace["metadata"]["budget"]["provider_calls_blocked"] == 1
    assert trace["metadata"]["budget"]["exhausted"] is True


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
            "max_tokens": 999999,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "PONG"
    assert body["helmrail_route"]["provider"] == "kimi"
    assert body["helmrail_route"]["upstream_model"] == "kimi-k2.7-code"
    assert calls[0]["api_key"] == "local-test-key"
    assert calls[0]["payload"]["model"] == "helmrail-kimi"
    assert calls[0]["payload"]["max_tokens"] == 16384
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
