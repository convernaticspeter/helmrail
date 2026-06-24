from app.training import build_preference_pairs


def _base_sample(**overrides):
    sample = {
        "sample_id": "sample_test",
        "created_at_bucket": "2026-06",
        "task": {"category": "coding", "input_redacted": {"messages": []}},
        "routing": {"workflow_shape": "fugu-style-executed-multi-agent-as-model", "mode": "worker_verifier", "worker_classes": []},
        "execution": {
            "selected_output_redacted": "GOOD FALLBACK",
            "observations_redacted": [],
            "result_redacted": {},
        },
        "outputs": {"output_redacted": {"choices": [{"message": {"content": "FINAL"}}]}},
        "privacy": {"raw_trace_included": False, "contains_local_run_id": False, "redaction_pipeline": "deterministic-v0.2"},
    }
    sample.update(overrides)
    return sample


def test_build_preference_pairs_from_worker_verifier_rejection():
    sample = _base_sample(
        execution={
            "selected_output_redacted": "GOOD FALLBACK",
            "observations_redacted": [
                {"step_id": "produce", "model_id": "gpt-5.5", "provider": "openrouter", "ok": True, "text": "BAD PRIMARY"},
                {"step_id": "verify", "model_id": "claude-opus-4.6", "approved": False, "confidence": 20, "decision": {"approved": False, "confidence": 20, "suggestion": "bad"}},
                {"step_id": "fallback_produce", "model_id": "kimi-k2.7-code", "provider": "openrouter", "ok": True, "text": "GOOD FALLBACK"},
                {"step_id": "verify", "model_id": "claude-opus-4.6", "approved": True, "confidence": 91, "decision": {"approved": True, "confidence": 91}},
            ],
            "result_redacted": {},
        }
    )
    pairs = build_preference_pairs(sample)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["source"] == "verifier"
    assert pair["preference_type"] == "quality_verifier_preference"
    assert pair["chosen"]["text"] == "GOOD FALLBACK"
    assert pair["rejected"]["text"] == "BAD PRIMARY"
    assert pair["privacy"]["raw_trace_included"] is False


def test_build_preference_pairs_from_compare_synthesis():
    sample = _base_sample(
        routing={"workflow_shape": "fugu-style-executed-multi-agent-as-model", "mode": "compare", "worker_classes": ["candidate", "candidate", "synthesizer"]},
        execution={
            "selected_output_redacted": "SYNTH FINAL",
            "observations_redacted": [
                {"step_id": "parallel_candidate", "model_id": "gpt-5.5", "provider": "openrouter", "ok": True, "text": "A"},
                {"step_id": "parallel_candidate", "model_id": "claude-opus-4.6", "provider": "openrouter", "ok": True, "text": "B"},
                {"step_id": "synthesize", "model_id": "gpt-5.5-pro", "provider": "openrouter", "ok": True, "text": "SYNTH FINAL"},
            ],
            "result_redacted": {},
        }
    )
    pairs = build_preference_pairs(sample)
    assert len(pairs) == 2
    assert {pair["source"] for pair in pairs} == {"synthesizer"}
    assert {pair["rejected"]["text"] for pair in pairs} == {"A", "B"}
    assert all(pair["chosen"]["text"] == "SYNTH FINAL" for pair in pairs)


def test_build_preference_pairs_from_race_winner():
    sample = _base_sample(
        routing={"workflow_shape": "fugu-style-executed-multi-agent-as-model", "mode": "race", "worker_classes": ["candidate", "candidate"]},
        execution={
            "selected_output_redacted": "FAST WINNER",
            "observations_redacted": [
                {"step_id": "race_candidate", "model_id": "glm-5.2", "provider": "openrouter", "ok": True, "text": "FAST WINNER"},
                {"step_id": "race_candidate", "model_id": "kimi-k2.7-code", "provider": "openrouter", "ok": True, "text": "SLOW SECOND"},
            ],
            "result_redacted": {"winner": {"model_id": "glm-5.2", "provider": "openrouter", "latency_ms": 100}},
        }
    )
    pairs = build_preference_pairs(sample)
    assert len(pairs) == 1
    assert pairs[0]["source"] == "race_winner"
    assert pairs[0]["preference_type"] == "operational_first_success_preference"
    assert pairs[0]["chosen"]["text"] == "FAST WINNER"
    assert pairs[0]["rejected"]["text"] == "SLOW SECOND"


def test_build_preference_pairs_from_human_correction():
    sample = _base_sample(
        execution={"selected_output_redacted": "MODEL OUTPUT", "observations_redacted": [], "result_redacted": {}},
        feedback={
            "latest": {
                "outcome": "user_corrected",
                "rating": 4,
                "corrected_output_redacted": "HUMAN BETTER OUTPUT",
            }
        },
    )
    pairs = build_preference_pairs(sample)
    assert len(pairs) == 1
    assert pairs[0]["source"] == "human_feedback"
    assert pairs[0]["chosen"]["text"] == "HUMAN BETTER OUTPUT"
    assert pairs[0]["rejected"]["text"] == "MODEL OUTPUT"
    assert pairs[0]["preference"]["outcome"] == "user_corrected"


def test_build_preference_pairs_from_proxy_raw_output_shape_and_redacts_again():
    sample = _base_sample(
        execution={"selected_output_redacted": "", "observations_redacted": [], "result_redacted": {}},
        outputs={
            "output_redacted": {
                "ok": True,
                "raw": {
                    "choices": [
                        {
                            "message": {
                                "content": "Proxy final for [EMAIL_REDACTED] token=[SECRET_REDACTED] leaked-tail-token"
                            }
                        }
                    ]
                },
            }
        },
        feedback={
            "latest": {
                "outcome": "user_corrected",
                "rating": 5,
                "corrected_output_redacted": "Human correction token=[SECRET_REDACTED] human-tail-token",
            }
        },
    )
    pairs = build_preference_pairs(sample)
    assert len(pairs) == 1
    pair_text = str(pairs[0])
    assert "leaked-tail-token" not in pair_text
    assert "human-tail-token" not in pair_text
    assert "[SECRET_REDACTED]" in pair_text
    assert pairs[0]["rejected"]["text"].startswith("Proxy final")
