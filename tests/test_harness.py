"""Tests for Task 10 harness and AWS runtime adapter boundaries."""

from __future__ import annotations

import io
import json
import unittest
from typing import Any

from lovv_agent.adapters.aws_clients import AwsClientProvider
from lovv_agent.adapters.aws_runtime import (
    build_aws_runtime_adapters,
    require_converse_runtime,
    require_embedding_adapter,
    runtime_injection_error_state,
)
from lovv_agent.adapters.boto3_clients import create_boto3_client_factory
from lovv_agent.adapters.embeddings import BedrockEmbeddingAdapter
from lovv_agent.config import (
    AwsSettings,
    DynamoDbSettings,
    EmbeddingSettings,
    LlmSettings,
    RuntimeConfig,
    S3VectorSettings,
)
from lovv_agent.harness import build_harness
from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.prompts.registry import (
    CANDIDATE_REASON_CLAIM_PROMPT_ID,
    INTENT_NORMALIZATION_PROMPT_ID,
    PLANNER_COPY_EXPLANATION_PROMPT_ID,
    load_prompt_template,
)


class FakeBoto3Session:
    """Minimal boto3 Session fake that records requested clients."""

    def __init__(self, *, profile_name: str | None, owner: "FakeBoto3Module") -> None:
        self.profile_name = profile_name
        self.owner = owner

    def client(self, service_name: str, *, region_name: str) -> dict[str, str | None]:
        """Return a lightweight client marker."""

        client = {
            "service_name": service_name,
            "region_name": region_name,
            "profile_name": self.profile_name,
        }
        self.owner.clients.append(client)
        return client


class FakeBoto3Module:
    """Minimal boto3 module fake used without importing the real dependency."""

    def __init__(self) -> None:
        self.sessions: list[FakeBoto3Session] = []
        self.clients: list[dict[str, str | None]] = []

    def Session(self, profile_name: str | None = None) -> FakeBoto3Session:  # noqa: N802 - boto3 API.
        """Create a fake boto3 session."""

        session = FakeBoto3Session(profile_name=profile_name, owner=self)
        self.sessions.append(session)
        return session


class RecordingAwsFactory:
    """Record service client requests and return service-specific fakes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.bedrock = RecordingBedrockRuntimeClient()
        self.s3_vectors = RecordingS3VectorsClient()
        self.dynamodb = RecordingDynamoDbClient()

    def __call__(self, service_name: str, *, region_name: str) -> Any:
        self.calls.append((service_name, region_name))
        if service_name == "bedrock-runtime":
            return self.bedrock
        if service_name == "s3vectors":
            return self.s3_vectors
        if service_name == "dynamodb":
            return self.dynamodb
        raise AssertionError(f"unexpected service: {service_name}")


class RecordingS3VectorsClient:
    """S3 Vector fake with the runtime method expected by the repository."""

    def query_vectors(self, **request: Any) -> dict[str, Any]:
        """Return stable attraction records for full graph harness tests."""

        return {
            "vectors": [
                {
                    "key": f"attraction#{index}",
                    "distance": 0.1 + (index * 0.01),
                    "metadata": {
                        "entity_type": "attraction",
                        "place_id": f"attraction#{index}",
                        "title": f"테스트 해변 {index}",
                        "city_id": "KR-TestCity",
                        "city_name_ko": "테스트시",
                        "theme_tags": ["바다·해안"],
                        "latitude": 37.0 + index / 100,
                        "longitude": 129.0 + index / 100,
                        "ddb_pk": "CITY#TestCity",
                        "ddb_sk": f"ATTRACTION#{index}",
                    },
                }
                for index in range(1, 7)
            ],
            "request": dict(request),
        }


class RecordingDynamoDbClient:
    """DynamoDB fake with the runtime methods expected by the repository."""

    def get_item(self, **request: Any) -> dict[str, Any]:
        """Return one detail record for final placed item enrichment."""

        key = request["Key"]
        sk = key["SK"]["S"]
        return {
            "Item": {
                "PK": key["PK"],
                "SK": key["SK"],
                "overview": {"S": f"{sk}의 검증된 상세 설명입니다."},
            },
            "request": dict(request),
        }

    def query(self, **request: Any) -> dict[str, Any]:
        """Return an empty query response."""

        return {"Items": [], "request": dict(request)}


class RecordingBedrockRuntimeClient:
    """Bedrock Runtime fake for embedding and Converse calls."""

    def __init__(self) -> None:
        self.invoke_model_requests: list[dict[str, Any]] = []
        self.converse_requests: list[dict[str, Any]] = []

    def invoke_model(self, **request: Any) -> dict[str, Any]:
        """Return a small embedding payload."""

        self.invoke_model_requests.append(dict(request))
        request_body = json.loads(request["body"].decode("utf-8"))
        dimensions = int(request_body.get("dimensions", 2))
        body = json.dumps({"embedding": [0.1] * dimensions}).encode("utf-8")
        return {"body": io.BytesIO(body)}

    def converse(self, **request: Any) -> dict[str, Any]:
        """Return a minimal structured-output response."""

        self.converse_requests.append(dict(request))
        return {"structured_output": {"ok": True}}


class Boto3ClientFactoryTest(unittest.TestCase):
    """Validate live AWS factory behavior without importing real boto3."""

    def test_factory_uses_profile_and_region_at_call_time(self) -> None:
        fake_boto3 = FakeBoto3Module()
        factory = create_boto3_client_factory(
            profile_name="lovv-dev",
            boto3_module=fake_boto3,
        )

        client = factory("dynamodb", region_name="ap-northeast-2")

        self.assertEqual(client["service_name"], "dynamodb")
        self.assertEqual(client["region_name"], "ap-northeast-2")
        self.assertEqual(client["profile_name"], "lovv-dev")
        self.assertEqual(fake_boto3.sessions[0].profile_name, "lovv-dev")


class AwsRuntimeAssemblyTest(unittest.TestCase):
    """Validate AWS runtime wiring with fully mocked clients."""

    def test_runtime_assembly_wires_repositories_tools_and_model_adapters(self) -> None:
        factory = RecordingAwsFactory()
        config = RuntimeConfig(
            aws=AwsSettings(region="ap-northeast-2"),
            s3_vectors=S3VectorSettings(
                bucket_name="lovv-vector-dev",
                index_name="kr-tour-domain-v1",
            ),
            dynamodb=DynamoDbSettings(table_name="TourKoreaDomainData"),
            embeddings=EmbeddingSettings(model_id="amazon.titan-embed-text-v2:0"),
            llm=LlmSettings(model_id="gpt-oss-120b"),
        )

        adapters = build_aws_runtime_adapters(
            client_factory=factory,
            config=config,
        )

        self.assertEqual(
            factory.calls,
            [
                ("s3vectors", "ap-northeast-2"),
                ("dynamodb", "ap-northeast-2"),
                ("bedrock-runtime", "ap-northeast-2"),
            ],
        )
        self.assertEqual(
            adapters.repositories.s3_vectors.settings.bucket_name,
            "lovv-vector-dev",
        )
        self.assertEqual(
            adapters.repositories.dynamodb.settings.table_name,
            "TourKoreaDomainData",
        )
        self.assertIs(adapters.tools.destination_search.s3_vectors, adapters.repositories.s3_vectors)
        self.assertIs(adapters.tools.dynamo_lookup.dynamodb, adapters.repositories.dynamodb)
        self.assertIsNotNone(adapters.embedding_adapter)
        self.assertIsNotNone(adapters.converse_runtime)

    def test_runtime_assembly_leaves_model_adapters_unset_without_model_ids(self) -> None:
        adapters = build_aws_runtime_adapters(
            client_factory=RecordingAwsFactory(),
            config=RuntimeConfig(),
        )

        self.assertIsNone(adapters.embedding_adapter)
        self.assertIsNone(adapters.converse_runtime)
        with self.assertRaises(SchemaValidationError):
            require_embedding_adapter(adapters)
        with self.assertRaises(SchemaValidationError):
            require_converse_runtime(adapters)

    def test_provider_creates_bedrock_runtime_client_lazily(self) -> None:
        factory = RecordingAwsFactory()
        provider = AwsClientProvider.from_factory(factory, config=RuntimeConfig())

        self.assertEqual(factory.calls, [])
        client = provider.create_bedrock_runtime_client()

        self.assertIs(client, factory.bedrock)
        self.assertEqual(factory.calls, [("bedrock-runtime", "us-east-1")])

    def test_runtime_injection_failure_has_structured_error_state(self) -> None:
        error = runtime_injection_error_state(
            RuntimeError("factory failed"),
            component="test_runtime",
            retryable=True,
        )

        self.assertEqual(
            error.to_dict(),
            {
                "status": "error",
                "code": "runtime_adapter_injection_failed",
                "component": "test_runtime",
                "message": "factory failed",
                "error_type": "RuntimeError",
                "retryable": True,
            },
        )


class BedrockAdapterTest(unittest.TestCase):
    """Validate Bedrock embedding and Converse wrappers."""

    def test_embedding_adapter_invokes_bedrock_runtime_model(self) -> None:
        client = RecordingBedrockRuntimeClient()
        adapter = BedrockEmbeddingAdapter(
            client=client,
            model_id="amazon.titan-embed-text-v2:0",
            dimensions=2,
        )

        embedding = adapter.embed_query("조용한 바다 산책")

        self.assertEqual(embedding, (0.1, 0.1))
        request = client.invoke_model_requests[0]
        self.assertEqual(request["modelId"], "amazon.titan-embed-text-v2:0")
        self.assertIn(b"inputText", request["body"])

    def test_converse_runtime_injects_configured_test_model(self) -> None:
        factory = RecordingAwsFactory()
        config = RuntimeConfig(llm=LlmSettings(model_id="gpt-oss-120b"))
        adapters = build_aws_runtime_adapters(
            client_factory=factory,
            config=config,
        )

        runtime = require_converse_runtime(adapters)
        response = runtime({"messages": [{"role": "user", "content": [{"text": "hi"}]}]})

        self.assertEqual(response["structured_output"], {"ok": True})
        request = factory.bedrock.converse_requests[0]
        self.assertEqual(request["modelId"], "gpt-oss-120b")


class PromptRegistryTest(unittest.TestCase):
    """Validate versioned prompt assets are loadable project artifacts."""

    def test_prompt_registry_loads_candidate_and_planner_prompts(self) -> None:
        candidate_prompt = load_prompt_template(CANDIDATE_REASON_CLAIM_PROMPT_ID)
        intent_prompt = load_prompt_template(INTENT_NORMALIZATION_PROMPT_ID)
        planner_prompt = load_prompt_template(PLANNER_COPY_EXPLANATION_PROMPT_ID)

        self.assertEqual(candidate_prompt.version, "v1")
        self.assertIn("Candidate Evidence Agent", candidate_prompt.text)
        self.assertEqual(intent_prompt.version, "v1")
        self.assertIn("API structured input", intent_prompt.text)
        self.assertEqual(planner_prompt.version, "v1")
        self.assertIn("Planner Agent", planner_prompt.text)


class FullLangGraphHarnessTest(unittest.TestCase):
    """Validate API request to public response through the real StateGraph."""

    def test_local_harness_invokes_real_langgraph_with_injected_adapters(self) -> None:
        factory = RecordingAwsFactory()
        config = RuntimeConfig(
            aws=AwsSettings(region="us-east-1"),
            s3_vectors=S3VectorSettings(
                bucket_name="lovv-vector-dev",
                index_name="kr-tour-domain-v1",
            ),
            dynamodb=DynamoDbSettings(table_name="TourKoreaDomainData"),
            embeddings=EmbeddingSettings(model_id="amazon.titan-embed-text-v2:0"),
            llm=LlmSettings(model_id="openai.gpt-oss-120b-1:0"),
        )
        adapters = build_aws_runtime_adapters(client_factory=factory, config=config)
        harness = build_harness(config=config, adapters=adapters)

        state = harness.invoke_state(
            {
                "entryType": "chat",
                "destinationId": None,
                "country": "KR",
                "travelYear": 2026,
                "travelMonth": 10,
                "tripType": "daytrip",
                "themes": ["sea_coast"],
                "includeFestivals": False,
                "naturalLanguageQuery": "바다",
                "userLocation": None,
            },
            request_id="REQ-LANGGRAPH-1",
        )

        self.assertEqual(state.serving.response_status, "completed")
        self.assertEqual(
            state.trace.node_timings["visited_nodes"],
            [
                "intent_agent",
                "supervisor_router",
                "candidate_evidence_agent",
                "supervisor_router",
                "planner_agent",
                "supervisor_router",
                "response_packager",
            ],
        )
        response = state.serving.response_payload
        self.assertEqual(response["recommendationId"], "REQ-LANGGRAPH-1")
        self.assertEqual(response["destination"]["destinationId"], "KR-TestCity")
        self.assertGreater(len(response["itinerary"]["days"][0]["items"]), 0)
        first_item = response["itinerary"]["days"][0]["items"][0]
        self.assertIn("검증된 상세 설명", first_item["body"])
        self.assertEqual(state.trace.node_timings["intent_mode"], "deterministic_short_query")
        self.assertTrue(factory.bedrock.invoke_model_requests)

    def test_long_query_injects_versioned_intent_prompt_before_safe_fallback(self) -> None:
        factory = RecordingAwsFactory()
        config = RuntimeConfig(
            embeddings=EmbeddingSettings(model_id="amazon.titan-embed-text-v2:0"),
            llm=LlmSettings(model_id="openai.gpt-oss-120b-1:0"),
        )
        adapters = build_aws_runtime_adapters(client_factory=factory, config=config)
        harness = build_harness(config=config, adapters=adapters)

        state = harness.invoke_state(
            {
                "entryType": "chat",
                "destinationId": None,
                "country": "KR",
                "travelYear": 2026,
                "travelMonth": 10,
                "tripType": "daytrip",
                "themes": ["sea_coast"],
                "includeFestivals": False,
                "naturalLanguageQuery": "조용하고 덜 붐비는 바다 산책을 하고 싶어요.",
                "userLocation": None,
            },
        )

        first_request = factory.bedrock.converse_requests[0]
        self.assertIn("Lovv 소도시 여행 추천 시스템", first_request["system"][0]["text"])
        self.assertEqual(
            state.trace.node_timings["intent_mode"],
            "deterministic_llm_fallback",
        )
        self.assertEqual(state.intent.active_required_themes, ("바다·해안",))


if __name__ == "__main__":
    unittest.main()
