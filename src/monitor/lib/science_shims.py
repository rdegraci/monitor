"""Local shims for scientific optional dependencies."""
from __future__ import annotations

from typing import Any


def _load_module(module_name: str) -> Any:
    """Import an optional module and return None if unavailable."""
    try:
        return __import__(module_name, fromlist=["*"])
    except Exception:
        return None


pandas: Any = _load_module("pandas")
sklearn_preprocessing: Any = _load_module("sklearn.preprocessing")
sklearn_ensemble: Any = _load_module("sklearn.ensemble")
sklearn_linear_model: Any = _load_module("sklearn.linear_model")
sklearn_metrics: Any = _load_module("sklearn.metrics")
sklearn_model_selection: Any = _load_module("sklearn.model_selection")
