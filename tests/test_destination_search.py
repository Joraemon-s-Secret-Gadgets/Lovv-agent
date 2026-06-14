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
    SearchBudgetSettings,
)
from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.repositories.dynamodb import DynamoDbRepository
from lovv_agent.repositories.s3_vectors import S3VectorRepository
from lovv_agent.tools.destination_search import (
    ATTRACTION_ENTITY_TYPE,
    DestinationSearchTool,
    build_attraction_filter,
    build_attraction_search_request,
    normalize_attraction_candidate,
)


class RecordingAwsFactory:
    """Record lazy AWS client creation calls without touching real AWS."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, service_name: str, *, region_name: str) -> dict[str, str]:
        self.calls.append((service_name, region_name))
        return {"service": service_name, "region": region_name}


class RecordingS3VectorClient:
    """Mock S3 Vector client used by repository tests."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.response = {"vectors": [{"key": "chunk-1"}]} if response is None else response

    def query_vectors(self, **request: Any) -> dict[str, Any]:
        self.requests.append(dict(request))
        return self.response


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


class AttractionSearchTest(unittest.TestCase):
    """Validate attraction search request construction for Task 4.2."""

    def test_search_candidates_builds_attraction_only_filter(self) -> None:
        client = RecordingS3VectorClient(
            response={
                "vectors": [
                    {
                        "key": "place-1::chunk-3",
                        "distance": 0.12,
                        "metadata": {
                            "entity_type": ATTRACTION_ENTITY_TYPE,
                            "city_id": "city-1",
                            "city_name_ko": "샘플시",
                            "theme_tags": ["sea_coast", "walk"],
                            "title": "조용한 해변 산책로",
                            "latitude": 35.1,
                            "longitude": 129.1,
                            "ddb_pk": "PLACE#1",
                            "ddb_sk": "DETAIL#1",
                        },
                    },
                ],
            },
        )
        repository = S3VectorRepository(client=client, settings=S3VectorSettings())
        tool = DestinationSearchTool(
            s3_vectors=repository,
            search_budget=SearchBudgetSettings(per_theme_attraction_top_k=7),
        )

        candidates = tool.search_candidates(
            [0.1, 0.2, 0.3],
            city_id="city-1",
            theme_tags=["sea_coast", "walk"],
        )

        request = client.requests[0]
        self.assertEqual(request["top_k"], 7)
        self.assertTrue(request["return_metadata"])
        self.assertTrue(request["return_distance"])
        self.assertEqual(
            request["filter"],
            {
                "and": [
                    {
                        "field": "entity_type",
                        "operator": "eq",
                        "value": "attraction",
                    },
                    {"field": "city_id", "operator": "eq", "value": "city-1"},
                    {
                        "field": "theme_tags",
                        "operator": "contains_any",
                        "values": ["sea_coast", "walk"],
                    },
                ],
            },
        )
        self.assertEqual(candidates[0].place_id, "place-1")
        self.assertEqual(candidates[0].city_id, "city-1")

    def test_search_candidates_top_k_call_argument_overrides_runtime_budget(self) -> None:
        request = build_attraction_search_request(
            query_vector=[0.1],
            top_k=3,
            search_budget=SearchBudgetSettings(per_theme_attraction_top_k=9),
        )

        self.assertEqual(request["top_k"], 3)

    def test_filter_combines_city_and_single_theme(self) -> None:
        metadata_filter = build_attraction_filter(city_id="city-7", theme="history")

        self.assertEqual(
            metadata_filter,
            {
                "and": [
                    {
                        "field": "entity_type",
                        "operator": "eq",
                        "value": "attraction",
                    },
                    {"field": "city_id", "operator": "eq", "value": "city-7"},
                    {
                        "field": "theme_tags",
                        "operator": "contains_any",
                        "values": ["history"],
                    },
                ],
            },
        )

    def test_chunk_key_normalizes_to_stable_place_id(self) -> None:
        candidate = normalize_attraction_candidate(
            {
                "key": "place-99#chunk-12",
                "distance": 0.5,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "city-1",
                    "title": "명소",
                    "theme_tags": "history",
                },
            },
        )

        self.assertEqual(candidate.place_id, "place-99")
        self.assertEqual(candidate.theme_tags, ("history",))

    def test_normalize_metadata_place_id_overrides_chunk_key(self) -> None:
        candidate = normalize_attraction_candidate(
            {
                "key": "chunk-only-1",
                "distance": 0.5,
                "metadata": {
                    "entity_type": "attraction",
                    "place_id": "place-from-metadata",
                    "city_id": "city-1",
                    "title": "명소",
                    "theme_tags": ["history"],
                },
            },
        )

        self.assertEqual(candidate.place_id, "place-from-metadata")

    def test_normalize_non_attraction_candidate_fails(self) -> None:
        with self.assertRaises(SchemaValidationError):
            normalize_attraction_candidate(
                {
                    "key": "festival-1::chunk-1",
                    "distance": 0.5,
                    "metadata": {
                        "entity_type": "festival",
                        "city_id": "city-1",
                        "title": "축제",
                        "theme_tags": ["festival"],
                    },
                },
            )


if __name__ == "__main__":
    unittest.main()
