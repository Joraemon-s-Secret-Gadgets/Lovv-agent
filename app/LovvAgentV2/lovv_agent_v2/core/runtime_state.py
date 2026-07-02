from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def runtime_value(state: Mapping[str, Any], key: str) -> Any | None:
    runtime = state.get("runtime")
    if isinstance(runtime, Mapping):
        return runtime.get(key)
    if runtime is None:
        return None
    return getattr(runtime, key, None)


__all__ = ["runtime_value"]
