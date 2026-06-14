"""Lazy boto3 client factory for live AWS runtime execution.

This module is the only adapter boundary that knows how to create boto3
sessions. Importing it does not import boto3 or create clients; the dependency
is loaded only when the returned factory is invoked by a harness or app entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from lovv_agent.adapters.aws_clients import AwsClientFactory, AwsClientProvider
from lovv_agent.config import RuntimeConfig, default_runtime_config

ADAPTER_NAME = "Boto3ClientFactory"

RESPONSIBILITY = "Create live AWS service clients from RuntimeConfig at the harness boundary."


class Boto3ClientFactoryError(RuntimeError):
    """Raised when live boto3 client construction cannot be configured."""


@dataclass(frozen=True, slots=True)
class Boto3ClientFactory:
    """Create boto3 clients without leaking credentials into project config."""

    profile_name: str | None = None
    boto3_module: Any | None = None

    def __call__(self, service_name: str, *, region_name: str) -> Any:
        """Return a boto3 client for one AWS service."""

        module = self.boto3_module
        if module is None:
            try:
                module = import_module("boto3")
            except ModuleNotFoundError as exc:
                raise Boto3ClientFactoryError(
                    "boto3 is required for live AWS runtime clients",
                ) from exc

        session = (
            module.Session(profile_name=self.profile_name)
            if self.profile_name
            else module.Session()
        )
        return session.client(service_name, region_name=region_name)


def create_boto3_client_factory(
    *,
    profile_name: str | None = None,
    boto3_module: Any | None = None,
) -> AwsClientFactory:
    """Build a live AWS client factory without creating clients immediately."""

    return Boto3ClientFactory(
        profile_name=profile_name,
        boto3_module=boto3_module,
    )


def create_boto3_client_provider(
    *,
    config: RuntimeConfig | None = None,
    boto3_module: Any | None = None,
) -> AwsClientProvider:
    """Build an AwsClientProvider backed by lazy boto3 session creation."""

    resolved_config = default_runtime_config() if config is None else config
    return AwsClientProvider.from_factory(
        create_boto3_client_factory(
            profile_name=resolved_config.aws.profile_name,
            boto3_module=boto3_module,
        ),
        config=resolved_config,
    )


__all__ = [
    "ADAPTER_NAME",
    "RESPONSIBILITY",
    "Boto3ClientFactory",
    "Boto3ClientFactoryError",
    "create_boto3_client_factory",
    "create_boto3_client_provider",
]
