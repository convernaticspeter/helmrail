from app.engine import execute_worker_plan


def _subscription(subscription_id="sub_openrouter"):
    return {
        "id": subscription_id,
        "provider": "openrouter",
        "account_label": "OpenRouter API",
        "connector_type": "api_key_env",
        "credential_ref": "TEST_OPENROUTER_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "enabled": True,
        "status": "ready",
        "metadata": {"api_style": "openai_compatible"},
    }


def _worker(role, model_id, subscription_id="sub_openrouter"):
    return {
        "role": role,
        "model_id": model_id,
        "subscription_id": subscription_id,
        "subscription_provider": "openrouter",
        "connector_type": "api_key_env",
        "api_style": "openai_compatible",
        "upstream_model": f"openrouter/{model_id}",
        "route_via": "openrouter",
        "ready": True,
        "status": "ready",
    }


def _raw(text):
    return {
        "id": "chatcmpl_test",
        "object": "chat.completion",
        "created": 1760000000,
        "model": "test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def test_engine_direct_executes_primary_and_optional_review(monkeypatch):
    calls = []

    def fake_forward(*, subscription, api_key, payload, upstream_model, timeout=120):
        calls.append({"payload": payload, "upstream_model": upstream_model, "api_key": api_key})
        system = payload["messages"][0].get("content", "") if payload.get("messages") else ""
        if "quality reviewer" in system:
            text = '{"approved": true, "confidence": 95, "issues": [], "improved_text": ""}'
        else:
            text = "PRIMARY OUTPUT"
        return {"ok": True, "status_code": 200, "provider": subscription["provider"], "upstream_model": upstream_model, "raw": _raw(text)}

    monkeypatch.setattr("app.engine.openai_compatible_chat_completion", fake_forward)
    result = execute_worker_plan(
        worker_plan={"mode": "direct", "workers": [_worker("primary", "gpt-5.5"), _worker("verifier", "claude-opus-4.6")]},
        messages=[{"role": "user", "content": "Do it"}],
        subscriptions=[_subscription()],
        get_secret=lambda _: "secret",
    )
    assert result["success"] is True
    assert result["selected_output"] == "PRIMARY OUTPUT"
    assert [obs["step_id"] for obs in result["observations"]] == ["execute", "review"]
    assert len(calls) == 2


def test_engine_worker_verifier_falls_back_when_primary_rejected(monkeypatch):
    call_no = {"n": 0}

    def fake_forward(*, subscription, api_key, payload, upstream_model, timeout=120):
        call_no["n"] += 1
        system = payload["messages"][0].get("content", "") if payload.get("messages") else ""
        if "quality verifier" in system and call_no["n"] == 2:
            text = '{"approved": false, "confidence": 20, "issues": ["bad"], "suggestion": "try fallback"}'
        elif "quality verifier" in system:
            text = '{"approved": true, "confidence": 91, "issues": [], "suggestion": ""}'
        elif call_no["n"] == 1:
            text = "BAD PRIMARY"
        else:
            text = "GOOD FALLBACK"
        return {"ok": True, "status_code": 200, "provider": subscription["provider"], "upstream_model": upstream_model, "raw": _raw(text)}

    monkeypatch.setattr("app.engine.openai_compatible_chat_completion", fake_forward)
    result = execute_worker_plan(
        worker_plan={
            "mode": "worker_verifier",
            "workers": [
                _worker("worker", "gpt-5.5"),
                _worker("fallback_worker", "kimi-k2.7-code"),
                _worker("verifier", "claude-opus-4.6"),
            ],
        },
        messages=[{"role": "user", "content": "Do it"}],
        subscriptions=[_subscription()],
        get_secret=lambda _: "secret",
    )
    assert result["success"] is True
    assert result["selected_output"] == "GOOD FALLBACK"
    assert [obs["step_id"] for obs in result["observations"]] == ["produce", "verify", "fallback_produce", "verify"]


def test_engine_race_returns_first_successful_candidate(monkeypatch):
    def fake_forward(*, subscription, api_key, payload, upstream_model, timeout=120):
        text = f"OUTPUT {upstream_model}"
        return {"ok": True, "status_code": 200, "provider": subscription["provider"], "upstream_model": upstream_model, "raw": _raw(text)}

    monkeypatch.setattr("app.engine.openai_compatible_chat_completion", fake_forward)
    result = execute_worker_plan(
        worker_plan={"mode": "race", "workers": [_worker("candidate", "glm-5.2"), _worker("candidate", "kimi-k2.7-code")]},
        messages=[{"role": "user", "content": "Fast answer"}],
        subscriptions=[_subscription()],
        get_secret=lambda _: "secret",
    )
    assert result["success"] is True
    assert result["selected_output"].startswith("OUTPUT openrouter/")
    assert len(result["observations"]) == 2
    assert result["winner"]["model_id"] in {"glm-5.2", "kimi-k2.7-code"}


def test_engine_compare_synthesizes_candidates(monkeypatch):
    def fake_forward(*, subscription, api_key, payload, upstream_model, timeout=120):
        system = payload["messages"][0].get("content", "") if payload.get("messages") else ""
        text = "SYNTHESIZED FINAL" if "synthesizer" in system else f"CANDIDATE {upstream_model}"
        return {"ok": True, "status_code": 200, "provider": subscription["provider"], "upstream_model": upstream_model, "raw": _raw(text)}

    monkeypatch.setattr("app.engine.openai_compatible_chat_completion", fake_forward)
    result = execute_worker_plan(
        worker_plan={
            "mode": "compare",
            "workers": [
                _worker("candidate", "gpt-5.5"),
                _worker("candidate", "claude-opus-4.6"),
                _worker("synthesizer", "gpt-5.5-pro"),
            ],
        },
        messages=[{"role": "user", "content": "Best answer"}],
        subscriptions=[_subscription()],
        get_secret=lambda _: "secret",
    )
    assert result["success"] is True
    assert result["selected_output"] == "SYNTHESIZED FINAL"
    assert result["candidates_collected"] == 2
    assert result["synthesized"] is True
    assert [obs["step_id"] for obs in result["observations"]].count("parallel_candidate") == 2
    assert result["observations"][-1]["step_id"] == "synthesize"
