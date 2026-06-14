"""Tests for DestinationSearchTool AWS repository boundaries."""

from __future__ import annotations

import unittest
from typing import Any

from lovv_agent.adapters.aws_clients import (
    AwsClientConfigurationError,
    AwsClientProvider,
)
from lovv_agent.config import (
    DynamoDbSettings,
    RuntimeConfig,
    S3VectorSettings,
)
from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.repositories.dynamodb import DynamoDbRepository
from lovv_agent.repositories.s3_vectors import S3VectorRepository


class RecordingAwsFactory:
    """Record lazy AWS client creation calls without touching real AWS."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, service_name: str, *, region_name: str) -> dict[str, str]:
        self.calls.append((service_name, region_name))
        return {"service": service_name, "region": region_name}


class RecordingS3VectorClient:
    """Mock S3 Vector client used by repository tests."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def query_vectors(self, **request: Any) -> dict[str, Any]:
        self.requests.append(dict(request))
        return {"vectors": [{"key": "chunk-1"}]}


class RecordingDynamoDbClient:
    """Mock DynamoDB client used by repository tests."""

    def __init__(self) -> None:
        self.get_item_requests: list[dict[str, Any]] = []
        self.query_requests: list[dict[str, Any]] = []

    def get_item(self, **request: Any) -> dict[str, Any]:
        self.get_item_requests.append(dict(request))
        return {"Item": {"pk": {"S": "PLACE#1"}}}

    def query(self, **request: Any) -> dict[str, Any]:
        self.query_requests.append(dict(request))
        return {"Items": [{"pk": {"S": "FESTIVAL#1"}}]}


class AwsClientProviderTest(unittest.TestCase):
    """Validate lazy AWS client construction for Task 4.1."""

    def test_provider_does_not_create_clients_until_requested(self) -> None:
        factory = RecordingAwsFactory()
        config = RuntimeConfig()

        provider = AwsClientProvider.from_factory(factory, config=config)

        self.assertEqual(factory.calls, [])
        s3_client = provider.create_s3_vectors_client()
        dynamodb_client = provider.create_dynamodb_client()

        self.assertEqual(
            factory.calls,
            [
                ("s3vectors", config.aws.region),
                ("dynamodb", config.aws.region),
            ],
        )
        self.assertEqual(s3_client["service"], "s3vectors")
        self.assertEqual(dynamodb_client["service"], "dynamodb")

    def test_provider_requires_injected_factory(self) -> None:
        provider = AwsClientProvider(config=RuntimeConfig())

        with self.assertRaises(AwsClientConfigurationError):
            provider.create_dynamodb_client()


class RepositoryBoundaryTest(unittest.TestCase):
    """Validate mockable repository boundaries without AWS credentials."""

    def test_s3_vector_repository_uses_injected_client_and_settings(self) -> None:
        client = RecordingS3VectorClient()
        repository = S3VectorRepository(
            client=client,
            settings=S3VectorSettings(
                bucket_name="lovv-vector-bucket",
                index_name="attractions-index",
            ),
        )

        response = repository.query_vectors({"query_vector": [0.1, 0.2], "top_k": 3})

        self.assertEqual(response["vectors"][0]["key"], "chunk-1")
        self.assertEqual(
            client.requests,
            [
                {
                    "query_vector": [0.1, 0.2],
                    "top_k": 3,
                    "bucket_name": "lovv-vector-bucket",
                    "index_name": "attractions-index",
                },
            ],
        )

    def test_dynamodb_repository_uses_injected_client_and_table(self) -> None:
        client = RecordingDynamoDbClient()
        repository = DynamoDbRepository(
            client=client,
            settings=DynamoDbSettings(table_name="lovv-table"),
        )

        item_response = repository.get_item(
            {"pk": {"S": "PLACE#1"}, "sk": {"S": "DETAIL#1"}},
        )
        query_response = repository.query_items(
            {"KeyConditionExpression": "pk = :pk"},
        )

        self.assertEqual(item_response["Item"]["pk"]["S"], "PLACE#1")
        self.assertEqual(query_response["Items"][0]["pk"]["S"], "FESTIVAL#1")
        self.assertEqual(client.get_item_requests[0]["TableName"], "lovv-table")
        self.assertEqual(client.query_requests[0]["TableName"], "lovv-table")

    def test_repositories_validate_request_and_response_shapes(self) -> None:
        s3_repository = S3VectorRepository(
            client=RecordingS3VectorClient(),
            settings=S3VectorSettings(),
        )
        dynamodb_repository = DynamoDbRepository(
            client=RecordingDynamoDbClient(),
            settings=DynamoDbSettings(),
        )

        with self.assertRaises(SchemaValidationError):
            s3_repository.query_vectors(["not", "a", "mapping"])  # type: ignore[arg-type]

        with self.assertRaises(SchemaValidationError):
            dynamodb_repository.get_item(["not", "a", "mapping"])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
