"""AWS-backed runtime adapter assembly for Lovv graph nodes.

This module wires configured AWS clients into repositories and tools. It does
not read environment variables or create boto3 sessions by itself; callers pass
``RuntimeConfig`` and an ``AwsClientFactory`` from the app or smoke harness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from lovv_agent.adapters.aws_clients import (
    AwsClientFactory,
    AwsClientProvider,
    AwsRuntimeClients,
    create_client_provider,
)
from lovv_agent.adapters.bedrock_converse import (
    RuntimeInvoker,
    create_bedrock_converse_runtime,
)
from lovv_agent.adapters.embeddings import BedrockEmbeddingAdapter
from lovv_agent.config import LLM_ROUTING_NODES, RuntimeConfig, default_runtime_config, resolve_llm_model_id
from lovv_agent.models.schemas import SchemaValidationError
from lovv_agent.repositories.dynamodb import DynamoDbRepository
from lovv_agent.repositories.s3_vectors import S3VectorRepository
from lovv_agent.tools.destination_search import DestinationSearchTool
from lovv_agent.tools.dynamo_lookup import DynamoLookupTool

ADAPTER_NAME = "AwsRuntimeAdapterAssembly"

RESPONSIBILITY = "Wire AWS clients into repository/tool adapters for the graph."


@dataclass(frozen=True, slots=True)
class AwsRuntimeRepositories:
    """AWS-backed repository instances used by graph tools."""

    s3_vectors: S3VectorRepository
    dynamodb: DynamoDbRepository


@dataclass(frozen=True, slots=True)
class AwsRuntimeTools:
    """AWS-backed tool instances used by graph nodes."""

    destination_search: DestinationSearchTool
    dynamo_lookup: DynamoLookupTool


@dataclass(frozen=True, slots=True)
class AwsRuntimeAdapters:
    """Complete AWS runtime bundle for graph/harness injection."""

    config: RuntimeConfig
    clients: AwsRuntimeClients
    repositories: AwsRuntimeRepositories
    tools: AwsRuntimeTools
    embedding_adapter: BedrockEmbeddingAdapter | None
    converse_runtime: RuntimeInvoker | None
    converse_runtimes_by_node: Mapping[str, RuntimeInvoker]


@dataclass(frozen=True, slots=True)
class RuntimeInjectionErrorState:
    """Structured runtime injection failure for harness error handling."""

    status: str
    code: str
    component: str
    message: str
    error_type: str
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable structured error state."""

        return {
            "status": self.status,
            "code": self.code,
            "component": self.component,
            "message": self.message,
            "error_type": self.error_type,
            "retryable": self.retryable,
        }


def build_aws_runtime_adapters(
    *,
    client_factory: AwsClientFactory,
    config: RuntimeConfig | None = None,
) -> AwsRuntimeAdapters:
    """Create AWS-backed repositories, tools, and model adapters."""

    resolved_config = default_runtime_config() if config is None else config
    provider = create_client_provider(
        config=resolved_config,
        client_factory=client_factory,
    )
    return build_aws_runtime_adapters_from_provider(
        config=resolved_config,
        provider=provider,
    )


def build_aws_runtime_adapters_from_provider(
    *,
    config: RuntimeConfig,
    provider: AwsClientProvider,
) -> AwsRuntimeAdapters:
    """Create graph-ready AWS adapters from an injected client provider."""

    clients = provider.create_runtime_clients()
    # Repository는 IO 경계이고, tool은 그 위에서 비즈니스 정규화와
    # fallback 정책을 적용한다.
    repositories = AwsRuntimeRepositories(
        s3_vectors=S3VectorRepository(
            client=clients.s3_vectors,
            settings=config.s3_vectors,
        ),
        dynamodb=DynamoDbRepository(
            client=clients.dynamodb,
            settings=config.dynamodb,
        ),
    )
    tools = AwsRuntimeTools(
        destination_search=DestinationSearchTool(
            s3_vectors=repositories.s3_vectors,
            search_budget=config.search_budget,
        ),
        dynamo_lookup=DynamoLookupTool(
            dynamodb=repositories.dynamodb,
            search_budget=config.search_budget,
        ),
    )
    return AwsRuntimeAdapters(
        config=config,
        clients=clients,
        repositories=repositories,
        tools=tools,
        embedding_adapter=_build_embedding_adapter(
            client=clients.bedrock_runtime,
            model_id=config.embeddings.model_id,
        ),
        converse_runtime=_build_converse_runtime(
            client=clients.bedrock_runtime,
            model_id=config.llm.model_id,
        ),
        converse_runtimes_by_node=_build_converse_runtimes_by_node(
            client=clients.bedrock_runtime,
            config=config,
        ),
    )


def _build_embedding_adapter(
    *,
    client: Any,
    model_id: str | None,
) -> BedrockEmbeddingAdapter | None:
    """Create an embedding adapter only when a model id is configured."""

    if model_id is None:
        return None
    return BedrockEmbeddingAdapter(client=client, model_id=model_id)


def _build_converse_runtime(
    *,
    client: Any,
    model_id: str | None,
) -> RuntimeInvoker | None:
    """Create a Converse runtime only when a model id is configured."""

    if model_id is None:
        return None
    return create_bedrock_converse_runtime(client=client, model_id=model_id)


def _build_converse_runtimes_by_node(
    *,
    client: Any,
    config: RuntimeConfig,
) -> dict[str, RuntimeInvoker]:
    """Create Converse runtime wrappers for each configured LLM-using node."""

    runtimes: dict[str, RuntimeInvoker] = {}
    for node in LLM_ROUTING_NODES:
        model_id = resolve_llm_model_id(config.llm, node)
        if model_id is not None:
            # Keep one Bedrock client and one Runtime; only the injected modelId varies by node.
            runtimes[node] = create_bedrock_converse_runtime(
                client=client,
                model_id=model_id,
            )
    return runtimes


def require_embedding_adapter(adapters: AwsRuntimeAdapters) -> BedrockEmbeddingAdapter:
    """Return the configured embedding adapter or raise a clear config error."""

    if adapters.embedding_adapter is None:
        raise SchemaValidationError("embeddings.model_id is required for live embedding")
    return adapters.embedding_adapter


def require_converse_runtime(adapters: AwsRuntimeAdapters) -> RuntimeInvoker:
    """Return the configured Converse runtime or raise a clear config error."""

    if adapters.converse_runtime is None:
        raise SchemaValidationError("llm.model_id is required for live LLM calls")
    return adapters.converse_runtime


def require_agent_converse_runtime(
    adapters: AwsRuntimeAdapters,
    node: str,
) -> RuntimeInvoker:
    """Return the configured Converse runtime for one LLM-using graph node."""

    try:
        return adapters.converse_runtimes_by_node[node]
    except KeyError as exc:
        raise SchemaValidationError(
            f"llm.model_id for {node} is required for live LLM calls",
        ) from exc


def runtime_injection_error_state(
    exc: Exception,
    *,
    component: str = "aws_runtime_adapters",
    code: str = "runtime_adapter_injection_failed",
    retryable: bool = False,
) -> RuntimeInjectionErrorState:
    """Convert adapter construction failures into a structured error state."""

    return RuntimeInjectionErrorState(
        status="error",
        code=code,
        component=component,
        message=str(exc) or type(exc).__name__,
        error_type=type(exc).__name__,
        retryable=retryable,
    )


__all__ = [
    "ADAPTER_NAME",
    "RESPONSIBILITY",
    "AwsRuntimeAdapters",
    "AwsRuntimeRepositories",
    "AwsRuntimeTools",
    "RuntimeInjectionErrorState",
    "build_aws_runtime_adapters",
    "build_aws_runtime_adapters_from_provider",
    "require_agent_converse_runtime",
    "require_converse_runtime",
    "require_embedding_adapter",
    "runtime_injection_error_state",
]
