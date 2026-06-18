"""Unified state schema for Lovv agent runs.

The state classes mirror the SPEC state groups and keep runtime data separated
by ownership. They are intentionally lightweight so future LangGraph nodes can
either pass dataclass instances directly or adapt them to TypedDict/Pydantic
models without changing the group contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from lovv_agent.models.schemas import (
    CandidateEvidenceInput,
    CandidateEvidencePackage,
    FestivalVerification,
    GeoPoint,
    PlannerOutput,
    SchemaValidationError,
    validate_clarification,
)

STATE_GROUPS: tuple[str, ...] = (
    # group 이름은 SPEC section을 반영해 trace snapshot을 예측 가능하게 한다.
    "request",
    "conversation",
    "trace",
    "intent",
    "routing",
    "evidence",
    "festival",
    "planning",
    "serving",
)

FULFILLED_MATRIX_KEYS: tuple[str, ...] = ("evidence", "festival", "planning")
# Supervisor routing은 이 compact matrix marker만 저장한다.
FULFILLED_MATRIX_STATUSES: tuple[str, ...] = ("X", "O", "△", "N/A")


def _text(value: str, field_name: str) -> str:
    """Validate a non-empty state string."""

    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: str | None, field_name: str) -> str | None:
    """Validate optional state text."""

    if value is None:
        return None
    return _text(value, field_name)


def _free_text(value: str, field_name: str) -> str:
    """Validate a state text field that may be empty."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    return value.strip()


def _month(value: int, field_name: str) -> int:
    """Validate a state month value."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value < 1 or value > 12:
        raise SchemaValidationError(f"{field_name} must be between 1 and 12")
    return value


def _string_tuple(value: tuple[str, ...] | list[str], field_name: str) -> tuple[str, ...]:
    """Validate and normalize a string sequence."""

    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    return tuple(_text(item, field_name) for item in value)


def _mapping(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    """Copy and validate a mapping field."""

    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return dict(value)


def validate_fulfilled_matrix(matrix: Mapping[str, str]) -> dict[str, str]:
    """Validate Supervisor matrix keys and status symbols."""

    normalized = _mapping(matrix, "fulfilled_matrix")
    missing = set(FULFILLED_MATRIX_KEYS) - set(normalized)
    extra = set(normalized) - set(FULFILLED_MATRIX_KEYS)
    if missing or extra:
        raise SchemaValidationError(
            "fulfilled_matrix keys must be evidence, festival, and planning",
        )
    for key, value in normalized.items():
        if value not in FULFILLED_MATRIX_STATUSES:
            allowed = ", ".join(FULFILLED_MATRIX_STATUSES)
            raise SchemaValidationError(f"fulfilled_matrix.{key} must be one of {allowed}")
    return normalized


def default_fulfilled_matrix() -> dict[str, str]:
    """Return the initial Supervisor matrix."""

    return {"evidence": "X", "festival": "X", "planning": "X"}


@dataclass(slots=True)
class RequestState:
    """Structured request fields that seed a graph run."""

    request_id: str
    entry_type: str
    country: str
    travel_year: int
    travel_month: int
    trip_type: str
    destination_id: str | None
    themes: tuple[str, ...]
    include_festivals: bool
    natural_language_query: str = ""
    user_location: GeoPoint | None = None

    def __post_init__(self) -> None:
        self.request_id = _text(self.request_id, "request_id")
        self.entry_type = _text(self.entry_type, "entry_type")
        self.country = _text(self.country, "country")
        if isinstance(self.travel_year, bool) or not isinstance(self.travel_year, int):
            raise SchemaValidationError("travel_year must be an integer")
        if self.travel_year < 1:
            raise SchemaValidationError("travel_year must be positive")
        self.travel_month = _month(self.travel_month, "travel_month")
        self.trip_type = _text(self.trip_type, "trip_type")
        self.destination_id = _optional_text(self.destination_id, "destination_id")
        self.themes = _string_tuple(self.themes, "themes")
        if not isinstance(self.include_festivals, bool):
            raise SchemaValidationError("include_festivals must be a boolean")
        self.natural_language_query = _free_text(
            self.natural_language_query,
            "natural_language_query",
        )


@dataclass(slots=True)
class ConversationState:
    """Conversation context allowed during a single graph run."""

    messages: tuple[dict[str, Any], ...] = ()
    conversation_summary: str | None = None
    turn_index: int = 0
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.turn_index < 0:
            raise SchemaValidationError("turn_index must be zero or positive")
        self.conversation_summary = _optional_text(
            self.conversation_summary,
            "conversation_summary",
        )
        self.session_id = _optional_text(self.session_id, "session_id")
        self.messages = tuple(_mapping(message, "messages") for message in self.messages)


@dataclass(slots=True)
class TraceState:
    """Trace identifiers and timing records for observability."""

    recommendation_request_id: str | None = None
    agent_run_id: str | None = None
    node_timings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.recommendation_request_id = _optional_text(
            self.recommendation_request_id,
            "recommendation_request_id",
        )
        self.agent_run_id = _optional_text(self.agent_run_id, "agent_run_id")
        self.node_timings = _mapping(self.node_timings, "node_timings")


@dataclass(slots=True)
class IntentState:
    """Intent Agent output and Candidate Evidence input."""

    extracted_inputs: dict[str, Any] = field(default_factory=dict)
    active_required_themes: tuple[str, ...] = ()
    searchable_place_themes: tuple[str, ...] = ()
    external_link_themes: tuple[str, ...] = ()
    cleaned_raw_query: str = ""
    soft_preference_query: str = ""
    unsupported_conditions: tuple[str, ...] = ()
    candidate_evidence_input: CandidateEvidenceInput | None = None

    def __post_init__(self) -> None:
        self.extracted_inputs = _mapping(self.extracted_inputs, "extracted_inputs")
        self.active_required_themes = _string_tuple(
            self.active_required_themes,
            "active_required_themes",
        )
        self.searchable_place_themes = _string_tuple(
            self.searchable_place_themes,
            "searchable_place_themes",
        )
        self.external_link_themes = _string_tuple(
            self.external_link_themes,
            "external_link_themes",
        )
        self.unsupported_conditions = _string_tuple(
            self.unsupported_conditions,
            "unsupported_conditions",
        )
        self.cleaned_raw_query = _free_text(self.cleaned_raw_query, "cleaned_raw_query")
        self.soft_preference_query = _free_text(
            self.soft_preference_query,
            "soft_preference_query",
        )


@dataclass(slots=True)
class RoutingState:
    """Supervisor routing state shared across graph nodes."""

    next_node: str | None = None
    fulfilled_matrix: dict[str, str] = field(default_factory=default_fulfilled_matrix)
    validation_retry_count: int = 0
    needs_clarification: bool = False
    clarifying_question: str | None = None

    def __post_init__(self) -> None:
        self.next_node = _optional_text(self.next_node, "next_node")
        self.fulfilled_matrix = validate_fulfilled_matrix(self.fulfilled_matrix)
        if self.validation_retry_count < 0:
            raise SchemaValidationError("validation_retry_count must be zero or positive")
        validate_clarification(self.needs_clarification, self.clarifying_question)


@dataclass(slots=True)
class EvidenceState:
    """Candidate Evidence Agent output stored for in-run Planner use."""

    candidate_evidence_package: CandidateEvidencePackage | None = None
    selected_destination: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.selected_destination is not None:
            self.selected_destination = _mapping(
                self.selected_destination,
                "selected_destination",
            )


@dataclass(slots=True)
class FestivalState:
    """Festival verification results for Planner policy."""

    festival_verifications: tuple[FestivalVerification, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.festival_verifications, (list, tuple)):
            raise SchemaValidationError("festival_verifications must be a sequence")
        self.festival_verifications = tuple(self.festival_verifications)


@dataclass(slots=True)
class PlanningState:
    """Planner output and validation status."""

    planner_output: PlannerOutput | None = None
    validation_result: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.validation_result is not None:
            self.validation_result = _mapping(self.validation_result, "validation_result")


@dataclass(slots=True)
class ServingState:
    """Deterministic response packaging output."""

    response_payload: dict[str, Any] | None = None
    response_status: str | None = None

    def __post_init__(self) -> None:
        if self.response_payload is not None:
            self.response_payload = _mapping(self.response_payload, "response_payload")
        self.response_status = _optional_text(self.response_status, "response_status")


@dataclass(slots=True)
class UnifiedAgentState:
    """Full graph state grouped by the canonical ownership boundaries."""

    request: RequestState
    conversation: ConversationState = field(default_factory=ConversationState)
    trace: TraceState = field(default_factory=TraceState)
    intent: IntentState = field(default_factory=IntentState)
    routing: RoutingState = field(default_factory=RoutingState)
    evidence: EvidenceState = field(default_factory=EvidenceState)
    festival: FestivalState = field(default_factory=FestivalState)
    planning: PlanningState = field(default_factory=PlanningState)
    serving: ServingState = field(default_factory=ServingState)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable state snapshot for tests and harness adapters."""

        return asdict(self)


__all__ = [
    "FULFILLED_MATRIX_KEYS",
    "FULFILLED_MATRIX_STATUSES",
    "STATE_GROUPS",
    "ConversationState",
    "EvidenceState",
    "FestivalState",
    "IntentState",
    "PlanningState",
    "RequestState",
    "RoutingState",
    "ServingState",
    "TraceState",
    "UnifiedAgentState",
    "default_fulfilled_matrix",
    "validate_fulfilled_matrix",
]
