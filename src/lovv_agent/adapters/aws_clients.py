"""AWS runtime client injection boundary.

This module intentionally does not import ``boto3``. The application or future
AgentCore harness must inject a runtime client factory at the outer boundary so
unit tests and package imports never require AWS credentials or network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from lovv_agent.config import RuntimeConfig, default_runtime_config

ADAPTER_NAME = "AwsClientFactory"

RESPONSIBILITY = "Create AWS clients lazily from injected runtime config."


class AwsClientConfigurationError(RuntimeError):
    """Raised when an AWS client is requested without an injected factory."""


class AwsClientFactory(Protocol):
    """Callable boundary for runtime-owned AWS client construction."""

    def __call__(
        self,
        service_name: str,
        *,
        region_name: str,
    ) -> Any:
        """Return a client for ``service_name`` in ``region_name``."""


@dataclass(frozen=True, slots=True)
class AwsRuntimeClients:
    """Concrete client set passed into repositories at runtime."""

    s3_vectors: Any
    dynamodb: Any


@dataclass(frozen=True, slots=True)
class AwsClientProvider:
    """Lazy AWS client provider with no global singleton behavior."""

    config: RuntimeConfig
    client_factory: AwsClientFactory | None = None

    @classmethod
    def from_factory(
        cls,
        client_factory: AwsClientFactory,
        config: RuntimeConfig | None = None,
    ) -> "AwsClientProvider":
        """Build a provider from an injected client factory."""

        return cls(
            config=default_runtime_config() if config is None else config,
            client_factory=client_factory,
        )

    def create_s3_vectors_client(self) -> Any:
        """Create the S3 Vector runtime client on demand."""

        return self._create_client("s3vectors")

    def create_dynamodb_client(self) -> Any:
        """Create the DynamoDB runtime client on demand."""

        return self._create_client("dynamodb")

    def create_runtime_clients(self) -> AwsRuntimeClients:
        """Create runtime clients used by search and Dynamo lookup tools."""

        return AwsRuntimeClients(
            s3_vectors=self.create_s3_vectors_client(),
            dynamodb=self.create_dynamodb_client(),
        )

    def _create_client(self, service_name: str) -> Any:
        """Invoke the injected factory with non-secret runtime routing config."""

        if self.client_factory is None:
            raise AwsClientConfigurationError(
                "AWS clients require an injected client_factory",
            )
        return self.client_factory(
            service_name,
            region_name=self.config.aws.region,
        )


def create_client_provider(
    *,
    config: RuntimeConfig | None = None,
    client_factory: AwsClientFactory | None = None,
) -> AwsClientProvider:
    """Return a provider without creating any AWS clients."""

    return AwsClientProvider(
        config=default_runtime_config() if config is None else config,
        client_factory=client_factory,
    )


__all__ = [
    "ADAPTER_NAME",
    "RESPONSIBILITY",
    "AwsClientConfigurationError",
    "AwsClientFactory",
    "AwsClientProvider",
    "AwsRuntimeClients",
    "create_client_provider",
]
