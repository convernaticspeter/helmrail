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


def classify_task(prompt: str, requested: str = "auto", catalog: ModelCatalog | None = None) -> str:
    """Determine task type from prompt text or explicit request.

    Priority:
    1. Explicit task_type override (built-in policy or catalog task profile)
    2. Catalog task-profile keyword matching
    3. Built-in generic keyword matching
    4. Default
    """
    explicit = (requested or "auto").strip().lower().replace("-", "_")
    if explicit and explicit != "auto":
        if explicit in DEFAULT_ROUTE_POLICIES:
            return explicit
        if catalog and catalog.get_task_profile(explicit):
            return explicit
        return "default"

    text = (prompt or "").lower()
    if catalog:
        matched_profile = catalog.match_task_profile(text)
        if matched_profile:
            return matched_profile

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


def _policy_from_task_profile(profile_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    """Build an executable route policy from a catalog task profile."""
    mode = str(profile.get("mode") or "direct").strip().lower().replace("-", "_")
    primary_models = [str(model) for model in (profile.get("primary_models") or []) if str(model).strip()]
    fallback_models = [str(model) for model in (profile.get("fallback_models") or []) if str(model).strip()]
    verifier_models = [str(model) for model in (profile.get("verifier_models") or []) if str(model).strip()]

    policy: dict[str, Any] = {
        "mode": mode,
        "task_profile_id": profile_id,
        "label": profile.get("label", profile_id),
        "domain": profile.get("domain", ""),
        "required_capabilities": profile.get("required_capabilities", []),
        "helpful_capabilities": profile.get("helpful_capabilities", []),
        "evidence_level": profile.get("evidence_level", "heuristic_domain_profile"),
        "reason": profile.get("reason") or f"Task profile '{profile_id}' selected from catalog taxonomy.",
    }

    if mode == "worker_verifier":
        policy["worker"] = primary_models[0] if primary_models else "gpt-5.5"
        if fallback_models:
            policy["fallback_worker"] = fallback_models[0]
        if verifier_models:
            policy["verifier"] = verifier_models[0]
    elif mode in {"race", "compare"}:
        candidates = [*primary_models, *fallback_models]
        policy["candidates"] = candidates or ["gpt-5.5", "claude-opus-4.6"]
        if verifier_models:
            policy["synthesizer"] = verifier_models[0]
    else:
        policy["primary"] = primary_models[0] if primary_models else "gpt-5.5"
        policy["fallbacks"] = [*primary_models[1:], *fallback_models]
        if verifier_models:
            policy["verifier"] = verifier_models[0]
    return policy


def _policy_for_task(task_type: str, catalog: ModelCatalog) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve task type to a route policy and optional task-profile metadata."""
    if task_type in DEFAULT_ROUTE_POLICIES:
        return dict(DEFAULT_ROUTE_POLICIES[task_type]), None

    profile = catalog.get_task_profile(task_type)
    if profile:
        return _policy_from_task_profile(task_type, profile), {"id": task_type, **profile}

    return dict(DEFAULT_ROUTE_POLICIES["default"]), None


DOMAIN_TOOL_AFFINITY: dict[str, list[str]] = {
    "architecture": ["repo_inspection", "terminal", "web_research", "diagramming"],
    "development": ["repo_inspection", "terminal", "test_runner", "browser_qa"],
    "design": ["browser_qa", "vision_review", "frontend_inspection", "design_reference_search"],
    "growth_marketing": ["web_research", "browser_qa", "analytics_review", "copy_archive"],
    "analytics": ["analytics_api", "tag_manager", "browser_devtools", "repo_inspection"],
    "paid_media": ["ads_platform_api", "analytics_api", "landing_page_review", "web_research"],
    "organic_social": ["platform_search", "trend_research", "content_calendar", "web_research"],
    "content": ["web_research", "content_calendar", "source_review"],
    "research": ["web_search", "source_verification", "archive_search", "data_extraction"],
    "automation": ["browser_control", "browser_qa", "form_fill", "navigation"],
}

CAPABILITY_TOOL_AFFINITY: dict[str, list[str]] = {
    "backend_development": ["terminal", "test_runner", "api_client"],
    "frontend_development": ["browser_qa", "terminal", "screenshot_review"],
    "browser_automation": ["browser_control", "browser_qa", "form_fill", "navigation", "screenshot_review"],
    "conversion_tracking_setup": ["tag_manager", "browser_devtools", "network_inspector"],
    "analytics_instrumentation": ["analytics_api", "event_debugger"],
    "google_ads": ["google_ads_api", "keyword_planner", "search_terms_report"],
    "meta_ads": ["meta_ads_api", "creative_library", "analytics_api"],
    "bing_ads": ["microsoft_ads_api", "keyword_planner"],
    "tiktok_ads": ["tiktok_ads_api", "creative_center"],
    "osint": ["dns_lookup", "whois", "web_search", "archive_search"],
    "market_research_forums": ["reddit_search", "forum_search", "voice_of_customer_extraction"],
    "scientific_research": ["paper_search", "citation_review", "pdf_extraction"],
    "journalistic_research": ["source_verification", "archive_search", "fact_checking"],
}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _capability_weights(profile: dict[str, Any] | None) -> dict[str, float]:
    """Return normalized capability weights for a task profile."""
    if not profile:
        return {}

    explicit = profile.get("capability_weights")
    if isinstance(explicit, dict) and explicit:
        parsed: dict[str, float] = {}
        for capability, raw_weight in explicit.items():
            weight = float(raw_weight)
            if weight > 0:
                parsed[str(capability)] = weight
        total = sum(parsed.values())
        if total > 0:
            return {
                capability: round(weight / total, 4)
                for capability, weight in sorted(parsed.items(), key=lambda item: item[1], reverse=True)
            }

    required = _dedupe([str(cap) for cap in (profile.get("required_capabilities") or [])])
    helpful = [cap for cap in _dedupe([str(cap) for cap in (profile.get("helpful_capabilities") or [])]) if cap not in required]
    if not required and not helpful:
        return {}

    required_pool = 0.7 if helpful else 1.0
    helpful_pool = 0.3 if required else 1.0
    weights: dict[str, float] = {}
    if required:
        for capability in required:
            weights[capability] = weights.get(capability, 0.0) + required_pool / len(required)
    if helpful:
        for capability in helpful:
            weights[capability] = weights.get(capability, 0.0) + helpful_pool / len(helpful)
    return {
        capability: round(weight, 4)
        for capability, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True)
    }


def _tool_affinity(profile: dict[str, Any] | None) -> list[str]:
    """Return tool/integration affinities for a profile.

    These are descriptive capabilities, not commands to execute. An orchestrator
    can later map them to concrete Hermes toolsets, MCP tools, or platform APIs.
    """
    if not profile:
        return []

    tools: list[str] = []
    explicit = profile.get("tool_affinity")
    if isinstance(explicit, list):
        tools.extend(str(tool) for tool in explicit)

    domain = str(profile.get("domain") or "")
    tools.extend(DOMAIN_TOOL_AFFINITY.get(domain, []))
    for capability in [*(profile.get("required_capabilities") or []), *(profile.get("helpful_capabilities") or [])]:
        tools.extend(CAPABILITY_TOOL_AFFINITY.get(str(capability), []))
    return _dedupe(tools)


def _worker_ref(worker: dict[str, Any] | None) -> dict[str, Any] | None:
    if not worker:
        return None
    return {
        "role": worker.get("role"),
        "model_id": worker.get("model_id"),
        "route_via": worker.get("route_via"),
        "ready": bool(worker.get("ready")),
        "status": worker.get("status"),
    }


def _orchestration_steps(
    *,
    policy: dict[str, Any],
    task_profile: dict[str, Any] | None,
    workers: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    """Build executable-ish orchestration steps from the route policy.

    This stays plan-only: no provider calls, no tool calls, no side effects.
    """
    by_role = {str(worker.get("role")): worker for worker in workers}
    required = list((task_profile or {}).get("required_capabilities") or policy.get("required_capabilities") or [])
    helpful = list((task_profile or {}).get("helpful_capabilities") or policy.get("helpful_capabilities") or [])
    primary_caps = required or ["general"]

    if mode == "worker_verifier":
        steps: list[dict[str, Any]] = [
            {
                "id": "scope",
                "type": "analysis",
                "worker": _worker_ref(by_role.get("worker")),
                "capabilities": primary_caps[:3],
                "purpose": "Clarify inputs, constraints, success criteria, and likely failure modes.",
            },
            {
                "id": "produce",
                "type": "work",
                "worker": _worker_ref(by_role.get("worker")),
                "capabilities": primary_caps,
                "purpose": "Produce the primary artifact or technical plan for the task profile.",
            },
        ]
        fallback = by_role.get("fallback_worker")
        if fallback:
            steps.append({
                "id": "fallback_produce",
                "type": "fallback",
                "worker": _worker_ref(fallback),
                "capabilities": primary_caps,
                "condition": "Run if the primary worker is unavailable, low-confidence, or fails verification.",
                "purpose": "Produce an alternate candidate through the fallback model.",
            })
        verifier = by_role.get("verifier")
        if verifier:
            steps.append({
                "id": "verify",
                "type": "verification",
                "worker": _worker_ref(verifier),
                "capabilities": _dedupe([*helpful, "reasoning", "risk_review"]),
                "purpose": "Check correctness, risks, missing context, and produce a final synthesis.",
            })
        return steps

    if mode in {"race", "compare"}:
        steps = []
        for idx, worker in enumerate([worker for worker in workers if worker.get("role") == "candidate"], start=1):
            steps.append({
                "id": f"candidate_{idx}",
                "type": "parallel_candidate",
                "worker": _worker_ref(worker),
                "capabilities": primary_caps,
                "purpose": "Generate an independent candidate answer for comparison.",
            })
        synthesizer = by_role.get("synthesizer")
        if synthesizer:
            steps.append({
                "id": "synthesize",
                "type": "synthesis",
                "worker": _worker_ref(synthesizer),
                "capabilities": _dedupe([*helpful, "reasoning", "decision_quality"]),
                "purpose": "Compare candidates, resolve conflicts, and synthesize the final answer.",
            })
        return steps

    steps = [
        {
            "id": "execute",
            "type": "work",
            "worker": _worker_ref(by_role.get("primary")),
            "capabilities": primary_caps,
            "purpose": "Execute the task directly with the selected primary model.",
        }
    ]
    verifier = by_role.get("verifier")
    if verifier:
        steps.append({
            "id": "review",
            "type": "verification",
            "worker": _worker_ref(verifier),
            "capabilities": _dedupe([*helpful, "reasoning", "quality_review"]),
            "purpose": "Review direct output before final delivery when confidence requirements justify it.",
        })
    return steps


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
    resolved_task = classify_task(prompt, task_type, catalog=catalog)
    policy, task_profile = _policy_for_task(resolved_task, catalog)
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
        verifier = policy.get("verifier")
        if verifier:
            workers.append(_model_worker(
                role="verifier", model_id=str(verifier),
                subscriptions=subscriptions, catalog=catalog, readiness=readiness))
        selected = _first_ready([worker for worker in workers if worker["role"] in {"primary", "fallback"}])

    ready_workers = [worker for worker in workers if worker.get("ready")]
    confidence = (
        "high" if selected and selected.get("ready") and len(ready_workers) >= 2
        else "medium" if selected and selected.get("ready")
        else "low"
    )
    capability_weights = _capability_weights(task_profile)
    tool_affinity = _tool_affinity(task_profile)
    orchestration_steps = _orchestration_steps(
        policy=policy,
        task_profile=task_profile,
        workers=workers,
        mode=resolved_mode,
    )
    return {
        "object": "router.plan",
        "task_type": resolved_task,
        "mode": resolved_mode,
        "selected_worker": selected,
        "workers": workers,
        "ready": bool(selected and selected.get("ready")),
        "confidence": confidence,
        "capability_weights": capability_weights,
        "tool_affinity": tool_affinity,
        "orchestration_steps": orchestration_steps,
        "policy": policy,
        "task_profile": task_profile,
        "explanation": policy.get("reason", "Deterministic policy selected from task type and model catalog."),
    }
