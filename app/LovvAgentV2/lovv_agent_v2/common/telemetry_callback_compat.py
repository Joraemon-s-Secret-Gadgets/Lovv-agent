from __future__ import annotations

from typing import Any


def patch_langchain_callback_resume_compat() -> None:
    try:
        from langchain_core.callbacks.base import BaseCallbackHandler
    except ImportError:
        return
    if hasattr(BaseCallbackHandler, "on_resume"):
        return
    setattr(BaseCallbackHandler, "on_resume", _noop_on_resume)


def _noop_on_resume(self: object, value: Any = None, **kwargs: Any) -> None:
    return None


__all__ = ["patch_langchain_callback_resume_compat"]
