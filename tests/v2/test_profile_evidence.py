from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import pytest

from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.agents.profile.evidence import (
    InMemoryProfileEvidenceCache,
    ProfileEvidenceResolver,
    build_profile_evidence_record,
)
from lovv_agent_v2.agents.profile.node import profile_node


def _candidate_input() -> dict[str, object]:
    return {
        "country": "KR",
        "travel_month": 9,
        "travel_year": 2026,
        "trip_type": "3d2n",
        "active_required_themes": ["바다·해안", "자연·트레킹"],
        "include_festivals": False,
        "cleaned_raw_query": "숲길과 바다를 함께 보고 싶어요.",
        "soft_preference_query": "",
        "congestion_pref": "neutral",
        "transport_pref": "unknown",
        "destination_id": None,
        "user_location": None,
        "execution_mode": "city_discovery",
        "unsupported_conditions": [],
    }


def _saved_itinerary_signals() -> dict[str, object]:
    return {
        "saved_trip_count": 2,
        "recent_itineraries": [
            {
                "itinerary_id": "itn-1",
                "destination_json": {"country": "KR", "city": "Gangneung"},
                "themes_json": ["sea_coast", "nature_trekking"],
                "preference_snapshot": {"pace": "slow"},
                "trip_type": "3d2n",
                "duration_label": "3 days 2 nights",
                "conditions_snapshot_json": {"transport_pref": "car"},
                "items": [
                    {
                        "place_name": "Anmok Beach",
                        "content_id": "CID-1",
                        "place_id": "PLC-1",
                        "day_index": 1,
                        "sort_order": 1,
                    },
                ],
            },
            {
                "itinerary_id": "itn-2",
                "destination_json": {"country": "KR", "city": "Sokcho"},
                "themes_json": ["sea_coast"],
                "trip_type": "daytrip",
                "duration_label": "day trip",
                "items": [],
            },
        ],
        "liked_itineraries": [
            {
                "itinerary_id": "itn-liked",
                "themes_json": ["sea_coast"],
                "reaction": "like",
            },
        ],
    }


def test_build_profile_evidence_record_projects_saved_itinerary_signals() -> None:
    record = build_profile_evidence_record(
        _saved_itinerary_signals(),
        actor_id="actor-1",
        thread_id="thread-1",
    )

    assert record is not None
    assert record.lovv_user_profile.saved_trip_count == 3
    assert record.lovv_user_profile.saved_theme_counts["sea_coast"] == 3
    assert record.lovv_user_profile.saved_theme_counts["nature_trekking"] == 1

    profile_record = record.to_profile_record()
    assert profile_record["actor_id"] == "actor-1"
    assert profile_record["lovv_user_profile"] == {
        "saved_trip_count": 3,
        "saved_theme_counts": {
            "sea_coast": 3,
            "nature_trekking": 1,
            "history_tradition": 0,
            "art_sense": 0,
            "healing_rest": 0,
        },
    }
    evidence = profile_record["saved_itinerary_evidence"]
    assert evidence["destinations"][0]["city"] == "Gangneung"
    assert evidence["places"][0]["place_name"] == "Anmok Beach"
    assert evidence["liked_itinerary_count"] == 1


@pytest.mark.parametrize(
    "signals",
    [
        {},
        {"recent_itineraries": "not-a-list"},
        {"saved_trip_count": True},
    ],
)
def test_build_profile_evidence_record_rejects_empty_or_malformed_signals(
    signals: Mapping[str, object],
) -> None:
    assert (
        build_profile_evidence_record(signals, actor_id="actor-1", thread_id="thread-1")
        is None
    )


@dataclass(slots=True)
class FakeSavedItinerarySignalsTool:
    calls: list[tuple[str, str]]
    response: Mapping[str, Any] | None = None
    error: Exception | None = None

    def fetch_saved_itinerary_signals(
        self,
        *,
        actor_id: str,
        thread_id: str,
        recent_limit: int,
        liked_limit: int,
    ) -> Mapping[str, Any] | None:
        self.calls.append((actor_id, thread_id))
        if self.error is not None:
            raise self.error
        return self.response


def test_profile_evidence_resolver_uses_cache_hit_without_tool_call() -> None:
    cache = InMemoryProfileEvidenceCache(ttl_seconds=300)
    tool = FakeSavedItinerarySignalsTool(calls=[], response=_saved_itinerary_signals())
    resolver = ProfileEvidenceResolver(cache=cache, tool=tool, clock=lambda: 10.0)
    miss = resolver.resolve(actor_id="actor-1", thread_id="thread-1")
    assert miss.audit["cache_status"] == "miss"
    assert tool.calls == [("actor-1", "thread-1")]

    tool.calls.clear()
    hit = resolver.resolve(actor_id="actor-1", thread_id="thread-1")

    assert hit.record is not None
    assert hit.audit["cache_status"] == "hit"
    assert tool.calls == []


def test_profile_evidence_resolver_falls_back_when_tool_fails() -> None:
    resolver = ProfileEvidenceResolver(
        cache=InMemoryProfileEvidenceCache(ttl_seconds=300),
        tool=FakeSavedItinerarySignalsTool(
            calls=[],
            error=RuntimeError("gateway unavailable"),
        ),
        clock=lambda: 10.0,
    )

    result = resolver.resolve(actor_id="actor-1", thread_id="thread-1")

    assert result.record is None
    assert result.audit["cache_status"] == "miss"
    assert result.audit["fallback_reason"] == "tool_failed"


def test_profile_evidence_resolver_injects_profile_record_for_profile_node() -> None:
    resolver = ProfileEvidenceResolver(
        cache=InMemoryProfileEvidenceCache(ttl_seconds=300),
        tool=FakeSavedItinerarySignalsTool(calls=[], response=_saved_itinerary_signals()),
        clock=lambda: 10.0,
    )
    payload = {
        "intent": {"city_select_input": _candidate_input()},
        "profile": {"existing": "preserved"},
    }

    enriched = resolver.enrich_graph_payload(
        payload,
        actor_id="actor-1",
        thread_id="thread-1",
    )
    result = profile_node(cast(UnifiedAgentState, enriched))

    assert enriched["profile"]["existing"] == "preserved"
    assert enriched["profile"]["profile_record"]["lovv_user_profile"]["saved_trip_count"] == 3
    assert enriched["profile"]["saved_itinerary_evidence_audit"]["cache_status"] == "miss"
    assert result["intent"]["city_select_input"]["theme_weights"] == {
        "바다·해안": 1.3,
        "자연·트레킹": 1.075,
    }
