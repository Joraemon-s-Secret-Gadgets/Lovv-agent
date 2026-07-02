from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from lovv_agent_v2.infra.aws_clients import create_boto3_client_factory
from lovv_agent_v2.infra.config import RuntimeConfig
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool, FestivalSeedResult
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository


class FestivalCandidateLookupTool(Protocol):
    def search_festival_city_seeds(
        self,
        *,
        country: str,
        travel_month: int,
        travel_year: int | None = None,
        theme_pool: Sequence[str],
        city_id: str | None = None,
        city_key: str | None = None,
        max_candidates: int | None = None,
    ) -> FestivalSeedResult: ...


@dataclass(frozen=True, slots=True)
class FestivalVerifierTools:
    festival_lookup: FestivalCandidateLookupTool


def build_festival_verifier_tools(
    config: RuntimeConfig | None = None,
) -> FestivalVerifierTools:
    runtime_config = RuntimeConfig.from_env() if config is None else config
    client_factory = create_boto3_client_factory(
        profile_name=runtime_config.aws.profile_name,
    )
    dynamodb_client = client_factory("dynamodb", region_name=runtime_config.aws.region)
    return FestivalVerifierTools(
        festival_lookup=DynamoLookupTool(
            dynamodb=DynamoDbRepository(
                client=dynamodb_client,
                settings=runtime_config.dynamodb,
            ),
            search_budget=runtime_config.search_budget,
        ),
    )


__all__ = [
    "FestivalCandidateLookupTool",
    "FestivalVerifierTools",
    "build_festival_verifier_tools",
]
