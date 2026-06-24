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
