"""Local graph runtime for the Lovv recommendation workflow.

The project does not depend on LangGraph yet, so this module provides a small
typed runner that follows the same canonical node sequence. The runner keeps
node implementations injectable, which lets tests use mocked AWS/LLM boundaries
and gives the future AgentCore harness one stable invocation surface.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from lovv_agent.agents.supervisor import (
    NODE_CANDIDATE_EVIDENCE,
    NODE_END_WAIT_USER,
    NODE_FESTIVAL_VERIFIER,
    NODE_PLANNER,
    NODE_RESPONSE_PACKAGER,
    NODE_NAME as SUPERVISOR_NODE_NAME,
    SupervisorRouter,
    create_fulfilled_matrix,
)
from lovv_agent.models.schemas import (
    CandidateEvidencePackage,
    FestivalVerification,
    PlannerOutput,
    SchemaValidationError,
)
from lovv_agent.state import (
    IntentState,
    ServingState,
    UnifiedAgentState,
)
from lovv_agent.tools.response_packager import package_state_response

GRAPH_NODE_ORDER: tuple[str, ...] = (
    "intent_agent",
    "supervisor_router",
    "candidate_evidence_agent",
    "supervisor_router",
    "festival_verifier_agent_or_skip",
    "supervisor_router",
    "planner_agent",
    "supervisor_router",
    "response_packager",
)

CLARIFICATION_TERMINAL = "END_WAIT_USER"

IntentNode = Callable[[UnifiedAgentState], IntentState | Mapping[str, Any]]
CandidateEvidenceNode = Callable[[UnifiedAgentState], CandidateEvidencePackage | Mapping[str, Any]]
FestivalVerifierNode = Callable[
    [UnifiedAgentState],
    Sequence[FestivalVerification | Mapping[str, Any]],
]
PlannerNode = Callable[[UnifiedAgentState], PlannerOutput | Mapping[str, Any]]
ResponsePackagerNode = Callable[[UnifiedAgentState], Mapping[str, Any]]


class LangGraphState(TypedDict, total=False):
    """Small graph envelope around the canonical mutable agent state."""

    state: UnifiedAgentState
    completed_group: str | None
    worker_status: str | None
    terminal_status: str | None


@dataclass(frozen=True, slots=True)
class GraphNodeSet:
    """Injectable node implementations for one local graph run."""

    intent: IntentNode
    candidate_evidence: CandidateEvidenceNode
    festival_verifier: FestivalVerifierNode
    planner: PlannerNode
    response_packager: ResponsePackagerNode = package_state_response


@dataclass(slots=True)
class LocalGraphRuntime:
    """Execute the canonical Lovv graph sequence with deterministic routing."""

    nodes: GraphNodeSet
    supervisor: SupervisorRouter = field(default_factory=SupervisorRouter)

    def invoke(self, state: UnifiedAgentState) -> UnifiedAgentState:
        """Run the graph from Intent through Response Packager."""

        if not isinstance(state, UnifiedAgentState):
            raise SchemaValidationError("state must be a UnifiedAgentState")

        state.routing.fulfilled_matrix = create_fulfilled_matrix(
            include_festivals=state.request.include_festivals,
        )

        _record_visit(state, "intent_agent")
        state.intent = _coerce_intent_state(self.nodes.intent(state))
        _route_next(state, self.supervisor)

        _record_visit(state, NODE_CANDIDATE_EVIDENCE)
        package = _coerce_candidate_package(self.nodes.candidate_evidence(state))
        state.evidence.candidate_evidence_package = package
        _route_completed(
            state,
            self.supervisor,
            completed_group="evidence",
            worker_status=package.status,
            candidate_evidence_package=package,
        )
        if state.routing.next_node == NODE_END_WAIT_USER:
            return _package_and_finish(state, self.nodes.response_packager, CLARIFICATION_TERMINAL)
        if state.routing.next_node == NODE_RESPONSE_PACKAGER:
            return _package_and_finish(state, self.nodes.response_packager, "completed")

        _record_visit(state, "festival_verifier_agent_or_skip")
        if state.request.include_festivals:
            festival_verifications = _coerce_festival_verifications(
                self.nodes.festival_verifier(state),
            )
            state.festival.festival_verifications = festival_verifications
            _route_completed(state, self.supervisor, completed_group="festival")
        else:
            state.festival.festival_verifications = ()
            _route_next(state, self.supervisor)
        if state.routing.next_node == NODE_END_WAIT_USER:
            return _package_and_finish(state, self.nodes.response_packager, CLARIFICATION_TERMINAL)
        if state.routing.next_node == NODE_RESPONSE_PACKAGER:
            return _package_and_finish(state, self.nodes.response_packager, "completed")

        while True:
            _record_visit(state, NODE_PLANNER)
            planner_output = _coerce_planner_output(self.nodes.planner(state))
            state.planning.planner_output = planner_output
            state.planning.validation_result = planner_output.validation_result
            _route_completed(
                state,
                self.supervisor,
                completed_group="planning",
                planner_validation_result=planner_output.validation_result,
            )
            if state.routing.next_node == NODE_PLANNER:
                continue
            if not _planner_validation_passed(planner_output.validation_result):
                state.planning.planner_output = None
            break

        status = (
            CLARIFICATION_TERMINAL
            if state.routing.next_node == NODE_END_WAIT_USER
            else "completed"
        )
        return _package_and_finish(state, self.nodes.response_packager, status)


def get_graph_skeleton() -> tuple[str, ...]:
    """Return the canonical graph node order."""

    return GRAPH_NODE_ORDER


def build_local_graph(nodes: GraphNodeSet) -> LocalGraphRuntime:
    """Build a local graph runtime from injectable node implementations."""

    return LocalGraphRuntime(nodes=nodes)


def build_langgraph(
    nodes: GraphNodeSet,
    *,
    supervisor: SupervisorRouter | None = None,
) -> Any:
    """Compile the real LangGraph workflow with injectable business nodes.

    The graph envelope keeps orchestration-only metadata out of
    ``UnifiedAgentState`` while preserving the existing agent and tool
    contracts. Worker nodes always return to the Supervisor, and the
    Supervisor selects the next worker through conditional edges.
    """

    router = supervisor or SupervisorRouter()
    builder = StateGraph(LangGraphState)

    def intent_node(envelope: LangGraphState) -> LangGraphState:
        state = _langgraph_state(envelope)
        state.routing.fulfilled_matrix = create_fulfilled_matrix(
            include_festivals=state.request.include_festivals,
        )
        _record_visit(state, "intent_agent")
        state.intent = _coerce_intent_state(nodes.intent(state))
        return {
            "state": state,
            "completed_group": None,
            "worker_status": None,
            "terminal_status": None,
        }

    def supervisor_node(envelope: LangGraphState) -> LangGraphState:
        state = _langgraph_state(envelope)
        _record_visit(state, SUPERVISOR_NODE_NAME)
        package = state.evidence.candidate_evidence_package
        decision = router.decide(
            fulfilled_matrix=state.routing.fulfilled_matrix,
            include_festivals=state.request.include_festivals,
            completed_group=envelope.get("completed_group"),
            worker_status=envelope.get("worker_status"),
            validation_retry_count=state.routing.validation_retry_count,
            planner_validation_result=(
                state.planning.validation_result
                if envelope.get("completed_group") == "planning"
                else None
            ),
            needs_clarification=state.routing.needs_clarification,
            clarifying_question=state.routing.clarifying_question,
            candidate_evidence_package=package,
        )
        _apply_route_decision(state, decision)
        if (
            envelope.get("completed_group") == "planning"
            and decision.next_node != NODE_PLANNER
            and state.planning.planner_output is not None
            and not _planner_validation_passed(
                state.planning.planner_output.validation_result,
            )
        ):
            state.planning.planner_output = None
        terminal_status = (
            CLARIFICATION_TERMINAL
            if decision.next_node == NODE_END_WAIT_USER
            else envelope.get("terminal_status")
        )
        return {
            "state": state,
            "completed_group": None,
            "worker_status": None,
            "terminal_status": terminal_status,
        }

    def candidate_node(envelope: LangGraphState) -> LangGraphState:
        state = _langgraph_state(envelope)
        _record_visit(state, NODE_CANDIDATE_EVIDENCE)
        package = _coerce_candidate_package(nodes.candidate_evidence(state))
        state.evidence.candidate_evidence_package = package
        return {
            "state": state,
            "completed_group": "evidence",
            "worker_status": package.status,
        }

    def festival_node(envelope: LangGraphState) -> LangGraphState:
        state = _langgraph_state(envelope)
        _record_visit(state, NODE_FESTIVAL_VERIFIER)
        state.festival.festival_verifications = _coerce_festival_verifications(
            nodes.festival_verifier(state),
        )
        return {
            "state": state,
            "completed_group": "festival",
            "worker_status": "ok",
        }

    def planner_node(envelope: LangGraphState) -> LangGraphState:
        state = _langgraph_state(envelope)
        _record_visit(state, NODE_PLANNER)
        planner_output = _coerce_planner_output(nodes.planner(state))
        state.planning.planner_output = planner_output
        state.planning.validation_result = dict(planner_output.validation_result)
        return {
            "state": state,
            "completed_group": "planning",
            "worker_status": None,
        }

    def response_node(envelope: LangGraphState) -> LangGraphState:
        state = _langgraph_state(envelope)
        _record_visit(state, NODE_RESPONSE_PACKAGER)
        status = envelope.get("terminal_status") or "completed"
        state.serving.response_status = status
        state.serving = ServingState(
            response_payload=dict(nodes.response_packager(state)),
            response_status=status,
        )
        return {"state": state, "terminal_status": status}

    builder.add_node("intent_agent", intent_node)
    builder.add_node(SUPERVISOR_NODE_NAME, supervisor_node)
    builder.add_node(NODE_CANDIDATE_EVIDENCE, candidate_node)
    builder.add_node(NODE_FESTIVAL_VERIFIER, festival_node)
    builder.add_node(NODE_PLANNER, planner_node)
    builder.add_node(NODE_RESPONSE_PACKAGER, response_node)

    builder.add_edge(START, "intent_agent")
    builder.add_edge("intent_agent", SUPERVISOR_NODE_NAME)
    builder.add_edge(NODE_CANDIDATE_EVIDENCE, SUPERVISOR_NODE_NAME)
    builder.add_edge(NODE_FESTIVAL_VERIFIER, SUPERVISOR_NODE_NAME)
    builder.add_edge(NODE_PLANNER, SUPERVISOR_NODE_NAME)
    builder.add_conditional_edges(
        SUPERVISOR_NODE_NAME,
        lambda envelope: _langgraph_state(envelope).routing.next_node,
        {
            NODE_CANDIDATE_EVIDENCE: NODE_CANDIDATE_EVIDENCE,
            NODE_FESTIVAL_VERIFIER: NODE_FESTIVAL_VERIFIER,
            NODE_PLANNER: NODE_PLANNER,
            NODE_RESPONSE_PACKAGER: NODE_RESPONSE_PACKAGER,
            NODE_END_WAIT_USER: NODE_RESPONSE_PACKAGER,
        },
    )
    builder.add_edge(NODE_RESPONSE_PACKAGER, END)
    return builder.compile()


def invoke_langgraph(
    graph: Any,
    state: UnifiedAgentState,
    *,
    config: Mapping[str, Any] | None = None,
) -> UnifiedAgentState:
    """Invoke a compiled Lovv LangGraph and return its canonical state."""

    if not isinstance(state, UnifiedAgentState):
        raise SchemaValidationError("state must be a UnifiedAgentState")
    result = graph.invoke({"state": state}, config=dict(config or {}))
    if not isinstance(result, Mapping):
        raise SchemaValidationError("compiled graph must return a mapping")
    return _langgraph_state(result)


def _langgraph_state(envelope: Mapping[str, Any]) -> UnifiedAgentState:
    """Read and validate the canonical state from a graph envelope."""

    state = envelope.get("state")
    if not isinstance(state, UnifiedAgentState):
        raise SchemaValidationError("LangGraph envelope.state must be UnifiedAgentState")
    return state


def _route_next(state: UnifiedAgentState, supervisor: SupervisorRouter) -> None:
    """Ask Supervisor for the next pending node."""

    _record_visit(state, SUPERVISOR_NODE_NAME)
    decision = supervisor.decide(
        fulfilled_matrix=state.routing.fulfilled_matrix,
        include_festivals=state.request.include_festivals,
        validation_retry_count=state.routing.validation_retry_count,
    )
    _apply_route_decision(state, decision)


def _route_completed(
    state: UnifiedAgentState,
    supervisor: SupervisorRouter,
    *,
    completed_group: str,
    worker_status: str | None = None,
    planner_validation_result: Mapping[str, Any] | None = None,
    candidate_evidence_package: CandidateEvidencePackage | None = None,
) -> None:
    """Ask Supervisor to process a completed worker result."""

    _record_visit(state, SUPERVISOR_NODE_NAME)
    decision = supervisor.decide(
        fulfilled_matrix=state.routing.fulfilled_matrix,
        include_festivals=state.request.include_festivals,
        completed_group=completed_group,
        worker_status=worker_status,
        validation_retry_count=state.routing.validation_retry_count,
        planner_validation_result=planner_validation_result,
        candidate_evidence_package=candidate_evidence_package,
    )
    _apply_route_decision(state, decision)


def _apply_route_decision(state: UnifiedAgentState, decision: Any) -> None:
    """Copy a Supervisor decision into routing state."""

    state.routing.next_node = decision.next_node
    state.routing.fulfilled_matrix = dict(decision.fulfilled_matrix)
    state.routing.validation_retry_count = decision.validation_retry_count
    state.routing.needs_clarification = decision.needs_clarification
    state.routing.clarifying_question = decision.clarifying_question


def _planner_validation_passed(validation_result: Mapping[str, Any]) -> bool:
    """Return whether Planner validation passed for safe response packaging."""

    for key in ("is_valid", "valid", "passed"):
        value = validation_result.get(key)
        if isinstance(value, bool):
            return value
    status = validation_result.get("status")
    return isinstance(status, str) and status.strip().lower() in {
        "valid",
        "ok",
        "passed",
        "success",
    }


def _package_and_finish(
    state: UnifiedAgentState,
    response_packager: ResponsePackagerNode,
    status: str,
) -> UnifiedAgentState:
    """Run Response Packager and mark serving status."""

    _record_visit(state, NODE_RESPONSE_PACKAGER)
    state.serving.response_status = status
    state.serving = ServingState(
        response_payload=dict(response_packager(state)),
        response_status=status,
    )
    return state


def _record_visit(state: UnifiedAgentState, node_name: str) -> None:
    """Append one node visit to trace metadata for integration tests."""

    visits = state.trace.node_timings.setdefault("visited_nodes", [])
    if not isinstance(visits, list):
        raise SchemaValidationError("trace.node_timings.visited_nodes must be a list")
    visits.append(node_name)


def _coerce_intent_state(result: IntentState | Mapping[str, Any]) -> IntentState:
    """Normalize Intent node output."""

    if isinstance(result, IntentState):
        return result
    if isinstance(result, Mapping):
        return IntentState(**dict(result))
    raise SchemaValidationError("intent node must return IntentState or mapping")


def _coerce_candidate_package(
    result: CandidateEvidencePackage | Mapping[str, Any],
) -> CandidateEvidencePackage:
    """Normalize Candidate Evidence node output."""

    if isinstance(result, CandidateEvidencePackage):
        return result
    if isinstance(result, Mapping):
        return CandidateEvidencePackage.from_mapping(result)
    raise SchemaValidationError("candidate evidence node must return package or mapping")


def _coerce_festival_verifications(
    result: Sequence[FestivalVerification | Mapping[str, Any]],
) -> tuple[FestivalVerification, ...]:
    """Normalize Festival Verifier node output."""

    if not isinstance(result, Sequence) or isinstance(result, (str, bytes)):
        raise SchemaValidationError("festival verifier node must return a sequence")
    return tuple(
        item
        if isinstance(item, FestivalVerification)
        else FestivalVerification.from_mapping(_mapping(item, "festival_verification"))
        for item in result
    )


def _coerce_planner_output(result: PlannerOutput | Mapping[str, Any]) -> PlannerOutput:
    """Normalize Planner node output."""

    if isinstance(result, PlannerOutput):
        return result
    if isinstance(result, Mapping):
        return PlannerOutput.from_mapping(result)
    raise SchemaValidationError("planner node must return PlannerOutput or mapping")


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    """Copy one mapping payload."""

    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return dict(value)


__all__ = [
    "CLARIFICATION_TERMINAL",
    "GRAPH_NODE_ORDER",
    "GraphNodeSet",
    "LangGraphState",
    "LocalGraphRuntime",
    "build_langgraph",
    "build_local_graph",
    "get_graph_skeleton",
    "invoke_langgraph",
]
