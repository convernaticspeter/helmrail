from __future__ import annotations

import os
from dataclasses import dataclass

from .limits import RuntimeLimits


TRUE_VALUES = {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str = "Helmrail"
    version: str = "0.1.0"
    db_path: str = "./data/helmrail.sqlite"
    api_key: str = ""
    require_auth: bool = False
    max_provider_calls: int = 8
    max_parallel_workers: int = 3
    provider_timeout_seconds: int = 120
    max_output_tokens: int = 4096

    def runtime_limits(self) -> RuntimeLimits:
        return RuntimeLimits(
            max_provider_calls=self.max_provider_calls,
            max_parallel_workers=self.max_parallel_workers,
            provider_timeout_seconds=self.provider_timeout_seconds,
            max_output_tokens=self.max_output_tokens,
        ).normalized()

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("HELMRAIL_API_KEY", "")
        require_auth_env = os.getenv("HELMRAIL_REQUIRE_AUTH")
        require_auth = bool(api_key) if require_auth_env is None else require_auth_env.lower() in TRUE_VALUES
        return cls(
            app_name=os.getenv("HELMRAIL_APP_NAME", "Helmrail"),
            version=os.getenv("HELMRAIL_VERSION", "0.1.0"),
            db_path=os.getenv("HELMRAIL_DB_PATH", "./data/helmrail.sqlite"),
            api_key=api_key,
            require_auth=require_auth,
            max_provider_calls=_int_env("HELMRAIL_MAX_PROVIDER_CALLS", 8),
            max_parallel_workers=_int_env("HELMRAIL_MAX_PARALLEL_WORKERS", 3),
            provider_timeout_seconds=_int_env("HELMRAIL_PROVIDER_TIMEOUT_SECONDS", 120),
            max_output_tokens=_int_env("HELMRAIL_MAX_OUTPUT_TOKENS", 4096),
        )
