"""Model catalog loader for benchmark-grounded routing decisions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ModelCatalog:
    """In-memory catalog of models with capabilities and benchmarks."""
    
    def __init__(self, catalog_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path)
        self._catalog: dict[str, Any] = {}
        self._models: dict[str, dict[str, Any]] = {}
        self._by_capability: dict[str, list[str]] = {}
        self._reload()
    
    def _reload(self) -> None:
        """Load and index the YAML catalog."""
        if not self.catalog_path.exists():
            self._catalog = {"metadata": {}, "models": {}}
            self._models = {}
            self._by_capability = {}
            return
        
        with open(self.catalog_path, "r", encoding="utf-8") as f:
            self._catalog = yaml.safe_load(f) or {"metadata": {}, "models": {}}
        
        self._models = self._catalog.get("models", {})
        
        # Build capability index
        self._by_capability = {}
        for model_id, model_info in self._models.items():
            capabilities = model_info.get("capabilities", [])
            for cap in capabilities:
                if cap not in self._by_capability:
                    self._by_capability[cap] = []
                self._by_capability[cap].append(model_id)
    
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
        return capability in model.get("capabilities", [])
    
    def models_with_capability(self, capability: str) -> list[str]:
        """Get all model IDs that have a capability, ordered by benchmark rank."""
        models = self._by_capability.get(capability, [])
        
        # Sort by benchmark score (higher is better) or rank (lower is better)
        def score_key(model_id: str) -> float:
            model = self._models.get(model_id, {})
            benchmarks = model.get("benchmarks", {})
            
            # Try to find a relevant score/rank
            for bench_name, bench_data in benchmarks.items():
                if isinstance(bench_data, dict):
                    if "score" in bench_data:
                        return -bench_data["score"]  # Negative for descending sort
                    if "rank" in bench_data:
                        return bench_data["rank"]
            return float("inf")
        
        return sorted(models, key=score_key)
    
    def best_model_for_capability(
        self, capability: str, available_models: set[str] | None = None
    ) -> str | None:
        """Get the best model for a capability from available models.
        
        Args:
            capability: The capability to optimize for (e.g., "coding", "reasoning")
            available_models: Set of model IDs that are currently available
            
        Returns:
            Best model ID or None if no models available
        """
        candidates = self.models_with_capability(capability)
        
        if available_models is not None:
            candidates = [m for m in candidates if m in available_models]
        
        return candidates[0] if candidates else None
    
    def get_metadata(self) -> dict[str, Any]:
        """Get catalog metadata."""
        return self._catalog.get("metadata", {})
    
    def list_models(self) -> list[str]:
        """Get all model IDs in the catalog."""
        return list(self._models.keys())
    
    def list_capabilities(self) -> list[str]:
        """Get all unique capabilities."""
        return list(self._by_capability.keys())


def load_catalog(catalog_path: str | Path | None = None) -> ModelCatalog:
    """Load the model catalog from the default or specified path.
    
    Args:
        catalog_path: Path to catalog YAML. If None, uses default location.
        
    Returns:
        ModelCatalog instance
    """
    if catalog_path is None:
        catalog_path = Path(__file__).parent.parent / "data" / "model_catalog.yaml"
    
    return ModelCatalog(catalog_path)
