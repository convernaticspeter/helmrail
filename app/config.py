from __future__ import annotations

import os
from dataclasses import dataclass


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Helmrail"
    version: str = "0.1.0"
    db_path: str = "./data/helmrail.sqlite"
    api_key: str = ""
    require_auth: bool = False

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
        )
