from __future__ import annotations

from typing import Any

from .model_catalog import ModelCatalog


# Policies referenzieren echte Modell-IDs, nicht Provider-Aliase.
# Helmrail resolved dann: "Welche Subscription bietet dieses Modell am besten?"
# Priorität: OpenRouter > Codex/Oracle > Direktanbieter
DEFAULT_ROUTE_POLICIES: dict[str, dict[str, Any]] = {
    "default": {
        "mode": "direct",
        "primary": "gpt-5.5",
        "fallbacks": ["claude-opus-4.6", "gemini-3-pro"],
        "reason": "General requests default to the top LiveBench model (gpt-5.5), with OpenRouter fallbacks.",
    },
    "fast": {
        "mode": "race",
        "candidates": ["glm-5.2", "kimi-k2.7-code", "claude-sonnet-4.6"],
        "reason": "Fast mode races cost-effective models with good coding capability.",
    },
    "cheap": {
        "mode": "direct",
        "primary": "glm-5.2",
        "fallbacks": ["kimi-k2.7-code", "claude-sonnet-4.6"],
        "reason": "Cheap mode prefers Z.ai (glm-5.2) which is extremely cost-effective, then Kimi coding plan.",
    },
    "coding": {
        "mode": "worker_verifier",
        "worker": "gpt-5.5",
        "fallback_worker": "kimi-k2.7-code",
        "verifier": "claude-opus-4.6",
        "reason": "Coding primary: gpt-5.5 (DeepSWE #1). Fallback: kimi-k2.7-code (Kimi Coding Plan). Verifier: claude-opus-4.6 (SWE-bench #4).",
    },
    "reasoning": {
        "mode": "worker_verifier",
        "worker": "gpt-5.5-pro",
        "fallback_worker": "claude-opus-4.6",
        "verifier": "gpt-5.5",
        "reason": "Reasoning primary: gpt-5.5-pro via Oracle (ARC-AGI #1). Fallback: claude-opus-4.6 (Arena #4). Verifier: gpt-5.5.",
    },
    "creative_writing": {
        "mode": "direct",
        "primary": "claude-opus-4.6",
        "fallbacks": ["gemini-3-pro", "gpt-5.5"],
        "reason": "Creative writing primary: claude-opus-4.6 (Arena Creative Writing #2). Fallbacks: gemini-3-pro (#4), gpt-5.5.",
    },
    "high_confidence": {
        "mode": "compare",
        "candidates": ["gpt-5.5", "claude-opus-4.6", "glm-5.2"],
        "synthesizer": "gpt-5.5-pro",
        "reason": "High-confidence mode gathers answers from top models and synthesizes with gpt-5.5-pro (ARC-AGI #1).",
    },
}

CODING_HINTS = (
    "code", "coding", "bug", "debug", "fix", "patch", "repo",
    "test", "pytest", "typescript", "python", "javascript",
    "commit", "diff", "stacktrace", "traceback", "refactor",
)

REASONING_HINTS = (
    "reason", "think", "analyze", "deduce", "logic",
    "prove", "theorem", "argument", "schließen", "folgern",
)

CREATIVE_HINTS = (
    "write", "draft", "copy", "blog", "article", "story",
    "creative", "slogan", "tagline", "headline", "texten",
    "schreiben", "verfassen",
)

FAST_HINTS = ("quick", "fast", "schnell", "kurz", "latency")
CHEAP_HINTS = (
    "cheap", "billig", "cost", "budget", "günstig",
)
HIGH_CONFIDENCE_HINTS = (
    "verify", "review", "prüf", "confidence",
    "sicher", "kritisch", "risk", "double-check",
)


def classify_task(prompt: str, requested: str = "auto") -> str:
    """Determine task type from prompt text or explicit request.
    
    Priority:
    1. Explicit task_type override
    2. Keyword matching (coding > reasoning > creative > high_confidence > cheap > fast)
    3. Default
    """
    explicit = (requested or "auto").strip().lower().replace("-", "_")
    if explicit and explicit != "auto":
        return explicit if explicit in DEFAULT_ROUTE_POLICIES else "default"

    text = (prompt or "").lower()
    if any(hint in text for hint in CODING_HINTS):
        return "coding"
    if any(hint in text for hint in REASONING_HINTS):
        return "reasoning"
    if any(hint in text for hint in CREATIVE_HINTS):
        return "creative_writing"
    if any(hint in text for hint in HIGH_CONFIDENCE_HINTS):
        return "high_confidence"
    if any(hint in text for hint in CHEAP_HINTS):
        return "cheap"
    if any(hint in text for hint in FAST_HINTS):
        return "fast"
    return "default"


# --- Model-to-Subscription Resolution ---

# OpenRouter model ID prefixes for each provider
OPENROUTER_PREFIXES: dict[str, str] = {
    "openai": "openai/",
    "anthropic": "anthropic/",
    "google": "google/",
    "zhipu": "zhipu/",
    "moonshot": "moonshot/",
}


def _openrouter_model_id(model_id: str, provider: str) -> str:
    """Construct the OpenRouter upstream model ID for a given model."""
    prefix = OPENROUTER_PREFIXES.get(provider, "")
    return f"{prefix}{model_id}"


def _subscription_can_serve_model(subscription: dict[str, Any], model_id: str, catalog: ModelCatalog) -> dict[str, Any]:
    """Check if a subscription can serve a model and return resolution info.
    
    Returns:
        dict with 'can_serve' flag and resolution details:
        - upstream_model: The model ID to forward to this subscription
        - route_via: How to reach it (openrouter, codex, oracle, direct)
        - priority: Lower is better (0=openrouter, 1=special.connector, 2=direct)
    """
    model_info = catalog.get_model(model_id)
    if not model_info:
        return {"can_serve": False}
    
    provider = model_info.get("provider", "")
    connector_type = subscription.get("connector_type", "")
    sub_provider = subscription.get("provider", "")
    base_url = subscription.get("base_url", "")
    metadata = subscription.get("metadata", {}) or {}
    
    # 1. OpenRouter: can serve any model
    if sub_provider == "openrouter" and connector_type in ("api_key_env", "api_key_local"):
        upstream = _openrouter_model_id(model_id, provider)
        return {
            "can_serve": True,
            "upstream_model": upstream,
            "route_via": "openrouter",
            "priority": 0,
        }
    
    # 2. Codex CLI: can serve OpenAI models
    if connector_type == "codex_cli" and provider == "openai":
        return {
            "can_serve": True,
            "upstream_model": model_id,
            "route_via": "codex",
            "priority": 1,
        }
    
    # 3. Oracle browser: can serve gpt-5.5-pro
    if connector_type == "oracle_browser" and model_id == "gpt-5.5-pro":
        return {
            "can_serve": True,
            "upstream_model": model_id,
            "route_via": "oracle",
            "priority": 1,
        }
    
    # 4. Direct API: subscription provider matches model provider
    if sub_provider == provider and connector_type in ("api_key_env", "api_key_local"):
        upstream = metadata.get("upstream_model") or model_id
        # Check if model is in the subscription's model_aliases
        aliases = subscription.get("model_aliases", [])
        if aliases:
            # Prefer alias matching model_id exactly
            for alias in aliases:
                clean = alias.replace("helmrail-", "")
                if clean == model_id:
                    return {
                        "can_serve": True,
                        "upstream_model": upstream,
                        "route_via": "direct",
                        "priority": 2,
                    }
            # Otherwise check if any alias maps to this model
            alias_map = metadata.get("model_alias_map", {})
            for alias, mapped in alias_map.items():
                if mapped == model_id or model_id in mapped:
                    return {
                        "can_serve": True,
                        "upstream_model": upstream,
                        "route_via": "direct",
                        "priority": 2,
                    }
        # If subscription has no aliases, it serves its upstream_model
        if not aliases and upstream:
            return {
                "can_serve": True,
                "upstream_model": upstream,
                "route_via": "direct",
                "priority": 2,
            }
    
    # 5. Kimi Coding Plan: can serve kimi-k2.7-code
    if sub_provider == "kimi" and model_id == "kimi-k2.7-code":
        return {
            "can_serve": True,
            "upstream_model": "kimi-k2.7-code",
            "route_via": "direct",
            "priority": 1,
        }
    
    return {"can_serve": False}


def _resolve_model_to_subscription(
    model_id: str,
    subscriptions: list[dict[str, Any]],
    catalog: ModelCatalog,
    readiness: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the best subscription to serve a model.
    
    Priority: OpenRouter (0) > Special connector (1) > Direct (2)
    Among same-priority subscriptions, prefer ready ones.
    
    Returns:
        dict with subscription + resolution info, or None if unavailable
    """
    candidates: list[dict[str, Any]] = []
    
    for subscription in subscriptions:
        if not subscription.get("enabled"):
            continue
        
        result = _subscription_can_serve_model(subscription, model_id, catalog)
        if not result.get("can_serve"):
            continue
        
        probe = readiness.get(subscription["id"], {})
        ready = bool(probe.get("ok", True))
        priority = result.get("priority", 99)
        
        candidates.append({
            "subscription": subscription,
            "upstream_model": result["upstream_model"],
            "route_via": result["route_via"],
            "priority": priority,
            "ready": ready,
            "probe": probe,
        })
    
    if not candidates:
        return None
    
    # Sort: lower priority first, then ready before not-ready
    candidates.sort(key=lambda c: (c["priority"], not c["ready"]))
    
    return candidates[0]


# --- Worker/Plan building ---

def _api_style(subscription: dict[str, Any]) -> str:
    metadata = subscription.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("api_style"):
        return str(metadata["api_style"])
    return "openai_compatible"


def _model_worker(
    *,
    role: str,
    model_id: str,
    subscriptions: list[dict[str, Any]],
    catalog: ModelCatalog,
    readiness: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build a worker record by resolving a model ID to a subscription."""
    
    catalog_entry = catalog.get_model(model_id)
    if catalog_entry is None:
        return {
            "role": role,
            "model_id": model_id,
            "ready": False,
            "status": "unknown_model",
            "reason": f"Model {model_id} not found in catalog.",
        }
    
    resolution = _resolve_model_to_subscription(model_id, subscriptions, catalog, readiness)
    if resolution is None:
        return {
            "role": role,
            "model_id": model_id,
            "catalog_provider": catalog_entry.get("provider", ""),
            "capabilities": catalog_entry.get("capabilities", []),
            "ready": False,
            "status": "no_subscription",
            "reason": f"No enabled subscription can serve {model_id}.",
        }
    
    subscription = resolution["subscription"]
    probe = resolution.get("probe", {})
    ready = resolution["ready"]
    
    return {
        "role": role,
        "model_id": model_id,
        "subscription_id": subscription["id"],
        "subscription_provider": subscription["provider"],
        "account_label": subscription["account_label"],
        "connector_type": subscription["connector_type"],
        "api_style": _api_style(subscription),
        "base_url": subscription.get("base_url", ""),
        "upstream_model": resolution["upstream_model"],
        "route_via": resolution["route_via"],
        "ready": ready,
        "status": str(probe.get("status") or subscription.get("status") or "configured"),
        "reason": str(probe.get("message") or f"{model_id} available via {subscription['provider']} ({resolution['route_via']})."),
        "capabilities": catalog_entry.get("capabilities", []),
    }


def _first_ready(workers: list[dict[str, Any]]) -> dict[str, Any] | None:
    for worker in workers:
        if worker.get("ready"):
            return worker
    return workers[0] if workers else None


def plan_route(
    *,
    subscriptions: list[dict[str, Any]],
    catalog: ModelCatalog,
    prompt: str = "",
    task_type: str = "auto",
    mode: str = "",
    readiness: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    readiness = readiness or {}
    resolved_task = classify_task(prompt, task_type)
    policy = dict(DEFAULT_ROUTE_POLICIES.get(resolved_task) or DEFAULT_ROUTE_POLICIES["default"])
    if mode:
        policy["mode"] = mode.strip().lower().replace("-", "_")
    resolved_mode = str(policy["mode"])

    workers: list[dict[str, Any]] = []
    if resolved_mode == "worker_verifier":
        workers.append(_model_worker(
            role="worker", model_id=str(policy.get("worker") or ""),
            subscriptions=subscriptions, catalog=catalog, readiness=readiness))
        fallback = policy.get("fallback_worker")
        if fallback:
            workers.append(_model_worker(
                role="fallback_worker", model_id=str(fallback),
                subscriptions=subscriptions, catalog=catalog, readiness=readiness))
        verifier = policy.get("verifier")
        if verifier:
            workers.append(_model_worker(
                role="verifier", model_id=str(verifier),
                subscriptions=subscriptions, catalog=catalog, readiness=readiness))
        selected = _first_ready([worker for worker in workers if worker["role"] in {"worker", "fallback_worker"}])
    elif resolved_mode in {"race", "compare"}:
        for model_id in policy.get("candidates") or []:
            workers.append(_model_worker(
                role="candidate", model_id=str(model_id),
                subscriptions=subscriptions, catalog=catalog, readiness=readiness))
        synthesizer = policy.get("synthesizer")
        if synthesizer:
            workers.append(_model_worker(
                role="synthesizer", model_id=str(synthesizer),
                subscriptions=subscriptions, catalog=catalog, readiness=readiness))
        selected = _first_ready([worker for worker in workers if worker["role"] == "candidate"])
    else:
        workers.append(_model_worker(
            role="primary", model_id=str(policy.get("primary") or ""),
            subscriptions=subscriptions, catalog=catalog, readiness=readiness))
        for model_id in policy.get("fallbacks") or []:
            workers.append(_model_worker(
                role="fallback", model_id=str(model_id),
                subscriptions=subscriptions, catalog=catalog, readiness=readiness))
        selected = _first_ready(workers)

    ready_workers = [worker for worker in workers if worker.get("ready")]
    confidence = (
        "high" if selected and selected.get("ready") and len(ready_workers) >= 2
        else "medium" if selected and selected.get("ready")
        else "low"
    )
    return {
        "object": "router.plan",
        "task_type": resolved_task,
        "mode": resolved_mode,
        "selected_worker": selected,
        "workers": workers,
        "ready": bool(selected and selected.get("ready")),
        "confidence": confidence,
        "policy": policy,
        "explanation": policy.get("reason", "Deterministic policy selected from task type and model catalog."),
    }
