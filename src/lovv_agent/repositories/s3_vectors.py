"""S3 Vector repository placeholder.

Later tasks add ``query_vectors`` request construction and candidate
normalization. Task 1.1 contains no AWS calls.
"""

from __future__ import annotations

REPOSITORY_NAME = "S3VectorRepository"

RESPONSIBILITY = "Search vector candidates through an injected S3 Vector client."

__all__ = ["REPOSITORY_NAME", "RESPONSIBILITY"]
