from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeLimits:
    """Hard safety rails for internal Helmrail provider calls.

    These are intentionally simple caps for local/internal production. They are
    not billing logic; they prevent one API-facing request from silently fanning
    out into an unbounded number of paid upstream calls.
    """

    max_provider_calls: int = 8
    max_parallel_workers: int = 3
    provider_timeout_seconds: int = 120
    max_output_tokens: int = 4096

    def normalized(self) -> "RuntimeLimits":
        return RuntimeLimits(
            max_provider_calls=max(1, min(int(self.max_provider_calls), 32)),
            max_parallel_workers=max(1, min(int(self.max_parallel_workers), 8)),
            provider_timeout_seconds=max(5, min(int(self.provider_timeout_seconds), 600)),
            max_output_tokens=max(256, min(int(self.max_output_tokens), 32768)),
        )


class CallBudget:
    def __init__(self, limits: RuntimeLimits | None = None) -> None:
        self.limits = (limits or RuntimeLimits()).normalized()
        self._used = 0
        self._blocked = 0
        self._lock = threading.Lock()

    def reserve(self) -> bool:
        with self._lock:
            if self._used >= self.limits.max_provider_calls:
                self._blocked += 1
                return False
            self._used += 1
            return True

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.limits.max_provider_calls - self._used)

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "provider_calls_used": self._used,
                "provider_calls_blocked": self._blocked,
                "max_provider_calls": self.limits.max_provider_calls,
                "max_parallel_workers": self.limits.max_parallel_workers,
                "provider_timeout_seconds": self.limits.provider_timeout_seconds,
                "max_output_tokens": self.limits.max_output_tokens,
                "exhausted": self._used >= self.limits.max_provider_calls,
            }


def _clamped_positive_int(value: Any, cap: int) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = cap
    return max(1, min(requested, cap))


def apply_openai_output_cap(payload: dict[str, Any], max_output_tokens: int) -> dict[str, Any]:
    """Clamp OpenAI-compatible output-token knobs in-place and return payload.

    Some providers default to very high completion limits when the client omits
    max_tokens. That can turn a tiny internal canary into a credit-limit error,
    so Helmrail always sends a bounded output cap unless the caller supplied a
    smaller one.
    """
    cap = RuntimeLimits(max_output_tokens=max_output_tokens).normalized().max_output_tokens
    if payload.get("max_completion_tokens") is not None:
        payload["max_completion_tokens"] = _clamped_positive_int(payload.get("max_completion_tokens"), cap)
    elif payload.get("max_tokens") is not None:
        payload["max_tokens"] = _clamped_positive_int(payload.get("max_tokens"), cap)
    else:
        payload["max_tokens"] = cap
    return payload


def budget_exhausted_result(*, provider: str = "", upstream_model: str = "") -> dict[str, object]:
    return {
        "ok": False,
        "status_code": 429,
        "error": "Provider call budget exhausted for this request.",
        "text": "",
        "latency_ms": 0,
        "provider": provider,
        "upstream_model": upstream_model,
        "budget_exhausted": True,
    }
