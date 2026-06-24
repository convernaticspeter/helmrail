from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .limits import RuntimeLimits

ModelRoute = Literal["direct", "coordinator"]


@dataclass(frozen=True)
class VisibleModelProfile:
    id: str
    route: ModelRoute
    tier: str
    description: str
    limits: RuntimeLimits


DEFAULT_LIMITS = RuntimeLimits().normalized()
ULTRA_LIMITS = RuntimeLimits(
    max_provider_calls=24,
    max_parallel_workers=4,
    provider_timeout_seconds=180,
    max_output_tokens=32768,
).normalized()

VISIBLE_MODEL_PROFILES: dict[str, VisibleModelProfile] = {
    "helmrail-fast": VisibleModelProfile(
        id="helmrail-fast",
        route="direct",
        tier="fast",
        description="Low-latency Helmrail alias; direct provider fallback with standard request limits.",
        limits=DEFAULT_LIMITS,
    ),
    "helmrail-standard": VisibleModelProfile(
        id="helmrail-standard",
        route="coordinator",
        tier="standard",
        description="Standard Helmrail model: hidden coordinator and worker routing with standard cost/latency budget.",
        limits=DEFAULT_LIMITS,
    ),
    "helmrail-coordinator": VisibleModelProfile(
        id="helmrail-coordinator",
        route="coordinator",
        tier="standard",
        description="Alias for helmrail-standard.",
        limits=DEFAULT_LIMITS,
    ),
    "helmrail-auto": VisibleModelProfile(
        id="helmrail-auto",
        route="coordinator",
        tier="standard",
        description="Alias for helmrail-standard.",
        limits=DEFAULT_LIMITS,
    ),
    "helmrail-ultra": VisibleModelProfile(
        id="helmrail-ultra",
        route="coordinator",
        tier="ultra",
        description="Ultra Helmrail model: larger hidden-agent budget for bootstraps, complex coding, and high-stakes synthesis.",
        limits=ULTRA_LIMITS,
    ),
}


def visible_model_profile(model: str) -> VisibleModelProfile | None:
    return VISIBLE_MODEL_PROFILES.get(model)


def is_coordinator_model(model: str) -> bool:
    profile = visible_model_profile(model)
    return bool(profile and profile.route == "coordinator")


def _profile_or_configured(configured: int, default: int, profile_value: int) -> int:
    # Explicit env/admin settings win. Profile values apply only when the global
    # setting is still at the built-in default.
    return profile_value if configured == default else configured


def limits_for_visible_model(base_limits: RuntimeLimits, model: str) -> RuntimeLimits:
    base = base_limits.normalized()
    profile = visible_model_profile(model)
    if profile is None:
        return base
    profile_limits = profile.limits.normalized()
    default = DEFAULT_LIMITS
    return RuntimeLimits(
        max_provider_calls=_profile_or_configured(
            base.max_provider_calls, default.max_provider_calls, profile_limits.max_provider_calls
        ),
        max_parallel_workers=_profile_or_configured(
            base.max_parallel_workers, default.max_parallel_workers, profile_limits.max_parallel_workers
        ),
        provider_timeout_seconds=_profile_or_configured(
            base.provider_timeout_seconds, default.provider_timeout_seconds, profile_limits.provider_timeout_seconds
        ),
        max_output_tokens=_profile_or_configured(
            base.max_output_tokens, default.max_output_tokens, profile_limits.max_output_tokens
        ),
    ).normalized()


def public_model_profile_summaries() -> list[dict[str, object]]:
    return [
        {
            "id": profile.id,
            "tier": profile.tier,
            "route": profile.route,
            "limits": profile.limits.__dict__,
        }
        for profile in VISIBLE_MODEL_PROFILES.values()
    ]


def public_model_profiles(created: int) -> list[dict[str, object]]:
    return [
        {
            "id": profile.id,
            "object": "model",
            "created": created,
            "owned_by": "helmrail",
            "description": profile.description,
            "helmrail_profile": {
                "tier": profile.tier,
                "route": profile.route,
                "limits": profile.limits.__dict__,
            },
        }
        for profile in VISIBLE_MODEL_PROFILES.values()
    ]
