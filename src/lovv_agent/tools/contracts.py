"""Tool I/O contract dataclasses for Gateway-ready separation.

Each I/O tool has explicit Input/Output contracts defined here. Currently the
tools run in-process; when Gateway Lambda separation happens, only the adapter
layer changes — these contracts remain the stable interface.

Design principle:
- I/O bound + stateless → Gateway Lambda candidate
- Pure computation → stays in-process (not defined here)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# search_attractions — S3 Vectors 벡터 검색
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchAttractionsInput:
    """Input for S3 Vectors attraction search.

    Gateway tool name: search_attractions
    """

    query_vector: list[float]
    city_id: str | None = None
    theme: str | None = None
    top_k: int = 50
    filters: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_vector": self.query_vector,
            "city_id": self.city_id,
            "theme": self.theme,
            "top_k": self.top_k,
            "filters": self.filters,
        }


@dataclass(frozen=True, slots=True)
class SearchAttractionsOutput:
    """Output from S3 Vectors attraction search."""

    candidates: tuple[dict[str, Any], ...]
    retrieval_count: int
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": list(self.candidates),
            "retrieval_count": self.retrieval_count,
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# search_place_pool — Pass 2 인출 (city 고정 + theme off)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchPlacePoolInput:
    """Input for Pass 2 place pool retrieval (city-anchored, theme-off).

    Gateway tool name: search_place_pool
    """

    query_vector: list[float]
    city_id: str
    top_k: int = 50
    exclude_place_ids: tuple[str, ...] = ()
    filters: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_vector": self.query_vector,
            "city_id": self.city_id,
            "top_k": self.top_k,
            "exclude_place_ids": list(self.exclude_place_ids),
            "filters": self.filters,
        }


@dataclass(frozen=True, slots=True)
class SearchPlacePoolOutput:
    """Output from Pass 2 place pool retrieval."""

    candidates: tuple[dict[str, Any], ...]
    retrieval_count: int
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": list(self.candidates),
            "retrieval_count": self.retrieval_count,
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# lookup_festival_seeds — DynamoDB 축제 후보 조회
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LookupFestivalSeedsInput:
    """Input for DynamoDB festival candidate lookup.

    Gateway tool name: lookup_festival_seeds
    """

    city_id: str
    travel_month: int
    travel_year: int
    max_candidates: int = 30

    def to_dict(self) -> dict[str, Any]:
        return {
            "city_id": self.city_id,
            "travel_month": self.travel_month,
            "travel_year": self.travel_year,
            "max_candidates": self.max_candidates,
        }


@dataclass(frozen=True, slots=True)
class LookupFestivalSeedsOutput:
    """Output from DynamoDB festival candidate lookup."""

    festivals: tuple[dict[str, Any], ...]
    retrieval_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "festivals": list(self.festivals),
            "retrieval_count": self.retrieval_count,
        }


# ---------------------------------------------------------------------------
# enrich_place_details — DynamoDB BatchGetItem 장소 상세
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnrichPlaceDetailsInput:
    """Input for DynamoDB place detail enrichment.

    Gateway tool name: enrich_place_details
    """

    place_keys: tuple[dict[str, str], ...] = ()  # Each: {"pk": ..., "sk": ...}

    def to_dict(self) -> dict[str, Any]:
        return {
            "place_keys": list(self.place_keys),
        }


@dataclass(frozen=True, slots=True)
class EnrichPlaceDetailsOutput:
    """Output from DynamoDB place detail enrichment."""

    details: tuple[dict[str, Any], ...] = ()
    missing_keys: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "details": list(self.details),
            "missing_keys": list(self.missing_keys),
        }


# ---------------------------------------------------------------------------
# embed_query — Bedrock Titan embedding 생성
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbedQueryInput:
    """Input for text embedding generation.

    Gateway tool name: embed_query
    """

    text: str
    model_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "model_id": self.model_id,
        }


@dataclass(frozen=True, slots=True)
class EmbedQueryOutput:
    """Output from text embedding generation."""

    vector: list[float] = field(default_factory=list)
    dimension: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "vector": self.vector,
            "dimension": self.dimension,
        }


__all__ = [
    "EmbedQueryInput",
    "EmbedQueryOutput",
    "EnrichPlaceDetailsInput",
    "EnrichPlaceDetailsOutput",
    "LookupFestivalSeedsInput",
    "LookupFestivalSeedsOutput",
    "SearchAttractionsInput",
    "SearchAttractionsOutput",
    "SearchPlacePoolInput",
    "SearchPlacePoolOutput",
]
