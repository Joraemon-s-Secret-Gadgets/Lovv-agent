"""Typed runtime configuration for the Lovv agent graph.

This module owns non-secret runtime settings only. Importing it must not read
environment variables, create AWS clients, or pick a concrete model ID. Runtime
callers can either construct :class:`RuntimeConfig` directly or call
``RuntimeConfig.from_env`` at the application boundary.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field


class ConfigError(ValueError):
    """Raised when injected runtime configuration is invalid."""


CONFIG_SECTIONS: tuple[str, ...] = (
    "aws",
    "s3_vectors",
    "dynamodb",
    "embeddings",
    "llm",
    "intent",
    "search_budget",
    "timeouts",
    "retries",
)

ENV_KEYS: tuple[str, ...] = (
    "LOVV_AWS_REGION",
    "LOVV_AWS_PROFILE",
    "LOVV_S3_VECTOR_BUCKET",
    "LOVV_S3_VECTOR_INDEX",
    "LOVV_DYNAMODB_TABLE",
    "LOVV_EMBEDDING_ADAPTER_ID",
    "LOVV_EMBEDDING_MODEL_ID",
    "LOVV_LLM_ADAPTER_ID",
    "LOVV_LLM_MODEL_ID",
    "LOVV_INTENT_MIN_NATURAL_LANGUAGE_QUERY_CHARS",
    "LOVV_SEARCH_PER_THEME_TOP_K",
    "LOVV_SEARCH_RAW_SOFT_TOP_K",
    "LOVV_MAX_FESTIVAL_SEED_CANDIDATES",
    "LOVV_VERIFIER_CANDIDATE_K",
    "LOVV_CONNECT_TIMEOUT_SECONDS",
    "LOVV_READ_TIMEOUT_SECONDS",
    "LOVV_MAX_RETRY_ATTEMPTS",
    "LOVV_SCHEMA_RETRY_LIMIT",
)

DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_S3_VECTOR_BUCKET = "local-lovv-vector-bucket"
DEFAULT_S3_VECTOR_INDEX = "local-attraction-index"
DEFAULT_DYNAMODB_TABLE = "local-lovv-table"
DEFAULT_EMBEDDING_ADAPTER_ID = "local-embedding-adapter"
DEFAULT_LLM_ADAPTER_ID = "bedrock-converse"
DEFAULT_MIN_NATURAL_LANGUAGE_QUERY_CHARS = 5
DEFAULT_PER_THEME_ATTRACTION_TOP_K = 24
DEFAULT_RAW_SOFT_CHANNEL_TOP_K = 12
DEFAULT_MAX_FESTIVAL_SEED_CANDIDATES = 30
DEFAULT_VERIFIER_CANDIDATE_K = 5
DEFAULT_CONNECT_TIMEOUT_SECONDS = 3.0
DEFAULT_READ_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RETRY_ATTEMPTS = 2
DEFAULT_SCHEMA_RETRY_LIMIT = 2


def _optional_text(value: str | None) -> str | None:
    """Normalize empty environment values to ``None``."""

    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _required_text(value: str | None, field_name: str) -> str:
    """Return a non-empty string or raise a field-specific config error."""

    normalized = _optional_text(value)
    if normalized is None:
        raise ConfigError(f"{field_name} must be a non-empty string")
    return normalized


def _positive_int(value: str | int, field_name: str) -> int:
    """Parse and validate a positive integer setting."""

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{field_name} must be a positive integer")
    return parsed


def _positive_float(value: str | float | int, field_name: str) -> float:
    """Parse and validate a positive float setting."""

    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} must be a positive number") from exc
    if parsed <= 0:
        raise ConfigError(f"{field_name} must be a positive number")
    return parsed


@dataclass(frozen=True, slots=True)
class AwsSettings:
    """AWS account-local runtime routing settings.

    ``profile_name`` is optional and is only a profile selector. It is not a
    credential value and should never contain access keys or secret material.
    """

    region: str = DEFAULT_AWS_REGION
    profile_name: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.region, "aws.region")
        if self.profile_name is not None:
            _required_text(self.profile_name, "aws.profile_name")


@dataclass(frozen=True, slots=True)
class S3VectorSettings:
    """S3 Vector resource names used by DestinationSearchTool."""

    bucket_name: str = DEFAULT_S3_VECTOR_BUCKET
    index_name: str = DEFAULT_S3_VECTOR_INDEX

    def __post_init__(self) -> None:
        _required_text(self.bucket_name, "s3_vectors.bucket_name")
        _required_text(self.index_name, "s3_vectors.index_name")


@dataclass(frozen=True, slots=True)
class DynamoDbSettings:
    """DynamoDB table boundary for festivals and final item detail enrichment."""

    table_name: str = DEFAULT_DYNAMODB_TABLE

    def __post_init__(self) -> None:
        _required_text(self.table_name, "dynamodb.table_name")


@dataclass(frozen=True, slots=True)
class EmbeddingSettings:
    """Embedding runtime selector without hardcoding provider credentials."""

    adapter_id: str = DEFAULT_EMBEDDING_ADAPTER_ID
    model_id: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.adapter_id, "embeddings.adapter_id")
        if self.model_id is not None:
            _required_text(self.model_id, "embeddings.model_id")


@dataclass(frozen=True, slots=True)
class LlmSettings:
    """LLM adapter selector.

    The default intentionally leaves ``model_id`` unset so this package does
    not freeze a specific foundation model in code.
    """

    adapter_id: str = DEFAULT_LLM_ADAPTER_ID
    model_id: str | None = None

    def __post_init__(self) -> None:
        _required_text(self.adapter_id, "llm.adapter_id")
        if self.model_id is not None:
            _required_text(self.model_id, "llm.model_id")


@dataclass(frozen=True, slots=True)
class IntentSettings:
    """Intent Agent policy knobs for conservative MVP extraction.

    Short natural-language input should not block the graph. When the trimmed
    query is shorter than ``min_natural_language_query_chars``, the Intent node
    should skip LLM extraction and continue from structured API fields.
    """

    min_natural_language_query_chars: int = DEFAULT_MIN_NATURAL_LANGUAGE_QUERY_CHARS

    def __post_init__(self) -> None:
        _positive_int(
            self.min_natural_language_query_chars,
            "intent.min_natural_language_query_chars",
        )


@dataclass(frozen=True, slots=True)
class SearchBudgetSettings:
    """Runtime-configurable retrieval and verifier candidate budgets."""

    per_theme_attraction_top_k: int = DEFAULT_PER_THEME_ATTRACTION_TOP_K
    raw_soft_channel_top_k: int = DEFAULT_RAW_SOFT_CHANNEL_TOP_K
    max_festival_seed_candidates: int = DEFAULT_MAX_FESTIVAL_SEED_CANDIDATES
    verifier_candidate_k: int = DEFAULT_VERIFIER_CANDIDATE_K

    def __post_init__(self) -> None:
        _positive_int(
            self.per_theme_attraction_top_k,
            "search_budget.per_theme_attraction_top_k",
        )
        _positive_int(
            self.raw_soft_channel_top_k,
            "search_budget.raw_soft_channel_top_k",
        )
        _positive_int(
            self.max_festival_seed_candidates,
            "search_budget.max_festival_seed_candidates",
        )
        _positive_int(self.verifier_candidate_k, "search_budget.verifier_candidate_k")


@dataclass(frozen=True, slots=True)
class TimeoutSettings:
    """Network timeout settings for future injected AWS/LLM adapters."""

    connect_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _positive_float(self.connect_seconds, "timeouts.connect_seconds")
        _positive_float(self.read_seconds, "timeouts.read_seconds")


@dataclass(frozen=True, slots=True)
class RetrySettings:
    """Bounded retry settings for runtime calls and schema validation."""

    max_attempts: int = DEFAULT_MAX_RETRY_ATTEMPTS
    schema_retry_limit: int = DEFAULT_SCHEMA_RETRY_LIMIT

    def __post_init__(self) -> None:
        _positive_int(self.max_attempts, "retries.max_attempts")
        _positive_int(self.schema_retry_limit, "retries.schema_retry_limit")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Complete injectable runtime configuration for Lovv graph execution."""

    aws: AwsSettings = field(default_factory=AwsSettings)
    s3_vectors: S3VectorSettings = field(default_factory=S3VectorSettings)
    dynamodb: DynamoDbSettings = field(default_factory=DynamoDbSettings)
    embeddings: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)
    intent: IntentSettings = field(default_factory=IntentSettings)
    search_budget: SearchBudgetSettings = field(default_factory=SearchBudgetSettings)
    timeouts: TimeoutSettings = field(default_factory=TimeoutSettings)
    retries: RetrySettings = field(default_factory=RetrySettings)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RuntimeConfig":
        """Build config from non-secret environment values.

        Passing ``env`` keeps tests and harnesses deterministic. When omitted,
        the function reads ``os.environ`` at call time only.
        """

        source = os.environ if env is None else env

        return cls(
            aws=AwsSettings(
                region=source.get("LOVV_AWS_REGION", DEFAULT_AWS_REGION),
                profile_name=_optional_text(source.get("LOVV_AWS_PROFILE")),
            ),
            s3_vectors=S3VectorSettings(
                bucket_name=source.get(
                    "LOVV_S3_VECTOR_BUCKET",
                    DEFAULT_S3_VECTOR_BUCKET,
                ),
                index_name=source.get(
                    "LOVV_S3_VECTOR_INDEX",
                    DEFAULT_S3_VECTOR_INDEX,
                ),
            ),
            dynamodb=DynamoDbSettings(
                table_name=source.get(
                    "LOVV_DYNAMODB_TABLE",
                    DEFAULT_DYNAMODB_TABLE,
                ),
            ),
            embeddings=EmbeddingSettings(
                adapter_id=source.get(
                    "LOVV_EMBEDDING_ADAPTER_ID",
                    DEFAULT_EMBEDDING_ADAPTER_ID,
                ),
                model_id=_optional_text(source.get("LOVV_EMBEDDING_MODEL_ID")),
            ),
            llm=LlmSettings(
                adapter_id=source.get("LOVV_LLM_ADAPTER_ID", DEFAULT_LLM_ADAPTER_ID),
                model_id=_optional_text(source.get("LOVV_LLM_MODEL_ID")),
            ),
            intent=IntentSettings(
                min_natural_language_query_chars=_positive_int(
                    source.get(
                        "LOVV_INTENT_MIN_NATURAL_LANGUAGE_QUERY_CHARS",
                        DEFAULT_MIN_NATURAL_LANGUAGE_QUERY_CHARS,
                    ),
                    "LOVV_INTENT_MIN_NATURAL_LANGUAGE_QUERY_CHARS",
                ),
            ),
            search_budget=SearchBudgetSettings(
                per_theme_attraction_top_k=_positive_int(
                    source.get(
                        "LOVV_SEARCH_PER_THEME_TOP_K",
                        DEFAULT_PER_THEME_ATTRACTION_TOP_K,
                    ),
                    "LOVV_SEARCH_PER_THEME_TOP_K",
                ),
                raw_soft_channel_top_k=_positive_int(
                    source.get(
                        "LOVV_SEARCH_RAW_SOFT_TOP_K",
                        DEFAULT_RAW_SOFT_CHANNEL_TOP_K,
                    ),
                    "LOVV_SEARCH_RAW_SOFT_TOP_K",
                ),
                max_festival_seed_candidates=_positive_int(
                    source.get(
                        "LOVV_MAX_FESTIVAL_SEED_CANDIDATES",
                        DEFAULT_MAX_FESTIVAL_SEED_CANDIDATES,
                    ),
                    "LOVV_MAX_FESTIVAL_SEED_CANDIDATES",
                ),
                verifier_candidate_k=_positive_int(
                    source.get(
                        "LOVV_VERIFIER_CANDIDATE_K",
                        DEFAULT_VERIFIER_CANDIDATE_K,
                    ),
                    "LOVV_VERIFIER_CANDIDATE_K",
                ),
            ),
            timeouts=TimeoutSettings(
                connect_seconds=_positive_float(
                    source.get(
                        "LOVV_CONNECT_TIMEOUT_SECONDS",
                        DEFAULT_CONNECT_TIMEOUT_SECONDS,
                    ),
                    "LOVV_CONNECT_TIMEOUT_SECONDS",
                ),
                read_seconds=_positive_float(
                    source.get(
                        "LOVV_READ_TIMEOUT_SECONDS",
                        DEFAULT_READ_TIMEOUT_SECONDS,
                    ),
                    "LOVV_READ_TIMEOUT_SECONDS",
                ),
            ),
            retries=RetrySettings(
                max_attempts=_positive_int(
                    source.get("LOVV_MAX_RETRY_ATTEMPTS", DEFAULT_MAX_RETRY_ATTEMPTS),
                    "LOVV_MAX_RETRY_ATTEMPTS",
                ),
                schema_retry_limit=_positive_int(
                    source.get(
                        "LOVV_SCHEMA_RETRY_LIMIT",
                        DEFAULT_SCHEMA_RETRY_LIMIT,
                    ),
                    "LOVV_SCHEMA_RETRY_LIMIT",
                ),
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a serializable non-secret config snapshot."""

        return asdict(self)


def default_runtime_config() -> RuntimeConfig:
    """Return local-test-safe defaults without reading environment variables."""

    return RuntimeConfig()


__all__ = [
    "AwsSettings",
    "CONFIG_SECTIONS",
    "ConfigError",
    "DynamoDbSettings",
    "ENV_KEYS",
    "EmbeddingSettings",
    "IntentSettings",
    "LlmSettings",
    "RetrySettings",
    "RuntimeConfig",
    "S3VectorSettings",
    "SearchBudgetSettings",
    "TimeoutSettings",
    "default_runtime_config",
]
