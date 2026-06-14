"""Adapter namespace for provider/runtime integration boundaries."""

from __future__ import annotations

ADAPTER_MODULES: tuple[str, ...] = (
    "bedrock_converse",
    "aws_clients",
    "embeddings",
)

__all__ = ["ADAPTER_MODULES"]
