"""S3 Vector repository boundary.

The repository is intentionally thin in Task 4.1: it accepts an injected client
and forwards already-built query payloads. Filter construction and candidate
normalization belong to later DestinationSearchTool subtasks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from lovv_agent.config import S3VectorSettings
from lovv_agent.models.schemas import SchemaValidationError

REPOSITORY_NAME = "S3VectorRepository"

RESPONSIBILITY = "Search vector candidates through an injected S3 Vector client."


class S3VectorClient(Protocol):
    """Runtime client shape required by :class:`S3VectorRepository`."""

    def query_vectors(self, **request: Any) -> Mapping[str, Any]:
        """Run an S3 Vector query and return the raw provider response."""


@dataclass(frozen=True, slots=True)
class S3VectorRepository:
    """Pass-through repository for injected S3 Vector clients."""

    client: S3VectorClient
    settings: S3VectorSettings

    def query_vectors(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Execute a vector query with configured bucket and index names."""

        if not isinstance(request, Mapping):
            raise SchemaValidationError("s3 vector request must be a mapping")
        payload = dict(request)
        payload.setdefault("bucket_name", self.settings.bucket_name)
        payload.setdefault("index_name", self.settings.index_name)
        response = self.client.query_vectors(**payload)
        if not isinstance(response, Mapping):
            raise SchemaValidationError("s3 vector response must be a mapping")
        return dict(response)


def extract_vector_records(response: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Extract raw vector records from common S3 Vector response shapes."""

    if not isinstance(response, Mapping):
        raise SchemaValidationError("s3 vector response must be a mapping")
    for field_name in ("vectors", "matches", "results"):
        records = response.get(field_name)
        if records is None:
            continue
        if not isinstance(records, (list, tuple)):
            raise SchemaValidationError(f"s3 vector response.{field_name} must be a list")
        return tuple(_copy_record(record, field_name) for record in records)
    return ()


def _copy_record(record: Any, field_name: str) -> dict[str, Any]:
    """Validate and copy one raw vector record."""

    if not isinstance(record, Mapping):
        raise SchemaValidationError(
            f"s3 vector response.{field_name} item must be a mapping",
        )
    return dict(record)


__all__ = [
    "REPOSITORY_NAME",
    "RESPONSIBILITY",
    "S3VectorClient",
    "S3VectorRepository",
    "extract_vector_records",
]
