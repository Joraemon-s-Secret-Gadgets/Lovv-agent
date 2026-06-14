"""DynamoDB repository boundary.

This layer stays mockable by accepting an injected client. It owns only request
shape construction for DynamoDB reads; business fallback decisions remain in
the caller-facing tools.
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

    def get_detail_item(
        self,
        *,
        pk: str,
        sk: str,
        consistent_read: bool = False,
    ) -> dict[str, Any]:
        """Read one detail item by the canonical `PK`/`SK` key pair."""

        return self.get_item(
            {
                "PK": {"S": _required_text(pk, "pk")},
                "SK": {"S": _required_text(sk, "sk")},
            },
            consistent_read=consistent_read,
        )

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

    def query_festival_candidates(
        self,
        *,
        country: str,
        travel_month: int,
        city_id: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Query candidate festival rows by country/month and optional city."""

        request: dict[str, Any] = {
            "KeyConditionExpression": "#country = :country AND #month = :month",
            "ExpressionAttributeNames": {
                "#country": "country",
                "#month": "month",
                "#entity_type": "entity_type",
            },
            "ExpressionAttributeValues": {
                ":country": {"S": _required_text(country, "country")},
                ":month": {"N": str(_month(travel_month, "travel_month"))},
                ":entity_type": {"S": "festival"},
            },
            "FilterExpression": "#entity_type = :entity_type",
        }
        normalized_city_id = _optional_text(city_id, "city_id")
        if normalized_city_id is not None:
            request["FilterExpression"] += " AND #city_id = :city_id"
            request["ExpressionAttributeNames"]["#city_id"] = "city_id"
            request["ExpressionAttributeValues"][":city_id"] = {"S": normalized_city_id}
        if limit is not None:
            request["Limit"] = _positive_int(limit, "limit")
        return self.query_items(request)


def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty text value for repository requests."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    """Validate optional text and normalize blanks to ``None``."""

    if value is None:
        return None
    return _required_text(value, field_name)


def _month(value: Any, field_name: str) -> int:
    """Validate a 1-12 month number."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value < 1 or value > 12:
        raise SchemaValidationError(f"{field_name} must be between 1 and 12")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    """Validate a positive integer request option."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return value


__all__ = [
    "DynamoDbClient",
    "DynamoDbRepository",
    "REPOSITORY_NAME",
    "RESPONSIBILITY",
]
