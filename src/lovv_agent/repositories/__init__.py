"""Repository namespace for external data sources."""

from __future__ import annotations

# Repository 모듈은 얇은 IO 경계이며 mock하기 쉬워야 한다.
REPOSITORY_MODULES: tuple[str, ...] = (
    "dynamodb",
    "s3_vectors",
)

__all__ = ["REPOSITORY_MODULES"]
