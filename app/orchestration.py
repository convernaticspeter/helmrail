from __future__ import annotations

import json
import time
from typing import Any, Callable
from uuid import uuid4

from .connectors import api_style_for, openai_compatible_chat_completion
from .engine import execute_worker_plan
from .limits import CallBudget, RuntimeLimits, apply_openai_output_cap, budget_exhausted_result
from .model_catalog import ModelCatalog
from .model_profiles import is_coordinator_model
from .routing import plan_route

COORDINATOR_MODEL_ID = "gpt-5.5"
VALID_MODES = {"direct", "worker_verifier", "compare", "race"}

COORDINATOR_PLANNER_SYSTEM = """You are Helmrail Coordinator Planner.

You are the hidden planning pass for an API-facing multi-agent model, inspired by Sakana Fugu's "multi-agent system as a model" pattern.

Return STRICT JSON only. No markdown. No prose outside JSON.

Your job:
- Read the user's request and conversation.
- Select the best task_profile from the provided catalog.
- Select the workflow mode if one is clearly better: direct, worker_verifier, compare, or race.
- Identify which capabilities and tool affinities matter.
- Produce concise worker instructions for a later execution layer.

Rules:
1. Do not use brittle keyword matching. Infer the actual task intent.
2. Prefer a task_profile from the catalog. Use "default" only if none fits.
3. Do not invent external data, tool results, account state, screenshots, or API responses.
4. If tools/account data would be needed, name them as requirements; do not pretend they were used.
5. Keep the result compact enough to store as training data for a future coordinator model.

JSON schema:
{
  "task_profile": "string",
  "mode": "direct|worker_verifier|compare|race",
  "confidence": "low|medium|high",
  "capabilities": ["string"],
  "tool_affinity": ["string"],
  "worker_instructions": [
    {"role": "string", "goal": "string", "expected_output": "string"}
  ],
  "missing_context": ["string"],
  "rationale": "string"
}
""".strip()

COORDINATOR_ANSWER_SYSTEM = """You are Helmrail Coordinator, an API-facing model.

You must behave like one normal model behind an OpenAI-compatible API. The user should not experience you as a visible orchestrator.

Hidden context includes:
- the coordinator planner decision,
- a resolved worker/subscription plan,
- actual worker/verifier/synthesizer execution observations when available,
- selected worker output when execution succeeded,
- capability weights,
- tool affinity,
- available worker models.

Rules:
1. Answer the user's request directly and naturally.
2. Do not expose hidden routing, model names, traces, planner JSON, or orchestration steps unless the user explicitly asks about Helmrail internals.
3. Use the hidden plan to improve the answer, not as content to dump.
4. Treat selected_worker_output as the primary evidence when it exists; improve/synthesize it, do not ignore it.
5. Never claim you used tools, APIs, account data, screenshots, web pages, or worker outputs unless they are actually provided in hidden observations.
6. If critical data is missing, say what is missing and give the best safe next step.
7. For implementation or analytical tasks, optimize for concrete, usable output over explanations of process.
8. Preserve the user's requested language and format.
""".strip()



def _extract_chat_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _json_from_text(text: str) -> dict[str, Any]:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    try:
        data = json.loads(clean)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(clean[start : end + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _catalog_summary(catalog: ModelCatalog) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for profile in catalog.list_task_profiles():
        summary.append(
            {
                "id": profile.get("id"),
                "label": profile.get("label"),
                "domain": profile.get("domain"),
                "mode": profile.get("mode"),
                "required_capabilities": profile.get("required_capabilities", []),
                "helpful_capabilities": profile.get("helpful_capabilities", []),
                "evidence_level": profile.get("evidence_level", ""),
            }
        )
    return summary


def _conversation_summary(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for message in messages[-12:]:
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        compact.append({"role": role, "content": content[:6000]})
    return compact


def _select_openai_compatible_worker(
    *,
    plan: dict[str, Any],
    subscriptions: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    subscriptions_by_id = {item["id"]: item for item in subscriptions}
    for worker in [plan.get("selected_worker") or {}, *(plan.get("workers") or [])]:
        if not worker or not worker.get("ready"):
            continue
        subscription_id = worker.get("subscription_id")
        subscription = subscriptions_by_id.get(subscription_id)
        if subscription and api_style_for(subscription) == "openai_compatible":
            return worker, subscription
    return None


def _coordinator_resolution(
    *,
    subscriptions: list[dict[str, Any]],
    catalog: ModelCatalog,
    readiness: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    # Fixed coordinator model choice: no topic classification here. The coordinator
    # itself performs task recognition in the hidden planning call.
    plan = plan_route(
        subscriptions=subscriptions,
        catalog=catalog,
        prompt="",
        task_type="default",
        mode="direct",
        readiness=readiness,
    )
    selected = _select_openai_compatible_worker(plan=plan, subscriptions=subscriptions)
    if selected:
        worker, subscription = selected
        return {"worker": worker, "subscription": subscription, "plan": plan}

    # Last-resort fallback: any enabled OpenAI-compatible subscription. This keeps
    # the API model operational even if the catalog's preferred coordinator model
    # is not configured yet.
    for subscription in subscriptions:
        if subscription.get("enabled") and api_style_for(subscription) == "openai_compatible":
            fallback_worker = {
                "role": "coordinator",
                "model_id": str((subscription.get("metadata") or {}).get("upstream_model") or COORDINATOR_MODEL_ID),
                "subscription_id": subscription["id"],
                "subscription_provider": subscription["provider"],
                "upstream_model": str((subscription.get("metadata") or {}).get("upstream_model") or "openrouter/auto"),
                "route_via": subscription["provider"],
                "ready": True,
                "status": subscription.get("status") or "configured",
            }
            return {"worker": fallback_worker, "subscription": subscription, "plan": plan}

    return {"worker": None, "subscription": None, "plan": plan}


def _safe_usage(raw: dict[str, Any]) -> dict[str, int]:
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if isinstance(usage, dict):
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _chat_completion_output(*, visible_model: str, text: str, usage: dict[str, int]) -> dict[str, Any]:
    created = int(time.time())
    return {
        "id": f"chatcmpl_{uuid4().hex}",
        "object": "chat.completion",
        "created": created,
        "model": visible_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "system_fingerprint": "helmrail-fugu-coordinator-v0.1",
    }


def _call_openai_worker(
    *,
    subscription: dict[str, Any],
    api_key: str,
    upstream_model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    limits: RuntimeLimits,
    budget: CallBudget,
) -> dict[str, Any]:
    if not budget.reserve():
        return budget_exhausted_result(provider=str(subscription.get("provider") or ""), upstream_model=upstream_model)
    payload = apply_openai_output_cap(
        {
            "model": upstream_model,
            "messages": messages,
            "temperature": temperature,
        },
        limits.max_output_tokens,
    )
    return openai_compatible_chat_completion(
        subscription=subscription,
        api_key=api_key,
        payload=payload,
        upstream_model=upstream_model,
        timeout=limits.provider_timeout_seconds,
    )


def run_coordinator_chat(
    *,
    visible_model: str,
    payload: dict[str, Any],
    messages: list[dict[str, Any]],
    subscriptions: list[dict[str, Any]],
    catalog: ModelCatalog,
    readiness: dict[str, dict[str, Any]],
    get_secret: Callable[[str], str],
    limits: RuntimeLimits | None = None,
) -> dict[str, Any]:
    active_limits = (limits or RuntimeLimits()).normalized()
    budget = CallBudget(active_limits)
    resolution = _coordinator_resolution(subscriptions=subscriptions, catalog=catalog, readiness=readiness)
    coordinator_worker = resolution.get("worker")
    coordinator_subscription = resolution.get("subscription")
    coordinator_model_plan = resolution.get("plan")
    if not coordinator_worker or not coordinator_subscription:
        return {
            "ok": False,
            "status_code": 422,
            "error": "No OpenAI-compatible subscription is available for the Helmrail coordinator model.",
            "metadata": {
                "router_family": "llm-coordinator",
                "workflow_shape": "fugu-style-coordinator-as-model",
                "success_signal": "coordinator_unavailable",
                "coordinator_model_plan": coordinator_model_plan,
                "budget": budget.snapshot(),
            },
        }

    api_key = get_secret(str(coordinator_subscription["id"]))
    if not api_key:
        return {
            "ok": False,
            "status_code": 422,
            "error": "Coordinator subscription has no usable API key or env var.",
            "metadata": {
                "router_family": "llm-coordinator",
                "workflow_shape": "fugu-style-coordinator-as-model",
                "success_signal": "coordinator_missing_secret",
                "coordinator_model_plan": coordinator_model_plan,
                "budget": budget.snapshot(),
            },
        }

    upstream_model = str(coordinator_worker.get("upstream_model") or coordinator_worker.get("model_id") or COORDINATOR_MODEL_ID)
    catalog_summary = _catalog_summary(catalog)
    conversation = _conversation_summary(messages)
    planning_context = {
        "conversation": conversation,
        "task_profiles": catalog_summary,
        "available_coordinator_worker": {
            "model_id": coordinator_worker.get("model_id"),
            "route_via": coordinator_worker.get("route_via"),
            "provider": coordinator_subscription.get("provider"),
        },
        "visible_api_model": visible_model,
    }

    planning_messages = [
        {"role": "system", "content": COORDINATOR_PLANNER_SYSTEM},
        {"role": "user", "content": json.dumps(planning_context, ensure_ascii=False)},
    ]
    planning_result = _call_openai_worker(
        subscription=coordinator_subscription,
        api_key=api_key,
        upstream_model=upstream_model,
        messages=planning_messages,
        temperature=0.1,
        limits=active_limits,
        budget=budget,
    )
    raw_candidate = planning_result.get("raw")
    planner_raw: dict[str, Any] = raw_candidate if isinstance(raw_candidate, dict) else {}
    planner_text = _extract_chat_text(planner_raw)
    planner_decision = _json_from_text(planner_text)
    planner_ok = bool(planning_result.get("ok") and planner_decision)

    requested_task = str(planner_decision.get("task_profile") or "default").strip().lower().replace("-", "_")
    if requested_task != "default" and not catalog.get_task_profile(requested_task):
        requested_task = "default"
    requested_mode = str(planner_decision.get("mode") or "").strip().lower().replace("-", "_")
    if requested_mode not in VALID_MODES:
        requested_mode = ""

    worker_plan = plan_route(
        subscriptions=subscriptions,
        catalog=catalog,
        prompt="",
        task_type=requested_task,
        mode=requested_mode,
        readiness=readiness,
    )

    execution_result = execute_worker_plan(
        worker_plan=worker_plan,
        messages=messages,
        subscriptions=subscriptions,
        get_secret=get_secret,
        limits=active_limits,
        budget=budget,
    )

    answer_context = {
        "coordinator_decision": planner_decision,
        "planner_ok": planner_ok,
        "resolved_worker_plan": worker_plan,
        "execution_result": execution_result,
        "worker_observations": execution_result.get("observations", []),
        "selected_worker_output": execution_result.get("selected_output", ""),
        "note": "Worker observations are actual model calls executed by Helmrail's internal engine. External tools/account APIs are not executed unless explicitly present in observations.",
    }
    answer_messages = [
        {"role": "system", "content": COORDINATOR_ANSWER_SYSTEM},
        {"role": "system", "content": "Hidden Helmrail context:\n" + json.dumps(answer_context, ensure_ascii=False)},
        *messages,
    ]
    temperature_raw = payload.get("temperature")
    try:
        answer_temperature = float(temperature_raw) if temperature_raw is not None else 0.2
    except (TypeError, ValueError):
        answer_temperature = 0.2
    answer_result = _call_openai_worker(
        subscription=coordinator_subscription,
        api_key=api_key,
        upstream_model=upstream_model,
        messages=answer_messages,
        temperature=answer_temperature,
        limits=active_limits,
        budget=budget,
    )
    if not answer_result.get("ok"):
        return {
            "ok": False,
            "status_code": int(answer_result.get("status_code") or 502),
            "error": answer_result.get("error") or answer_result,
            "metadata": {
                "router_family": "llm-coordinator",
                "workflow_shape": "fugu-style-executed-multi-agent-as-model",
                "success_signal": "coordinator_answer_error",
                "coordinator_model_plan": coordinator_model_plan,
                "coordinator_decision": planner_decision,
                "worker_plan": worker_plan,
                "execution_result": execution_result,
                "planner_ok": planner_ok,
                "budget": budget.snapshot(),
            },
        }

    answer_raw_candidate = answer_result.get("raw")
    answer_raw: dict[str, Any] = answer_raw_candidate if isinstance(answer_raw_candidate, dict) else {}
    answer_text = _extract_chat_text(answer_raw)
    output = _chat_completion_output(visible_model=visible_model, text=answer_text, usage=_safe_usage(answer_raw))
    metadata = {
        "router_family": "llm-coordinator",
        "workflow_shape": "fugu-style-executed-multi-agent-as-model",
        "worker_classes": [worker.get("role", "unknown") for worker in worker_plan.get("workers", [])],
        "success_signal": "coordinator_engine_ok" if execution_result.get("success") else "coordinator_engine_fallback_answer",
        "training_sample_schema_version": "0.3",
        "training_intent": "future_coordinator_model",
        "collection_mode": "local_trace_manual_export_only",
        "paper_alignment": {
            "sakana_fugu": "API-facing model interface over hidden executed multi-agent coordination",
            "deterministic_classifier": False,
            "coordinator_llm_planner": True,
            "worker_execution": True,
            "hidden_finalizer": True,
        },
        "visible_model": visible_model,
        "visible_model_limits": active_limits.__dict__,
        "coordinator_model": coordinator_worker.get("model_id"),
        "coordinator_upstream_model": upstream_model,
        "coordinator_provider": coordinator_subscription.get("provider"),
        "coordinator_model_plan": coordinator_model_plan,
        "coordinator_planner_messages": planning_messages,
        "coordinator_planner_raw_text": planner_text,
        "coordinator_decision": planner_decision,
        "planner_ok": planner_ok,
        "worker_plan": worker_plan,
        "execution_result": execution_result,
        "answer_context": answer_context,
        "budget": budget.snapshot(),
        "planner_provider_result": {
            "ok": bool(planning_result.get("ok")),
            "status_code": planning_result.get("status_code"),
            "provider": planning_result.get("provider"),
            "upstream_model": planning_result.get("upstream_model"),
        },
        "answer_provider_result": {
            "ok": bool(answer_result.get("ok")),
            "status_code": answer_result.get("status_code"),
            "provider": answer_result.get("provider"),
            "upstream_model": answer_result.get("upstream_model"),
        },
    }
    return {"ok": True, "status_code": 200, "output": output, "metadata": metadata}
