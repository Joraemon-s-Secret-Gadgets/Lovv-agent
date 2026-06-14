"""Repository namespace for external data sources."""

from __future__ import annotations

REPOSITORY_MODULES: tuple[str, ...] = (
    "dynamodb",
    "s3_vectors",
)

__all__ = ["REPOSITORY_MODULES"]
