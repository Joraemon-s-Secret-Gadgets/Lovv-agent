"""Lovv LangGraph agent package.

This package is intentionally import-safe: importing ``lovv_agent`` must not
create AWS clients, call LLM providers, read credentials, or compile a runtime
graph. Concrete runtime wiring is added in later Tasks through injected
adapters.
"""

from __future__ import annotations

# 패키지 import에는 부수효과를 두지 않고 런타임 wiring은 harness에서 시작한다.
__version__ = "0.1.0"

__all__ = ["__version__"]
