from __future__ import annotations

from collections.abc import Sequence

from lovv_agent_v2.agents.city_select.retrieval.agent import (
    CitySelectRetrievalAgent,
    CitySelectRetrievalRequest,
)
from lovv_agent_v2.agents.city_select.domain.contracts import (
    AttractionCandidate,
    PrunedCityGroups,
)
from lovv_agent_v2.agents.city_select.tools import CitySelectTools


def _city_input() -> dict[str, object]:
    return {
        "country": "KR",
        "travel_month": 10,
        "travel_year": 2026,
        "trip_type": "2d1n",
        "active_required_themes": ["역사·전통"],
        "include_festivals": True,
        "cleaned_raw_query": "가을 전통 축제와 유적",
        "soft_preference_query": "",
        "unsupported_conditions": [],
        "destination_id": None,
        "user_location": None,
        "execution_mode": "festival_seeded_city_discovery",
        "congestion_pref": "neutral",
        "transport_pref": "unknown",
    }


def test_retrieval_agent_searches_each_allowed_festival_city_directly() -> None:
    search = RecordingSearch()
    tools = CitySelectTools(
        destination_search=search,
        dynamo_lookup=RecordingDynamoLookup(),
        embedding=RecordingEmbedding(),
    )

    output = CitySelectRetrievalAgent(tools).run(
        CitySelectRetrievalRequest(
            candidate_input=_city_input(),
            allowed_city_ids=("KR-47-130", "KR-51-730", "KR-36-8"),
        ),
    )

    assert [(call["city_id"], call["theme"]) for call in search.calls] == [
        ("KR-47-130", "역사·전통"),
        ("KR-51-730", "역사·전통"),
        ("KR-36-8", "역사·전통"),
    ]
    assert None not in [call["city_id"] for call in search.calls]
    assert output.city_select["retrieval_audit"]["retrieved_candidate_count"] == 3
    assert "scratch" in output.city_select
    assert "pruned_groups" not in output.city_select


class RecordingEmbedding:
    def embed_query(self, query: str) -> list[float]:
        assert query == "가을 전통 축제와 유적"
        return [0.1, 0.2]


class RecordingDynamoLookup:
    pass


class RecordingSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> tuple[AttractionCandidate, ...]:
        assert tuple(query_vector) == (0.1, 0.2)
        assert ddb_pk is None
        self.calls.append({"city_id": city_id, "theme": theme})
        return (
            AttractionCandidate(
                key=f"{city_id}-{theme}",
                place_id=f"{city_id}-{theme}",
                distance=0.1,
                entity_type="attraction",
                city_id=city_id or "KR-NONE",
                city_name_ko="테스트시",
                title="역사 장소",
                theme_tags=(theme or "역사·전통",),
                latitude=35.1,
                longitude=129.1,
                ddb_pk=f"CITY#{city_id}",
                ddb_sk="ATTRACTION#1",
                metadata={},
            ),
        )

    def prune_cities(
        self,
        candidates: Sequence[AttractionCandidate],
        searchable_place_themes: Sequence[str],
        *,
        allowed_city_ids: Sequence[str] | None = None,
    ) -> PrunedCityGroups:
        assert tuple(searchable_place_themes) == ("역사·전통",)
        assert tuple(allowed_city_ids or ()) == ("KR-47-130", "KR-51-730", "KR-36-8")
        return PrunedCityGroups(
            survived_groups={candidate.city_id: (candidate,) for candidate in candidates},
            eliminated_cities=(),
        )
