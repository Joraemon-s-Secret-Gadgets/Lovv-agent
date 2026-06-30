from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from lovv_agent_v2.agents.planner.ors_provider import (
    OrsProviderUnavailableError,
    ors_provider_from_env,
)
from lovv_agent_v2.agents.planner.travel_time import HaversineTravelTimeProvider, TravelTimeProvider
from lovv_agent_v2.models.schemas import SchemaValidationError


class EmbeddingTool(Protocol):
    def embed_query(self, query: str) -> Sequence[float]: ...


class DestinationSearchTool(Protocol):
    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> Sequence[object]: ...


@dataclass(frozen=True, slots=True)
class PlannerRuntimeTools:
    destination_search: DestinationSearchTool
    embedding: EmbeddingTool


def runtime_tools_from_value(runtime: object) -> PlannerRuntimeTools | None:
    if runtime is None:
        return None
    destination_search = getattr(runtime, "destination_search", None)
    embedding = getattr(runtime, "embedding", None)
    if destination_search is None or embedding is None:
        raise SchemaValidationError("planner runtime must include destination_search and embedding")
    return PlannerRuntimeTools(
        destination_search=cast(DestinationSearchTool, destination_search),
        embedding=cast(EmbeddingTool, embedding),
    )


def travel_time_provider_from_value(provider: object) -> TravelTimeProvider:
    if provider is not None:
        return cast(TravelTimeProvider, provider)
    try:
        ors_provider = ors_provider_from_env()
    except OrsProviderUnavailableError:
        ors_provider = None
    if ors_provider is not None:
        return ors_provider
    return HaversineTravelTimeProvider()
