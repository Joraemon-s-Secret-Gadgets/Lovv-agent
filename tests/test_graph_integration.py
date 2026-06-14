"""Integration tests for the local Lovv graph runtime."""

from __future__ import annotations

import json
import unittest

from lovv_agent.agents.planner import PlannerAgent
from lovv_agent.graph import (
    CLARIFICATION_TERMINAL,
    GRAPH_NODE_ORDER,
    GraphNodeSet,
    build_local_graph,
    get_graph_skeleton,
)
from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    FestivalVerification,
    SelectedCity,
)
from lovv_agent.state import IntentState, RequestState, UnifiedAgentState
from lovv_agent.tools.response_packager import (
    package_recommendation_response,
    package_state_response,
)


def request_state(*, include_festivals: bool = False) -> UnifiedAgentState:
    """Return one typed graph state seeded with request fields."""

    return UnifiedAgentState(
        request=RequestState(
            request_id="REQ-1",
            entry_type="recommendation",
            country="KR",
            travel_year=2026,
            travel_month=10,
            trip_type="daytrip",
            destination_id=None,
            themes=("sea_coast",),
            include_festivals=include_festivals,
            natural_language_query="조용한 바다 산책",
        ),
    )


def place(place_id: str) -> dict[str, object]:
    """Return one grounded attraction candidate."""

    return {
        "place_id": place_id,
        "title": f"장소 {place_id}",
        "city_id": "KR-A",
        "city_name_ko": "에이군",
        "theme_tags": ["바다·해안"],
    }


def evidence_package(*, include_festival_candidate: bool = False) -> CandidateEvidencePackage:
    """Return a Planner-safe Candidate Evidence package."""

    selected_festivals = (
        {
            "festival_id": "F-A",
            "name": "에이 축제",
            "city_id": "KR-A",
            "city_name": "에이군",
            "month": 10,
        },
    )
    return CandidateEvidencePackage(
        status="ok",
        mode=(
            "festival_seeded_city_discovery"
            if include_festival_candidate
            else "city_discovery"
        ),
        selected_city=SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=(place("P-0"), place("P-1"), place("P-2")),
        selected_festival_candidates=selected_festivals if include_festival_candidate else (),
    )


def gourmet_evidence_package() -> CandidateEvidencePackage:
    """Return a package that should expose only a foodSearch link publicly."""

    return CandidateEvidencePackage(
        status="ok",
        mode="city_discovery",
        selected_city=SelectedCity(city_id="KR-A", city_name_ko="에이군", country="KR"),
        recommended_places=(place("P-0"), place("P-1"), place("P-2")),
        coverage_audit={"external_link_themes": ["미식·노포"]},
    )


def festival_verification() -> FestivalVerification:
    """Return one confirmed festival verifier output."""

    return FestivalVerification(
        festival_id="F-A",
        name="에이 축제",
        date_status="confirmed",
        start_date="2026-10-10",
        end_date="2026-10-12",
        is_applicable_to_trip=True,
        planner_policy="placeable",
        source_type="dynamodb_detail",
        confidence=0.8,
        evidence_summary="confirmed",
    )


def planner_node(state: UnifiedAgentState):
    """Run the real Planner against mocked upstream state."""

    return PlannerAgent().plan(
        state.evidence.candidate_evidence_package,
        trip_type=state.request.trip_type,
        include_festivals=state.request.include_festivals,
        festival_verifications=state.festival.festival_verifications,
    )


def response_packager(state: UnifiedAgentState) -> dict[str, object]:
    """Return a tiny response payload for graph wiring tests."""

    planner_output = state.planning.planner_output
    return {
        "responseStatus": state.serving.response_status,
        "nextNode": state.routing.next_node,
        "needsClarification": state.routing.needs_clarification,
        "clarifyingQuestion": state.routing.clarifying_question,
        "itineraryCount": len(planner_output.itinerary) if planner_output else 0,
        "festivalCount": (
            sum(1 for item in planner_output.itinerary if item.get("item_type") == "festival")
            if planner_output
            else 0
        ),
    }


class GraphRouteIntegrationTest(unittest.TestCase):
    """Validate Task 9.1 graph wiring and deterministic routing."""

    def test_graph_skeleton_keeps_canonical_node_order(self) -> None:
        self.assertEqual(get_graph_skeleton(), GRAPH_NODE_ORDER)
        self.assertEqual(GRAPH_NODE_ORDER[0], "intent_agent")
        self.assertEqual(GRAPH_NODE_ORDER[-1], "response_packager")

    def test_graph_route_executes_without_festival_verifier_when_not_requested(self) -> None:
        festival_calls: list[str] = []
        graph = build_local_graph(
            GraphNodeSet(
                intent=lambda state: IntentState(),
                candidate_evidence=lambda state: evidence_package(),
                festival_verifier=lambda state: festival_calls.append("called") or (),
                planner=planner_node,
                response_packager=response_packager,
            ),
        )

        final_state = graph.invoke(request_state(include_festivals=False))

        self.assertEqual(festival_calls, [])
        self.assertEqual(final_state.routing.fulfilled_matrix["festival"], "N/A")
        self.assertEqual(final_state.routing.fulfilled_matrix["planning"], "O")
        self.assertEqual(final_state.serving.response_status, "completed")
        self.assertEqual(final_state.serving.response_payload["itineraryCount"], 3)
        self.assertIn(
            "festival_verifier_agent_or_skip",
            final_state.trace.node_timings["visited_nodes"],
        )

    def test_graph_route_calls_festival_verifier_when_requested(self) -> None:
        festival_calls: list[str] = []
        graph = build_local_graph(
            GraphNodeSet(
                intent=lambda state: IntentState(),
                candidate_evidence=lambda state: evidence_package(
                    include_festival_candidate=True,
                ),
                festival_verifier=lambda state: festival_calls.append("called")
                or (festival_verification(),),
                planner=planner_node,
                response_packager=response_packager,
            ),
        )

        final_state = graph.invoke(request_state(include_festivals=True))

        self.assertEqual(festival_calls, ["called"])
        self.assertEqual(final_state.routing.fulfilled_matrix["festival"], "O")
        self.assertEqual(final_state.serving.response_payload["festivalCount"], 1)

    def test_graph_route_reaches_user_wait_on_candidate_clarification(self) -> None:
        planner_calls: list[str] = []
        clarifying_package = CandidateEvidencePackage(
            status="no_candidate",
            needs_clarification=True,
            clarifying_question="조건을 완화할까요?",
            mode="city_discovery",
            failure_signals=("no_city_after_theme_gate",),
        )
        graph = build_local_graph(
            GraphNodeSet(
                intent=lambda state: IntentState(),
                candidate_evidence=lambda state: clarifying_package,
                festival_verifier=lambda state: (),
                planner=lambda state: planner_calls.append("called") or planner_node(state),
                response_packager=response_packager,
            ),
        )

        final_state = graph.invoke(request_state(include_festivals=False))

        self.assertEqual(planner_calls, [])
        self.assertEqual(final_state.routing.next_node, CLARIFICATION_TERMINAL)
        self.assertEqual(final_state.serving.response_status, CLARIFICATION_TERMINAL)
        self.assertTrue(final_state.serving.response_payload["needsClarification"])
        self.assertEqual(
            final_state.serving.response_payload["clarifyingQuestion"],
            "조건을 완화할까요?",
        )


class ResponsePackagerMaskingTest(unittest.TestCase):
    """Validate Task 9.2 response packaging and masking."""

    def test_response_packager_public_shape_hides_internal_fields(self) -> None:
        state = request_state(include_festivals=False)
        package = evidence_package()
        state.evidence.candidate_evidence_package = package
        state.planning.planner_output = PlannerAgent().plan(
            package,
            trip_type=state.request.trip_type,
        )

        response = package_state_response(state)

        self.assertEqual(
            set(response),
            {
                "recommendationId",
                "expiresAt",
                "destination",
                "itinerary",
                "explainability",
                "festivalDateVerifications",
                "links",
            },
        )
        self.assertEqual(response["destination"]["destinationId"], "KR-A")
        self.assertEqual(response["itinerary"]["tripType"], "daytrip")
        serialized = json.dumps(response, ensure_ascii=False)
        self.assertNotIn("candidate_reason_claims", serialized)
        self.assertNotIn("explanation_audit", serialized)
        self.assertNotIn("validation_result", serialized)
        self.assertNotIn("retrieval_audit", serialized)

    def test_response_masking_flattens_food_search_link(self) -> None:
        package = gourmet_evidence_package()
        planner_output = PlannerAgent().plan(package, trip_type="daytrip")

        response = package_recommendation_response(
            planner_output=planner_output,
            request=request_state().request,
            selected_city=package.selected_city,
            recommendation_id="REC-1",
            expires_at="2026-06-14T09:30:00Z",
        )

        self.assertEqual(response["recommendationId"], "REC-1")
        self.assertIn("foodSearch", response["links"])
        self.assertIsInstance(response["links"]["foodSearch"], str)
        self.assertIn("google.com/search", response["links"]["foodSearch"])
        self.assertNotIn("external_search_link", json.dumps(response, ensure_ascii=False))

    def test_response_packager_includes_safe_festival_date_verifications(self) -> None:
        package = evidence_package(include_festival_candidate=True)
        verification = festival_verification()
        planner_output = PlannerAgent().plan(
            package,
            trip_type="daytrip",
            include_festivals=True,
            festival_verifications=(verification,),
        )

        response = package_recommendation_response(
            planner_output=planner_output,
            request=request_state(include_festivals=True).request,
            selected_city=package.selected_city,
            festival_verifications=(verification,),
            recommendation_id="REC-2",
            expires_at="2026-06-14T09:30:00Z",
        )

        self.assertEqual(len(response["festivalDateVerifications"]), 1)
        self.assertEqual(
            response["festivalDateVerifications"][0]["dateStatus"],
            "confirmed",
        )
        self.assertNotIn(
            "evidence_summary",
            json.dumps(response["festivalDateVerifications"], ensure_ascii=False),
        )


if __name__ == "__main__":
    unittest.main()
