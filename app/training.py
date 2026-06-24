from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .redaction import redact_json


def _month_bucket(created_at: str) -> str:
    if created_at:
        return created_at[:7]
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _latency_bucket(ms: int | float | None) -> str:
    if ms is None:
        return "unknown"
    try:
        value = float(ms)
    except (TypeError, ValueError):
        return "unknown"
    if value < 1_000:
        return "lt_1s"
    if value < 5_000:
        return "1s_5s"
    if value < 15_000:
        return "5s_15s"
    if value < 60_000:
        return "15s_60s"
    return "gt_60s"


def _execution_latency_bucket(execution_result: dict[str, Any]) -> str:
    observations = execution_result.get("observations") if isinstance(execution_result, dict) else None
    if not isinstance(observations, list) or not observations:
        return "unknown"
    total_ms = 0.0
    seen = False
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        raw_ms = observation.get("latency_ms")
        if raw_ms is None:
            continue
        try:
            total_ms += float(raw_ms)
            seen = True
        except (TypeError, ValueError):
            continue
    return _latency_bucket(total_ms if seen else None)


def _failure_mode(metadata: dict[str, Any], execution_result: dict[str, Any]) -> str:
    success = metadata.get("success_signal", "")
    if success in {"coordinator_engine_ok", "provider_ok", "coordinator_ok"}:
        return "none"
    if execution_result and not execution_result.get("success", True):
        return str(execution_result.get("reason") or "execution_failed")
    if success:
        return str(success)
    return "unknown"


def _tool_use_shape(metadata: dict[str, Any]) -> str:
    worker_plan = metadata.get("worker_plan") if isinstance(metadata, dict) else None
    if not isinstance(worker_plan, dict):
        return "none"
    tool_affinity = worker_plan.get("tool_affinity") or []
    if not tool_affinity:
        return "none"
    return "affinity_only_no_external_tool_calls"


def build_training_sample(
    *,
    sample_id: str,
    created_at: str,
    endpoint: str,
    model: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    helmrail_version: str = "unknown",
    contribution_mode: str = "local-auto-anonymized",
) -> dict[str, Any]:
    """Create a redacted, detached-ish training sample from a local raw trace.

    The returned JSON deliberately does not include the local run_id. The DB may
    keep a local run_id -> sample_id map for deletion/debug while data is local;
    exported bundles should use this sample JSON only.
    """
    metadata_dict: dict[str, Any] = metadata or {}
    worker_plan_raw = metadata_dict.get("worker_plan")
    worker_plan: dict[str, Any] = worker_plan_raw if isinstance(worker_plan_raw, dict) else {}
    execution_raw = metadata_dict.get("execution_result")
    execution_result: dict[str, Any] = execution_raw if isinstance(execution_raw, dict) else {}
    coordinator_raw = metadata_dict.get("coordinator_decision")
    coordinator_decision: dict[str, Any] = coordinator_raw if isinstance(coordinator_raw, dict) else {}
    task_profile_raw = worker_plan.get("task_profile")
    task_profile: dict[str, Any] = task_profile_raw if isinstance(task_profile_raw, dict) else {}
    redacted_input = redact_json(input_payload)
    redacted_output = redact_json(output_payload)
    redacted_metadata = redact_json(metadata_dict)
    redacted_execution = redact_json(execution_result)

    sample = {
        "schema_version": metadata_dict.get("training_sample_schema_version", "0.4"),
        "sample_id": sample_id,
        "created_at_bucket": _month_bucket(created_at),
        "source": {
            "helmrail_version": helmrail_version,
            "endpoint": endpoint,
            "contribution_mode": contribution_mode,
            "upload_state": "local_only_not_uploaded",
            "consent_version": "local-auto-draft-0.1",
        },
        "task": {
            "category": worker_plan.get("task_type") or coordinator_decision.get("task_profile") or "unknown",
            "profile_domain": task_profile.get("domain", "unknown"),
            "language": "unknown",
            "sensitivity_after_redaction": "medium-review-required",
            "input_redacted": redacted_input,
        },
        "routing": {
            "router_family": metadata_dict.get("router_family", "unknown"),
            "workflow_shape": metadata_dict.get("workflow_shape", "unknown"),
            "mode": worker_plan.get("mode", "unknown"),
            "visible_model": metadata_dict.get("visible_model", model),
            "worker_classes": metadata_dict.get("worker_classes", []),
            "capability_weights": worker_plan.get("capability_weights", {}),
            "tool_affinity": worker_plan.get("tool_affinity", []),
        },
        "coordinator": {
            "planner_ok": metadata_dict.get("planner_ok", False),
            "decision_redacted": redact_json(coordinator_decision),
            "worker_plan_redacted": redact_json(worker_plan),
            "paper_alignment": metadata_dict.get("paper_alignment", {}),
        },
        "execution": {
            "success": bool(execution_result.get("success")) if execution_result else metadata_dict.get("success_signal") == "provider_ok",
            "selected_output_redacted": redact_json(execution_result.get("selected_output", "")) if execution_result else "",
            "observations_redacted": redacted_execution.get("observations", []) if isinstance(redacted_execution, dict) else [],
            "result_redacted": redacted_execution,
        },
        "observations": {
            "latency_bucket": _execution_latency_bucket(execution_result),
            "cost_bucket": "unknown",
            "tool_use_shape": _tool_use_shape(metadata_dict),
            "success_signal": metadata_dict.get("success_signal", "unknown"),
            "failure_mode": _failure_mode(metadata_dict, execution_result),
        },
        "outputs": {
            "output_redacted": redacted_output,
        },
        "privacy": {
            "contains_local_run_id": False,
            "raw_trace_included": False,
            "redaction_pipeline": "deterministic-v0.2",
            "review_required_before_upload": True,
            "stored_locally": True,
        },
        "debug_redacted_metadata": redacted_metadata,
        "warnings": [
            "Local anonymized sample only: no data has been uploaded.",
            "Human review is required before contribution/export.",
            "Raw trace remains local and separate for operational debugging/deletion.",
        ],
    }
    return sample


def _choice_text(output_payload: Any) -> str:
    if not isinstance(output_payload, dict):
        return str(output_payload or "")
    choices = output_payload.get("choices")
    if not isinstance(choices, list) and isinstance(output_payload.get("raw"), dict):
        choices = output_payload["raw"].get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else {}
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if content is not None:
                return str(content)
    return ""


def _candidate_payload(observation: dict[str, Any], *, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "model_id": observation.get("model_id", ""),
        "provider": observation.get("provider", ""),
        "step_id": observation.get("step_id", ""),
        "text": redact_json(observation.get("text", "")),
    }


def _final_output_payload(sample: dict[str, Any]) -> dict[str, Any]:
    execution = sample.get("execution") if isinstance(sample.get("execution"), dict) else {}
    selected = execution.get("selected_output_redacted") if isinstance(execution, dict) else ""
    if isinstance(selected, str) and selected:
        return {
            "kind": "selected_worker_output",
            "model_id": "",
            "provider": "",
            "step_id": "selected_output",
            "text": redact_json(selected),
        }
    outputs = sample.get("outputs") if isinstance(sample.get("outputs"), dict) else {}
    text = _choice_text(outputs.get("output_redacted")) if isinstance(outputs, dict) else ""
    return {
        "kind": "final_output",
        "model_id": "",
        "provider": "",
        "step_id": "final_output",
        "text": redact_json(text),
    }


def _pair(
    *,
    sample: dict[str, Any],
    idx: int,
    source: str,
    chosen: dict[str, Any],
    rejected: dict[str, Any],
    preference_type: str,
    reason: str,
    confidence: int | None = None,
    outcome: str = "",
) -> dict[str, Any] | None:
    if not chosen.get("text") or not rejected.get("text"):
        return None
    if chosen.get("text") == rejected.get("text"):
        return None
    sample_id = str(sample.get("sample_id") or "sample_unknown")
    return {
        "schema_version": "preference_pair_v0.1",
        "pair_id": f"{sample_id}_pair_{idx}",
        "sample_id": sample_id,
        "created_at_bucket": sample.get("created_at_bucket", ""),
        "source": source,
        "preference_type": preference_type,
        "task": redact_json(sample.get("task", {})),
        "routing": {
            "workflow_shape": (sample.get("routing") or {}).get("workflow_shape", "unknown") if isinstance(sample.get("routing"), dict) else "unknown",
            "mode": (sample.get("routing") or {}).get("mode", "unknown") if isinstance(sample.get("routing"), dict) else "unknown",
            "worker_classes": (sample.get("routing") or {}).get("worker_classes", []) if isinstance(sample.get("routing"), dict) else [],
        },
        "chosen": chosen,
        "rejected": rejected,
        "preference": {
            "label": "chosen_preferred",
            "reason": reason,
            "confidence": confidence,
            "outcome": outcome,
        },
        "privacy": {
            "raw_trace_included": False,
            "contains_local_run_id": False,
            "redaction_pipeline": (sample.get("privacy") or {}).get("redaction_pipeline", "deterministic-v0.2") if isinstance(sample.get("privacy"), dict) else "deterministic-v0.2",
        },
    }


def build_preference_pairs(sample: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive preference-pair training records from an anonymized sample only.

    This function must not require or emit local run IDs or raw traces. It uses
    redacted worker observations, selected output, and optional redacted human
    feedback/corrections already embedded in the sample.
    """
    pairs: list[dict[str, Any]] = []
    execution = sample.get("execution") if isinstance(sample.get("execution"), dict) else {}
    observations = execution.get("observations_redacted") if isinstance(execution, dict) else []
    observations = observations if isinstance(observations, list) else []
    selected_output = _final_output_payload(sample)

    def add_pair(**kwargs: Any) -> None:
        pair = _pair(sample=sample, idx=len(pairs) + 1, **kwargs)
        if pair is not None:
            pairs.append(pair)

    # Verifier/reviewer signals: rejected candidate vs accepted/selected output.
    verified_candidates: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            continue
        if observation.get("step_id") not in {"produce", "fallback_produce", "execute"}:
            continue
        next_obs = observations[index + 1] if index + 1 < len(observations) and isinstance(observations[index + 1], dict) else None
        verifier_obs = next_obs if next_obs and next_obs.get("step_id") in {"verify", "review"} else None
        verified_candidates.append((observation, verifier_obs))

    accepted_candidate: tuple[dict[str, Any], dict[str, Any], int | None] | None = None
    rejected_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate, verifier_obs in verified_candidates:
        if not candidate.get("text"):
            continue
        if verifier_obs is not None:
            decision_raw = verifier_obs.get("decision")
            decision: dict[str, Any] = decision_raw if isinstance(decision_raw, dict) else {}
            approved = bool(verifier_obs.get("approved")) or bool(decision.get("approved"))
            confidence_raw = verifier_obs.get("confidence") or decision.get("confidence")
            confidence = int(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
            if approved:
                accepted_candidate = (candidate, verifier_obs, confidence)
            else:
                rejected_candidates.append((candidate, verifier_obs))
        elif selected_output.get("text") == candidate.get("text"):
            accepted_candidate = (candidate, {}, None)

    if accepted_candidate:
        accepted_obs, accepted_verifier, accepted_confidence = accepted_candidate
        chosen = _candidate_payload(accepted_obs, kind="accepted_worker_output")
        for rejected_obs, rejected_verifier in rejected_candidates:
            rejected_decision_raw = rejected_verifier.get("decision")
            decision: dict[str, Any] = rejected_decision_raw if isinstance(rejected_decision_raw, dict) else {}
            confidence_raw = rejected_verifier.get("confidence") or decision.get("confidence")
            confidence = int(confidence_raw) if isinstance(confidence_raw, (int, float)) else accepted_confidence
            add_pair(
                source="verifier",
                chosen=chosen,
                rejected=_candidate_payload(rejected_obs, kind="rejected_worker_output"),
                preference_type="quality_verifier_preference",
                reason=str(decision.get("suggestion") or decision.get("issues") or "Verifier rejected one candidate and accepted another."),
                confidence=confidence,
            )

    # Compare mode: synthesized output is preferred over individual candidates.
    synth_obs = next((obs for obs in observations if isinstance(obs, dict) and obs.get("step_id") == "synthesize" and obs.get("text")), None)
    if synth_obs:
        chosen = _candidate_payload(synth_obs, kind="synthesized_output")
        for obs in observations:
            if isinstance(obs, dict) and obs.get("step_id") == "parallel_candidate" and obs.get("text"):
                add_pair(
                    source="synthesizer",
                    chosen=chosen,
                    rejected=_candidate_payload(obs, kind="candidate_output"),
                    preference_type="synthesis_preference",
                    reason="Synthesizer output selected over raw candidate output.",
                )

    # Race mode: first successful winner over other successful candidates. This is operational, not necessarily semantic quality.
    result_raw = execution.get("result_redacted") if isinstance(execution, dict) else None
    result_redacted: dict[str, Any] = result_raw if isinstance(result_raw, dict) else {}
    winner_raw = result_redacted.get("winner")
    winner: dict[str, Any] = winner_raw if isinstance(winner_raw, dict) else {}
    winner_model = str(winner.get("model_id") or "")
    if winner_model:
        winner_obs = next((obs for obs in observations if isinstance(obs, dict) and obs.get("model_id") == winner_model and obs.get("text")), None)
        if winner_obs:
            chosen = _candidate_payload(winner_obs, kind="race_winner_output")
            for obs in observations:
                if isinstance(obs, dict) and obs.get("step_id") == "race_candidate" and obs.get("text") and obs.get("model_id") != winner_model:
                    add_pair(
                        source="race_winner",
                        chosen=chosen,
                        rejected=_candidate_payload(obs, kind="race_non_winner_output"),
                        preference_type="operational_first_success_preference",
                        reason="Race mode selected the first successful candidate; use cautiously as latency/availability signal.",
                    )

    # Human feedback/correction: corrected output over the model's selected/final output.
    feedback = sample.get("feedback") if isinstance(sample.get("feedback"), dict) else {}
    latest = feedback.get("latest") if isinstance(feedback, dict) and isinstance(feedback.get("latest"), dict) else {}
    corrected = latest.get("corrected_output_redacted") if isinstance(latest, dict) else None
    outcome = str(latest.get("outcome") or "") if isinstance(latest, dict) else ""
    if corrected and outcome in {"edited", "user_corrected", "rejected", "bad", "partial"}:
        add_pair(
            source="human_feedback",
            chosen={"kind": "human_corrected_output", "model_id": "", "provider": "", "step_id": "feedback", "text": redact_json(str(corrected))},
            rejected=selected_output,
            preference_type="human_correction_preference",
            reason="Human feedback supplied a corrected/preferred output.",
            outcome=outcome,
        )

    return pairs
