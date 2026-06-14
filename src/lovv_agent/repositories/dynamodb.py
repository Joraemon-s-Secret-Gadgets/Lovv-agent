"""DynamoDB repository boundary.

Task 4.1 keeps this layer as a mockable pass-through wrapper around an injected
client. Primary key construction, festival query expressions, and failure
warning policies are implemented in later retrieval subtasks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from lovv_agent.config import DynamoDbSettings
from lovv_agent.models.schemas import SchemaValidationError

REPOSITORY_NAME = "DynamoDbRepository"

RESPONSIBILITY = "Read normalized detail records through an injected client."


class DynamoDbClient(Protocol):
    """Runtime client shape required by :class:`DynamoDbRepository`."""

    def get_item(self, **request: Any) -> Mapping[str, Any]:
        """Return one DynamoDB item for the provided key request."""

    def query(self, **request: Any) -> Mapping[str, Any]:
        """Return DynamoDB query results for the provided query request."""


@dataclass(frozen=True, slots=True)
class DynamoDbRepository:
    """Pass-through repository for injected DynamoDB clients."""

    client: DynamoDbClient
    settings: DynamoDbSettings

    def get_item(
        self,
        key: Mapping[str, Any],
        *,
        consistent_read: bool = False,
    ) -> dict[str, Any]:
        """Read one item from the configured table by primary key."""

        if not isinstance(key, Mapping):
            raise SchemaValidationError("dynamodb key must be a mapping")
        response = self.client.get_item(
            TableName=self.settings.table_name,
            Key=dict(key),
            ConsistentRead=consistent_read,
        )
        if not isinstance(response, Mapping):
            raise SchemaValidationError("dynamodb get_item response must be a mapping")
        return dict(response)

    def query_items(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Run a query against the configured table."""

        if not isinstance(request, Mapping):
            raise SchemaValidationError("dynamodb query request must be a mapping")
        payload = dict(request)
        payload.setdefault("TableName", self.settings.table_name)
        response = self.client.query(**payload)
        if not isinstance(response, Mapping):
            raise SchemaValidationError("dynamodb query response must be a mapping")
        return dict(response)


__all__ = [
    "DynamoDbClient",
    "DynamoDbRepository",
    "REPOSITORY_NAME",
    "RESPONSIBILITY",
]
