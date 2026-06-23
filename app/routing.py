from __future__ import annotations

from typing import Any


DEFAULT_ROUTE_POLICIES: dict[str, dict[str, Any]] = {
    "default": {
        "mode": "direct",
        "primary": "helmrail-openrouter",
        "fallbacks": ["helmrail-zai", "helmrail-kimi"],
        "reason": "General requests default to the broadest OpenAI-compatible router, with direct API fallbacks.",
    },
    "fast": {
        "mode": "race",
        "candidates": ["helmrail-zai", "helmrail-kimi", "helmrail-openrouter"],
        "reason": "Fast mode races multiple healthy direct API workers and can return the first acceptable answer.",
    },
    "cheap": {
        "mode": "direct",
        "primary": "helmrail-zai",
        "fallbacks": ["helmrail-kimi", "helmrail-openrouter"],
        "reason": "Cheap mode prefers direct coding-plan API capacity before broader router capacity.",
    },
    "coding": {
        "mode": "worker_verifier",
        "worker": "helmrail-codex",
        "fallback_worker": "helmrail-kimi",
        "verifier": "helmrail-openrouter",
        "reason": "Coding mode prefers the subscription Codex connector, falls back to Kimi Coding, and verifies through a different provider.",
    },
    "high_confidence": {
        "mode": "compare",
        "candidates": ["helmrail-openrouter", "helmrail-zai", "helmrail-kimi"],
        "synthesizer": "helmrail-openrouter",
        "reason": "High-confidence mode gathers independent answers and lets a synthesizer reconcile disagreements.",
    },
}

CODING_HINTS = (
    "code",
    "coding",
    "bug",
    "debug",
    "fix",
    "patch",
    "repo",
    "test",
    "pytest",
    "typescript",
    "python",
    "javascript",
    "commit",
    "diff",
    "stacktrace",
    "traceback",
)

FAST_HINTS = ("quick", "fast", "schnell", "kurz", "latency")
CHEAP_HINTS = ("cheap", "billig", "kost", "budget")
HIGH_CONFIDENCE_HINTS = ("verify", "review", "prüf", "confidence", "sicher", "kritisch", "risk")


def classify_task(prompt: str, requested: str = "auto") -> str:
    explicit = (requested or "auto").strip().lower().replace("-", "_")
    if explicit and explicit != "auto":
        return explicit if explicit in DEFAULT_ROUTE_POLICIES else "default"

    text = (prompt or "").lower()
    if any(hint in text for hint in CODING_HINTS):
        return "coding"
    if any(hint in text for hint in HIGH_CONFIDENCE_HINTS):
        return "high_confidence"
    if any(hint in text for hint in CHEAP_HINTS):
        return "cheap"
    if any(hint in text for hint in FAST_HINTS):
        return "fast"
    return "default"


def _alias_index(subscriptions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for subscription in subscriptions:
        if not subscription.get("enabled"):
            continue
        for alias in subscription.get("model_aliases") or []:
            index[str(alias)] = subscription
    return index


def _api_style(subscription: dict[str, Any]) -> str:
    metadata = subscription.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("api_style"):
        return str(metadata["api_style"])
    return "openai_compatible"


def _upstream_model(subscription: dict[str, Any], alias: str) -> str:
    metadata = subscription.get("metadata") or {}
    alias_map = metadata.get("model_alias_map") if isinstance(metadata, dict) else None
    if isinstance(alias_map, dict):
        mapped = alias_map.get(alias)
        if isinstance(mapped, str) and mapped.strip():
            return mapped.strip()
    upstream = metadata.get("upstream_model") if isinstance(metadata, dict) else None
    if isinstance(upstream, str) and upstream.strip() and alias.startswith("helmrail-"):
        return upstream.strip()
    return alias


def _worker(
    *,
    role: str,
    alias: str,
    aliases: dict[str, dict[str, Any]],
    readiness: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    subscription = aliases.get(alias)
    if subscription is None:
        return {
            "role": role,
            "alias": alias,
            "ready": False,
            "status": "missing_alias",
            "reason": f"No enabled subscription exposes {alias}.",
        }

    probe = readiness.get(subscription["id"], {})
    ready = bool(probe.get("ok", True))
    return {
        "role": role,
        "alias": alias,
        "subscription_id": subscription["id"],
        "provider": subscription["provider"],
        "account_label": subscription["account_label"],
        "connector_type": subscription["connector_type"],
        "api_style": _api_style(subscription),
        "base_url": subscription.get("base_url", ""),
        "upstream_model": _upstream_model(subscription, alias),
        "ready": ready,
        "status": str(probe.get("status") or subscription.get("status") or "configured"),
        "reason": str(probe.get("message") or "Enabled subscription is available for routing."),
    }


def _first_ready(workers: list[dict[str, Any]]) -> dict[str, Any] | None:
    for worker in workers:
        if worker.get("ready"):
            return worker
    return workers[0] if workers else None


def plan_route(
    *,
    subscriptions: list[dict[str, Any]],
    prompt: str = "",
    task_type: str = "auto",
    mode: str = "",
    readiness: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    readiness = readiness or {}
    aliases = _alias_index(subscriptions)
    resolved_task = classify_task(prompt, task_type)
    policy = dict(DEFAULT_ROUTE_POLICIES.get(resolved_task) or DEFAULT_ROUTE_POLICIES["default"])
    if mode:
        policy["mode"] = mode.strip().lower().replace("-", "_")
    resolved_mode = str(policy["mode"])

    workers: list[dict[str, Any]] = []
    if resolved_mode == "worker_verifier":
        workers.append(_worker(role="worker", alias=str(policy.get("worker") or ""), aliases=aliases, readiness=readiness))
        fallback = policy.get("fallback_worker")
        if fallback:
            workers.append(_worker(role="fallback_worker", alias=str(fallback), aliases=aliases, readiness=readiness))
        verifier = policy.get("verifier")
        if verifier:
            workers.append(_worker(role="verifier", alias=str(verifier), aliases=aliases, readiness=readiness))
        selected = _first_ready([worker for worker in workers if worker["role"] in {"worker", "fallback_worker"}])
    elif resolved_mode in {"race", "compare"}:
        for alias in policy.get("candidates") or []:
            workers.append(_worker(role="candidate", alias=str(alias), aliases=aliases, readiness=readiness))
        synthesizer = policy.get("synthesizer")
        if synthesizer:
            workers.append(_worker(role="synthesizer", alias=str(synthesizer), aliases=aliases, readiness=readiness))
        selected = _first_ready([worker for worker in workers if worker["role"] == "candidate"])
    else:
        workers.append(_worker(role="primary", alias=str(policy.get("primary") or ""), aliases=aliases, readiness=readiness))
        for alias in policy.get("fallbacks") or []:
            workers.append(_worker(role="fallback", alias=str(alias), aliases=aliases, readiness=readiness))
        selected = _first_ready(workers)

    ready_workers = [worker for worker in workers if worker.get("ready")]
    confidence = "high" if selected and selected.get("ready") and len(ready_workers) >= 2 else "medium" if selected and selected.get("ready") else "low"
    return {
        "object": "router.plan",
        "task_type": resolved_task,
        "mode": resolved_mode,
        "selected_worker": selected,
        "workers": workers,
        "ready": bool(selected and selected.get("ready")),
        "confidence": confidence,
        "policy": policy,
        "explanation": policy.get("reason", "Deterministic policy selected from task type and enabled subscription aliases."),
    }
