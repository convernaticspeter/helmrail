from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .connectors import openai_compatible_chat_completion
from .limits import CallBudget, RuntimeLimits, apply_openai_output_cap, budget_exhausted_result

MAX_CONCURRENT_WORKERS = 4
VERIFIER_CONFIDENCE_THRESHOLD = 60
MAX_TEXT_LENGTH = 8000


VERIFY_SYSTEM = """You are a quality verifier for a multi-model orchestration system.

Review the worker output against the original user request.

Evaluate:
1. Does the output address the user's actual request?
2. Is it technically correct and complete?
3. Is anything obviously missing, hallucinated, or wrong?

Return STRICT JSON only:
{
  "approved": true or false,
  "confidence": 0 to 100,
  "issues": ["list of issues if any"],
  "suggestion": "improvement suggestion if not approved, else empty string"
}
""".strip()

SYNTHESIZE_SYSTEM = """You are a synthesizer in a multi-model orchestration system.

Multiple specialist models produced independent candidate answers to the same user request.

Your job:
1. Read each candidate answer carefully.
2. Select the strongest elements from each.
3. If candidates disagree, explain trade-offs and resolve them.
4. Produce ONE final synthesized answer.

Do NOT output JSON. Output the final answer text directly.
Be concrete, specific, and actionable. Prefer quality over length.
""".strip()

REVIEW_SYSTEM = """You are a quality reviewer in a multi-model orchestration system.

Review the direct worker output against the original user request.

Return STRICT JSON only:
{
  "approved": true or false,
  "confidence": 0 to 100,
  "issues": ["list of issues if any"],
  "improved_text": "if not approved, write an improved version; else empty string"
}
""".strip()


def _extract_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False) if content else ""


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


def _truncate(text: str, max_len: int = MAX_TEXT_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 40] + f"\n\n[truncated {len(text) - max_len + 40} chars]"


def _call_provider(
    *,
    worker: dict[str, Any],
    api_key: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    timeout: int = 180,
    budget: CallBudget | None = None,
) -> dict[str, Any]:
    """Make a single OpenAI-compatible chat/completion call."""
    subscription = worker.get("_subscription")
    upstream_model = str(worker.get("upstream_model") or worker.get("model_id") or "")
    if budget is not None and not budget.reserve():
        return budget_exhausted_result(provider=str(worker.get("subscription_provider") or ""), upstream_model=upstream_model)
    if not subscription:
        return {"ok": False, "error": "No subscription resolved for this worker.", "text": "", "latency_ms": 0}
    if worker.get("api_style") and worker.get("api_style") != "openai_compatible":
        return {
            "ok": False,
            "error": f"Worker api_style={worker.get('api_style')} is not supported by the OpenAI-compatible execution engine yet.",
            "text": "",
            "latency_ms": 0,
            "provider": worker.get("subscription_provider"),
            "upstream_model": worker.get("upstream_model") or worker.get("model_id"),
        }
    if not api_key:
        return {
            "ok": False,
            "error": "No API key or env secret is available for this worker.",
            "text": "",
            "latency_ms": 0,
            "provider": worker.get("subscription_provider"),
            "upstream_model": worker.get("upstream_model") or worker.get("model_id"),
        }
    if not upstream_model:
        return {"ok": False, "error": "No upstream model for this worker.", "text": "", "latency_ms": 0}

    payload = apply_openai_output_cap(
        {
            "model": upstream_model,
            "messages": messages,
            "temperature": temperature,
        },
        budget.limits.max_output_tokens if budget is not None else RuntimeLimits().max_output_tokens,
    )
    t0 = time.monotonic()
    try:
        result = openai_compatible_chat_completion(
            subscription=subscription,
            api_key=api_key,
            payload=payload,
            upstream_model=upstream_model,
            timeout=timeout,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "text": "",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "provider": worker.get("subscription_provider"),
            "upstream_model": upstream_model,
        }
    latency_ms = int((time.monotonic() - t0) * 1000)
    raw_candidate = result.get("raw")
    raw: dict[str, Any] = raw_candidate if isinstance(raw_candidate, dict) else {}
    text = _extract_text(raw) if result.get("ok") else ""
    return {
        "ok": bool(result.get("ok")),
        "status_code": result.get("status_code"),
        "text": text,
        "latency_ms": latency_ms,
        "error": result.get("error"),
        "provider": result.get("provider") or worker.get("subscription_provider"),
        "upstream_model": result.get("upstream_model") or upstream_model,
        "usage": raw.get("usage", {}),
    }


def _resolve_worker_subscription(
    worker: dict[str, Any],
    subscriptions_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach the resolved subscription object to a worker for engine calls."""
    sub_id = worker.get("subscription_id")
    if sub_id and sub_id in subscriptions_by_id:
        return {**worker, "_subscription": subscriptions_by_id[sub_id]}
    return worker


def _build_verify_messages(
    *,
    original_messages: list[dict[str, Any]],
    worker_text: str,
    worker_role: str,
    worker_model: str,
) -> list[dict[str, Any]]:
    user_text = ""
    for msg in reversed(original_messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            user_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            break
    return [
        {"role": "system", "content": VERIFY_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "original_request": _truncate(user_text),
                    "worker_role": worker_role,
                    "worker_model": worker_model,
                    "worker_output": _truncate(worker_text),
                },
                ensure_ascii=False,
            ),
        },
    ]


def _build_review_messages(
    *,
    original_messages: list[dict[str, Any]],
    worker_text: str,
    worker_role: str,
    worker_model: str,
) -> list[dict[str, Any]]:
    user_text = ""
    for msg in reversed(original_messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            user_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            break
    return [
        {"role": "system", "content": REVIEW_SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "original_request": _truncate(user_text),
                    "worker_role": worker_role,
                    "worker_model": worker_model,
                    "worker_output": _truncate(worker_text),
                },
                ensure_ascii=False,
            ),
        },
    ]


def _build_synthesize_messages(
    *,
    original_messages: list[dict[str, Any]],
    candidate_outputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    user_text = ""
    for msg in reversed(original_messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            user_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            break
    candidates_text = ""
    for idx, cand in enumerate(candidate_outputs, start=1):
        candidates_text += f"\n\n--- Candidate {idx} (model: {cand.get('model_id', 'unknown')}) ---\n{_truncate(cand.get('text', ''), 4000)}"
    return [
        {"role": "system", "content": SYNTHESIZE_SYSTEM},
        {
            "role": "user",
            "content": f"Original request:\n{_truncate(user_text)}\n\n{candidates_text}",
        },
    ]


def _execute_direct(
    *,
    worker_plan: dict[str, Any],
    messages: list[dict[str, Any]],
    get_secret: Callable[[str], str],
    subscriptions_by_id: dict[str, dict[str, Any]],
    limits: RuntimeLimits,
    budget: CallBudget,
) -> dict[str, Any]:
    workers = worker_plan.get("workers", [])
    primary = next((w for w in workers if w.get("role") == "primary"), None)
    fallbacks = [w for w in workers if w.get("role") == "fallback"]
    reviewer = next((w for w in workers if w.get("role") == "verifier"), None)

    if not primary or not primary.get("ready"):
        return {"mode": "direct", "observations": [], "selected_output": "", "success": False, "reason": "no_ready_worker"}

    observations: list[dict[str, Any]] = []
    primary = _resolve_worker_subscription(primary, subscriptions_by_id)
    api_key = get_secret(str(primary.get("subscription_id", "")))
    primary_result = _call_provider(
        worker=primary,
        api_key=api_key,
        messages=messages,
        temperature=0.2,
        timeout=limits.provider_timeout_seconds,
        budget=budget,
    )
    observation = {
        "step_id": "execute",
        "role": primary.get("role"),
        "model_id": primary.get("model_id"),
        "provider": primary_result.get("provider"),
        "upstream_model": primary_result.get("upstream_model"),
        "ok": primary_result["ok"],
        "text": primary_result.get("text", ""),
        "latency_ms": primary_result.get("latency_ms", 0),
    }
    observations.append(observation)

    selected_text = primary_result.get("text", "")
    selected_output_obs = observation

    if not primary_result["ok"]:
        for fb in fallbacks:
            if not fb.get("ready"):
                continue
            fb = _resolve_worker_subscription(fb, subscriptions_by_id)
            fb_key = get_secret(str(fb.get("subscription_id", "")))
            fb_result = _call_provider(
                worker=fb,
                api_key=fb_key,
                messages=messages,
                temperature=0.2,
                timeout=limits.provider_timeout_seconds,
                budget=budget,
            )
            fb_obs = {
                "step_id": "fallback",
                "role": fb.get("role"),
                "model_id": fb.get("model_id"),
                "provider": fb_result.get("provider"),
                "upstream_model": fb_result.get("upstream_model"),
                "ok": fb_result["ok"],
                "text": fb_result.get("text", ""),
                "latency_ms": fb_result.get("latency_ms", 0),
            }
            observations.append(fb_obs)
            if fb_result["ok"]:
                selected_text = fb_result.get("text", "")
                selected_output_obs = fb_obs
                break

    # Optional reviewer
    if reviewer and selected_text and reviewer.get("ready"):
        reviewer = _resolve_worker_subscription(reviewer, subscriptions_by_id)
        rev_key = get_secret(str(reviewer.get("subscription_id", "")))
        review_messages = _build_review_messages(
            original_messages=messages,
            worker_text=selected_text,
            worker_role=str(selected_output_obs.get("role", "primary")),
            worker_model=str(selected_output_obs.get("model_id", "unknown")),
        )
        review_result = _call_provider(
            worker=reviewer,
            api_key=rev_key,
            messages=review_messages,
            temperature=0.1,
            timeout=limits.provider_timeout_seconds,
            budget=budget,
        )
        review_decision = _json_from_text(review_result.get("text", "")) if review_result["ok"] else {}
        review_obs = {
            "step_id": "review",
            "role": reviewer.get("role"),
            "model_id": reviewer.get("model_id"),
            "provider": review_result.get("provider"),
            "upstream_model": review_result.get("upstream_model"),
            "ok": review_result["ok"],
            "text": review_result.get("text", ""),
            "latency_ms": review_result.get("latency_ms", 0),
            "decision": review_decision,
        }
        observations.append(review_obs)
        if review_decision.get("approved") is False and review_decision.get("improved_text"):
            selected_text = str(review_decision["improved_text"])

    return {
        "mode": "direct",
        "observations": observations,
        "selected_output": selected_text,
        "success": bool(selected_text),
    }


def _execute_worker_verifier(
    *,
    worker_plan: dict[str, Any],
    messages: list[dict[str, Any]],
    get_secret: Callable[[str], str],
    subscriptions_by_id: dict[str, dict[str, Any]],
    limits: RuntimeLimits,
    budget: CallBudget,
) -> dict[str, Any]:
    workers = worker_plan.get("workers", [])
    primary = next((w for w in workers if w.get("role") == "worker" and w.get("ready")), None)
    fallback = next((w for w in workers if w.get("role") == "fallback_worker" and w.get("ready")), None)
    verifier = next((w for w in workers if w.get("role") == "verifier" and w.get("ready")), None)

    if not primary and not fallback:
        return {"mode": "worker_verifier", "observations": [], "selected_output": "", "success": False, "reason": "no_ready_worker"}

    observations: list[dict[str, Any]] = []
    selected_text = ""

    for candidate_worker, step_id in [(primary, "produce"), (fallback, "fallback_produce")]:
        if not candidate_worker:
            continue
        candidate_worker = _resolve_worker_subscription(candidate_worker, subscriptions_by_id)
        api_key = get_secret(str(candidate_worker.get("subscription_id", "")))
        work_result = _call_provider(
            worker=candidate_worker,
            api_key=api_key,
            messages=messages,
            temperature=0.2,
            timeout=limits.provider_timeout_seconds,
            budget=budget,
        )
        work_obs = {
            "step_id": step_id,
            "role": candidate_worker.get("role"),
            "model_id": candidate_worker.get("model_id"),
            "provider": work_result.get("provider"),
            "upstream_model": work_result.get("upstream_model"),
            "ok": work_result["ok"],
            "text": work_result.get("text", ""),
            "latency_ms": work_result.get("latency_ms", 0),
        }
        observations.append(work_obs)

        if not work_result["ok"] or not work_result.get("text"):
            continue

        worker_text = work_result["text"]

        # Check with verifier
        if verifier:
            verifier = _resolve_worker_subscription(verifier, subscriptions_by_id)
            v_key = get_secret(str(verifier.get("subscription_id", "")))
            verify_messages = _build_verify_messages(
                original_messages=messages,
                worker_text=worker_text,
                worker_role=str(candidate_worker.get("role", "worker")),
                worker_model=str(candidate_worker.get("model_id", "unknown")),
            )
            verify_result = _call_provider(
                worker=verifier,
                api_key=v_key,
                messages=verify_messages,
                temperature=0.1,
                timeout=limits.provider_timeout_seconds,
                budget=budget,
            )
            verdict = _json_from_text(verify_result.get("text", "")) if verify_result["ok"] else {}
            confidence = int(verdict.get("confidence", 50)) if isinstance(verdict.get("confidence"), (int, float)) else 50
            approved = bool(verdict.get("approved")) or confidence >= VERIFIER_CONFIDENCE_THRESHOLD
            verify_obs = {
                "step_id": "verify",
                "role": verifier.get("role"),
                "model_id": verifier.get("model_id"),
                "provider": verify_result.get("provider"),
                "upstream_model": verify_result.get("upstream_model"),
                "ok": verify_result["ok"],
                "text": verify_result.get("text", ""),
                "latency_ms": verify_result.get("latency_ms", 0),
                "decision": verdict,
                "approved": approved,
                "confidence": confidence,
            }
            observations.append(verify_obs)

            if approved:
                selected_text = worker_text
                break
            # Not approved → try next candidate (fallback)
            continue

        # No verifier → accept
        selected_text = worker_text
        break

    return {
        "mode": "worker_verifier",
        "observations": observations,
        "selected_output": selected_text,
        "success": bool(selected_text),
    }


def _execute_race(
    *,
    worker_plan: dict[str, Any],
    messages: list[dict[str, Any]],
    get_secret: Callable[[str], str],
    subscriptions_by_id: dict[str, dict[str, Any]],
    limits: RuntimeLimits,
    budget: CallBudget,
) -> dict[str, Any]:
    workers = [
        _resolve_worker_subscription(w, subscriptions_by_id)
        for w in worker_plan.get("workers", [])
        if w.get("role") == "candidate" and w.get("ready")
    ]
    if not workers:
        return {"mode": "race", "observations": [], "selected_output": "", "success": False, "reason": "no_ready_candidates"}

    observations: list[dict[str, Any]] = []
    selected_text = ""
    winner_obs: dict[str, Any] | None = None

    def _race_call(worker: dict[str, Any]) -> dict[str, Any]:
        api_key = get_secret(str(worker.get("subscription_id", "")))
        result = _call_provider(
            worker=worker,
            api_key=api_key,
            messages=messages,
            temperature=0.2,
            timeout=limits.provider_timeout_seconds,
            budget=budget,
        )
        return {
            "worker": worker,
            "result": result,
        }

    with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT_WORKERS, limits.max_parallel_workers, len(workers))) as pool:
        futures = {pool.submit(_race_call, w): w for w in workers}
        for future in as_completed(futures):
            worker = futures[future]
            try:
                payload = future.result()
            except Exception as exc:
                observations.append({
                    "step_id": "race_candidate",
                    "role": "candidate",
                    "model_id": worker.get("model_id"),
                    "ok": False,
                    "text": "",
                    "latency_ms": 0,
                    "error": str(exc),
                })
                continue
            result = payload["result"]
            obs = {
                "step_id": "race_candidate",
                "role": "candidate",
                "model_id": worker.get("model_id"),
                "provider": result.get("provider"),
                "upstream_model": result.get("upstream_model"),
                "ok": result["ok"],
                "text": result.get("text", ""),
                "latency_ms": result.get("latency_ms", 0),
            }
            observations.append(obs)
            if result["ok"] and result.get("text") and not selected_text:
                selected_text = result["text"]
                winner_obs = obs

    return {
        "mode": "race",
        "observations": observations,
        "selected_output": selected_text,
        "winner": {
            "model_id": winner_obs.get("model_id") if winner_obs else "",
            "provider": winner_obs.get("provider") if winner_obs else "",
            "latency_ms": winner_obs.get("latency_ms", 0) if winner_obs else 0,
        } if winner_obs else None,
        "success": bool(selected_text),
    }


def _execute_compare(
    *,
    worker_plan: dict[str, Any],
    messages: list[dict[str, Any]],
    get_secret: Callable[[str], str],
    subscriptions_by_id: dict[str, dict[str, Any]],
    limits: RuntimeLimits,
    budget: CallBudget,
) -> dict[str, Any]:
    workers = [
        _resolve_worker_subscription(w, subscriptions_by_id)
        for w in worker_plan.get("workers", [])
        if w.get("role") == "candidate" and w.get("ready")
    ]
    synthesizer = next(
        (
            _resolve_worker_subscription(w, subscriptions_by_id)
            for w in worker_plan.get("workers", [])
            if w.get("role") == "synthesizer" and w.get("ready")
        ),
        None,
    )
    if not workers:
        return {"mode": "compare", "observations": [], "selected_output": "", "success": False, "reason": "no_ready_candidates"}

    observations: list[dict[str, Any]] = []
    candidate_outputs: list[dict[str, Any]] = []

    def _candidate_call(worker: dict[str, Any]) -> dict[str, Any]:
        api_key = get_secret(str(worker.get("subscription_id", "")))
        result = _call_provider(
            worker=worker,
            api_key=api_key,
            messages=messages,
            temperature=0.2,
            timeout=limits.provider_timeout_seconds,
            budget=budget,
        )
        return {"worker": worker, "result": result}

    with ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT_WORKERS, limits.max_parallel_workers, len(workers))) as pool:
        futures = {pool.submit(_candidate_call, w): w for w in workers}
        for future in as_completed(futures):
            worker = futures[future]
            try:
                payload = future.result()
            except Exception as exc:
                observations.append({
                    "step_id": "parallel_candidate",
                    "role": "candidate",
                    "model_id": worker.get("model_id"),
                    "ok": False,
                    "text": "",
                    "latency_ms": 0,
                    "error": str(exc),
                })
                continue
            result = payload["result"]
            obs = {
                "step_id": "parallel_candidate",
                "role": "candidate",
                "model_id": worker.get("model_id"),
                "provider": result.get("provider"),
                "upstream_model": result.get("upstream_model"),
                "ok": result["ok"],
                "text": result.get("text", ""),
                "latency_ms": result.get("latency_ms", 0),
            }
            observations.append(obs)
            if result["ok"] and result.get("text"):
                candidate_outputs.append({
                    "model_id": worker.get("model_id"),
                    "provider": result.get("provider"),
                    "text": result["text"],
                })

    if not candidate_outputs:
        return {
            "mode": "compare",
            "observations": observations,
            "selected_output": "",
            "candidates_collected": 0,
            "success": False,
            "reason": "all_candidates_failed",
        }

    # If only one candidate succeeded, use it directly (no synthesis needed)
    if len(candidate_outputs) == 1 or not synthesizer:
        selected_text = candidate_outputs[0]["text"]
        return {
            "mode": "compare",
            "observations": observations,
            "selected_output": selected_text,
            "candidates_collected": len(candidate_outputs),
            "synthesized": False,
            "success": True,
        }

    # Synthesize
    synth_messages = _build_synthesize_messages(
        original_messages=messages,
        candidate_outputs=candidate_outputs,
    )
    synth_key = get_secret(str(synthesizer.get("subscription_id", "")))
    synth_result = _call_provider(
        worker=synthesizer,
        api_key=synth_key,
        messages=synth_messages,
        temperature=0.2,
        timeout=limits.provider_timeout_seconds,
        budget=budget,
    )
    synth_obs = {
        "step_id": "synthesize",
        "role": synthesizer.get("role"),
        "model_id": synthesizer.get("model_id"),
        "provider": synth_result.get("provider"),
        "upstream_model": synth_result.get("upstream_model"),
        "ok": synth_result["ok"],
        "text": synth_result.get("text", ""),
        "latency_ms": synth_result.get("latency_ms", 0),
    }
    observations.append(synth_obs)
    selected_text = synth_result.get("text", "") if synth_result["ok"] else candidate_outputs[0]["text"]

    return {
        "mode": "compare",
        "observations": observations,
        "selected_output": selected_text,
        "candidates_collected": len(candidate_outputs),
        "synthesized": synth_result["ok"],
        "success": bool(selected_text),
    }


def execute_worker_plan(
    *,
    worker_plan: dict[str, Any],
    messages: list[dict[str, Any]],
    subscriptions: list[dict[str, Any]],
    get_secret: Callable[[str], str],
    limits: RuntimeLimits | None = None,
    budget: CallBudget | None = None,
) -> dict[str, Any]:
    """Execute the resolved worker plan from the coordinator.

    Returns structured observations, selected output, and execution metadata
    suitable for training-data traces.
    """
    mode = str(worker_plan.get("mode") or "direct").strip().lower()
    subscriptions_by_id = {s["id"]: s for s in subscriptions}
    active_limits = (limits or RuntimeLimits()).normalized()
    active_budget = budget or CallBudget(active_limits)

    if mode == "worker_verifier":
        result = _execute_worker_verifier(
            worker_plan=worker_plan,
            messages=messages,
            get_secret=get_secret,
            subscriptions_by_id=subscriptions_by_id,
            limits=active_limits,
            budget=active_budget,
        )
    elif mode == "race":
        result = _execute_race(
            worker_plan=worker_plan,
            messages=messages,
            get_secret=get_secret,
            subscriptions_by_id=subscriptions_by_id,
            limits=active_limits,
            budget=active_budget,
        )
    elif mode == "compare":
        result = _execute_compare(
            worker_plan=worker_plan,
            messages=messages,
            get_secret=get_secret,
            subscriptions_by_id=subscriptions_by_id,
            limits=active_limits,
            budget=active_budget,
        )
    else:
        result = _execute_direct(
            worker_plan=worker_plan,
            messages=messages,
            get_secret=get_secret,
            subscriptions_by_id=subscriptions_by_id,
            limits=active_limits,
            budget=active_budget,
        )
    result["budget"] = active_budget.snapshot()
    return result
