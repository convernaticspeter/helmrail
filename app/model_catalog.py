"""Model catalog loader for benchmark-grounded routing decisions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ModelCatalog:
    """In-memory catalog of models, capabilities, and task profiles."""

    def __init__(self, catalog_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path)
        self._catalog: dict[str, Any] = {}
        self._models: dict[str, dict[str, Any]] = {}
        self._task_profiles: dict[str, dict[str, Any]] = {}
        self._capability_taxonomy: dict[str, list[str]] = {}
        self._by_capability: dict[str, list[str]] = {}
        self._reload()

    def _reload(self) -> None:
        """Load and index the YAML catalog."""
        if not self.catalog_path.exists():
            self._catalog = {"metadata": {}, "models": {}, "task_profiles": {}, "capability_taxonomy": {}}
            self._models = {}
            self._task_profiles = {}
            self._capability_taxonomy = {}
            self._by_capability = {}
            return

        with open(self.catalog_path, "r", encoding="utf-8") as f:
            self._catalog = yaml.safe_load(f) or {"metadata": {}, "models": {}, "task_profiles": {}, "capability_taxonomy": {}}

        self._models = self._catalog.get("models", {}) or {}
        self._task_profiles = self._catalog.get("task_profiles", {}) or {}
        self._capability_taxonomy = self._catalog.get("capability_taxonomy", {}) or {}

        # Build capability index from model capabilities.
        self._by_capability = {}
        for model_id, model_info in self._models.items():
            capabilities = model_info.get("capabilities", []) or []
            for cap in capabilities:
                self._by_capability.setdefault(str(cap), []).append(str(model_id))

    def reload(self) -> None:
        """Reload catalog from disk (for hot-reload during development)."""
        self._reload()

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        """Get model info by ID."""
        return self._models.get(model_id)

    def has_capability(self, model_id: str, capability: str) -> bool:
        """Check if a model has a specific capability."""
        model = self._models.get(model_id)
        if not model:
            return False
        return capability in (model.get("capabilities", []) or [])

    def models_with_capability(self, capability: str) -> list[str]:
        """Get all model IDs that have a capability, ordered by benchmark rank."""
        models = self._by_capability.get(capability, [])

        # Sort by benchmark score (higher is better) or rank (lower is better).
        def score_key(model_id: str) -> float:
            model = self._models.get(model_id, {})
            benchmarks = model.get("benchmarks", {}) or {}
            for _, bench_data in benchmarks.items():
                if isinstance(bench_data, dict):
                    if "score" in bench_data:
                        return -float(bench_data["score"])
                    if "rank" in bench_data:
                        return float(bench_data["rank"])
            return float("inf")

        return sorted(models, key=score_key)

    def best_model_for_capability(
        self, capability: str, available_models: set[str] | None = None
    ) -> str | None:
        """Get the best model for a capability from available models."""
        candidates = self.models_with_capability(capability)
        if available_models is not None:
            candidates = [m for m in candidates if m in available_models]
        return candidates[0] if candidates else None

    def get_task_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Get a task profile by ID."""
        return self._task_profiles.get(profile_id)

    def list_task_profiles(self) -> list[dict[str, Any]]:
        """Return task profiles as API-friendly objects."""
        profiles: list[dict[str, Any]] = []
        for profile_id, profile in self._task_profiles.items():
            profiles.append({"id": profile_id, **profile})
        return profiles

    def match_task_profile(self, prompt: str) -> str | None:
        """Keyword-match a prompt to the best task profile.

        This intentionally stays deterministic and cheap. It is not a semantic
        classifier; upstream callers can always override with task_type.
        """
        text = (prompt or "").lower()
        if not text:
            return None

        best_profile: str | None = None
        best_score = 0
        best_priority = -1
        for profile_id, profile in self._task_profiles.items():
            keywords = profile.get("keywords", []) or []
            score = 0
            for keyword in keywords:
                kw = str(keyword).strip().lower()
                if kw and kw in text:
                    # Multi-word phrases are more specific than single tokens.
                    score += 3 if " " in kw else 1
            if score <= 0:
                continue
            priority = int(profile.get("priority", 0) or 0)
            if score > best_score or (score == best_score and priority > best_priority):
                best_profile = str(profile_id)
                best_score = score
                best_priority = priority
        return best_profile

    def get_capability_taxonomy(self) -> dict[str, list[str]]:
        """Get the curated capability taxonomy."""
        return self._capability_taxonomy

    def get_metadata(self) -> dict[str, Any]:
        """Get catalog metadata."""
        return self._catalog.get("metadata", {}) or {}

    def list_models(self) -> list[str]:
        """Get all model IDs in the catalog."""
        return list(self._models.keys())

    def list_capabilities(self) -> list[str]:
        """Get all unique model-level capabilities."""
        return list(self._by_capability.keys())


def load_catalog(catalog_path: str | Path | None = None) -> ModelCatalog:
    """Load the model catalog from the default or specified path."""
    if catalog_path is None:
        catalog_path = Path(__file__).parent.parent / "data" / "model_catalog.yaml"
    return ModelCatalog(catalog_path)
