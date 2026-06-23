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
    assert "/docs" in response.text
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


def test_subscription_registry_crud_and_model_alias(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setenv("TEST_PROVIDER_KEY", "not-real")

    created = c.post(
        "/v1/subscriptions",
        json={
            "provider": "OpenAI",
            "account_label": "Peter ChatGPT Pro",
            "plan": "ChatGPT Pro",
            "connector_type": "api_key_env",
            "credential_ref": "TEST_PROVIDER_KEY",
            "model_aliases": ["gpt-5.5-pro"],
        },
    )
    assert created.status_code == 200
    body = created.json()
    subscription = body["data"]
    assert subscription["provider"] == "openai"
    assert body["probe"]["ok"] is True
    assert body["probe"]["status"] == "ready"

    listed = c.get("/v1/subscriptions")
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == subscription["id"]

    models = c.get("/v1/models").json()["data"]
    assert "gpt-5.5-pro" in [model["id"] for model in models]

    probe = c.post(f"/v1/subscriptions/{subscription['id']}/probe")
    assert probe.status_code == 200
    assert probe.json()["data"]["status"] == "ready"

    deleted = c.delete(f"/v1/subscriptions/{subscription['id']}")
    assert deleted.status_code == 200
    assert c.get("/v1/subscriptions").json()["data"] == []


def test_subscription_endpoints_require_auth_when_enabled(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "subscriptions-auth.sqlite"), api_key="secret", require_auth=True))
    c = TestClient(app)
    assert c.get("/subscriptions").status_code == 200
    assert c.get("/v1/subscriptions").status_code == 401
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
