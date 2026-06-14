"""Candidate Evidence Agent orchestration helpers.

The Candidate Evidence node owns the search-side preparation that happens after
Intent normalization and before Planner receives an internal evidence package.
Task 6.1 keeps this module deliberately small: it resolves the execution mode
and splits active travel themes into place-search and external-link groups.
Retrieval, scoring, festival seed lookup, and package construction are added by
later Task 6 subtasks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent.models.schemas import (
    CandidateEvidenceInput,
    CandidateEvidencePackage,
    SchemaValidationError,
    SelectedCity,
)
from lovv_agent.tools.candidate_selection import (
    CandidateSelectionHelper,
    candidate_budgets_for_trip,
)
from lovv_agent.tools.destination_search import AttractionCandidate
from lovv_agent.tools.scoring import PlaceScoreResult, ScoringTool

NODE_NAME = "candidate_evidence_agent"

RESPONSIBILITY = "Build grounded city/place evidence for Planner input."

OUT_OF_SCOPE = (
    "final_user_response",
    "itinerary_generation",
    "festival_date_verification",
)

CITY_DISCOVERY_MODE = "city_discovery"
ANCHORED_PLACE_SEARCH_MODE = "anchored_place_search"
FESTIVAL_SEEDED_CITY_DISCOVERY_MODE = "festival_seeded_city_discovery"

EXTERNAL_LINK_THEME_LABELS: frozenset[str] = frozenset({"미식·노포"})
FESTIVAL_THEME_MARKERS: frozenset[str] = frozenset(
    {
        "festival",
        "festival_event",
        "축제",
        "축제·이벤트",
    },
)


@dataclass(frozen=True, slots=True)
class CandidateThemeSplit:
    """Theme groups used by Candidate Evidence retrieval and downstream Planner.

    ``active_required_themes`` keeps user-selected travel themes that still
    matter to the recommendation. ``searchable_place_themes`` is the subset that
    can be used for attraction vector retrieval and scoring. ``external_link``
    themes are carried forward as selected-city CTA requirements instead of
    being searched in the attraction index.
    """

    active_required_themes: tuple[str, ...]
    searchable_place_themes: tuple[str, ...]
    external_link_themes: tuple[str, ...]
    ignored_theme_markers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidateEvidenceContext:
    """Resolved Candidate Evidence entry context for one graph run."""

    candidate_input: CandidateEvidenceInput
    mode: str
    theme_split: CandidateThemeSplit
    fixed_city_id: str | None
    include_festivals: bool


class CandidateEvidenceAgent:
    """Small orchestration facade for Candidate Evidence subtasks.

    The agent depends on injected runtime tools. This keeps AWS calls outside
    tests and makes the orchestration contract explicit: Candidate Evidence
    chooses the mode, calls attraction retrieval, scores and selects evidence,
    then returns an internal package without final detail enrichment.
    """

    def __init__(
        self,
        *,
        destination_search: Any | None = None,
        scoring: ScoringTool | None = None,
        selection: CandidateSelectionHelper | None = None,
    ) -> None:
        self.destination_search = destination_search
        self.scoring = scoring or ScoringTool()
        self.selection = selection or CandidateSelectionHelper()

    def prepare_context(
        self,
        candidate_input: CandidateEvidenceInput | Mapping[str, Any],
    ) -> CandidateEvidenceContext:
        """Validate input and resolve mode/theme groups for this node."""

        return prepare_candidate_evidence_context(candidate_input)

    def run(
        self,
        candidate_input: CandidateEvidenceInput | Mapping[str, Any],
        *,
        query_vector: Sequence[float],
    ) -> CandidateEvidencePackage:
        """Build a Candidate Evidence Package for non-festival search modes."""

        context = self.prepare_context(candidate_input)
        if self.destination_search is None:
            raise SchemaValidationError("destination_search tool is required")
        if context.mode == FESTIVAL_SEEDED_CITY_DISCOVERY_MODE:
            return _package_failure(
                context,
                status="error",
                failure_signal="festival_seed_flow_not_implemented",
                needs_clarification=False,
            )
        if not context.theme_split.searchable_place_themes:
            return _package_failure(
                context,
                status="no_candidate",
                failure_signal="no_searchable_place_theme",
                needs_clarification=True,
                clarifying_question="현재 조건에서는 검색 가능한 관광 테마가 없습니다.",
            )
        return _run_attraction_search(
            context=context,
            query_vector=query_vector,
            destination_search=self.destination_search,
            scoring=self.scoring,
            selection=self.selection,
        )


def prepare_candidate_evidence_context(
    candidate_input: CandidateEvidenceInput | Mapping[str, Any],
) -> CandidateEvidenceContext:
    """Return the deterministic Candidate Evidence entry context."""

    normalized_input = ensure_candidate_evidence_input(candidate_input)
    mode = resolve_candidate_evidence_mode(normalized_input)
    theme_split = split_candidate_themes(normalized_input.active_required_themes)
    fixed_city_id = normalized_input.destination_id if mode == ANCHORED_PLACE_SEARCH_MODE else None

    return CandidateEvidenceContext(
        candidate_input=normalized_input,
        mode=mode,
        theme_split=theme_split,
        fixed_city_id=fixed_city_id,
        include_festivals=normalized_input.include_festivals,
    )


def ensure_candidate_evidence_input(
    candidate_input: CandidateEvidenceInput | Mapping[str, Any],
) -> CandidateEvidenceInput:
    """Accept schema instances or mappings at the node boundary."""

    if isinstance(candidate_input, CandidateEvidenceInput):
        return candidate_input
    if isinstance(candidate_input, Mapping):
        return CandidateEvidenceInput.from_mapping(candidate_input)
    raise SchemaValidationError("candidate_evidence_input must be a schema or mapping")


def resolve_candidate_evidence_mode(candidate_input: CandidateEvidenceInput) -> str:
    """Resolve execution mode from ``destinationId`` and ``includeFestivals``.

    A fixed destination always selects anchored search. ``includeFestivals`` is
    still preserved on the context so Task 6.3 can run the fixed-city festival
    lookup before Planner consumes the package.
    """

    if candidate_input.destination_id is not None:
        return ANCHORED_PLACE_SEARCH_MODE
    if candidate_input.include_festivals:
        return FESTIVAL_SEEDED_CITY_DISCOVERY_MODE
    return CITY_DISCOVERY_MODE


def split_candidate_themes(themes: Sequence[str]) -> CandidateThemeSplit:
    """Split active travel themes into searchable and external-link groups."""

    active_required_themes: list[str] = []
    searchable_place_themes: list[str] = []
    external_link_themes: list[str] = []
    ignored_theme_markers: list[str] = []

    for theme in _unique_theme_labels(themes):
        if theme in FESTIVAL_THEME_MARKERS:
            ignored_theme_markers.append(theme)
            continue
        active_required_themes.append(theme)
        if theme in EXTERNAL_LINK_THEME_LABELS:
            external_link_themes.append(theme)
        else:
            searchable_place_themes.append(theme)

    return CandidateThemeSplit(
        active_required_themes=tuple(active_required_themes),
        searchable_place_themes=tuple(searchable_place_themes),
        external_link_themes=tuple(external_link_themes),
        ignored_theme_markers=tuple(ignored_theme_markers),
    )


def _unique_theme_labels(themes: Sequence[str]) -> tuple[str, ...]:
    """Return stable, stripped theme labels without duplicates."""

    if isinstance(themes, str) or not isinstance(themes, Sequence):
        raise SchemaValidationError("active_required_themes must be a sequence")

    unique_themes: list[str] = []
    for raw_theme in themes:
        if not isinstance(raw_theme, str):
            raise SchemaValidationError("active_required_themes must contain strings")
        theme = raw_theme.strip()
        if not theme:
            raise SchemaValidationError("active_required_themes cannot contain blanks")
        if theme not in unique_themes:
            unique_themes.append(theme)
    return tuple(unique_themes)


def _run_attraction_search(
    *,
    context: CandidateEvidenceContext,
    query_vector: Sequence[float],
    destination_search: Any,
    scoring: ScoringTool,
    selection: CandidateSelectionHelper,
) -> CandidateEvidencePackage:
    """Run retrieval, city scoring, final city selection, and quota selection."""

    retrieved = _retrieve_by_theme(
        destination_search,
        query_vector=query_vector,
        themes=context.theme_split.searchable_place_themes,
        city_id=context.fixed_city_id,
    )
    merged_candidates = _merge_duplicate_candidates(retrieved)
    allowed_city_ids = (context.fixed_city_id,) if context.fixed_city_id else None
    pruned_groups = destination_search.prune_cities(
        merged_candidates,
        context.theme_split.searchable_place_themes,
        allowed_city_ids=allowed_city_ids,
    )
    if not pruned_groups.survived_groups:
        return _package_failure(
            context,
            status="no_candidate",
            failure_signal="no_city_after_theme_gate",
            retrieval_audit=_retrieval_audit(
                context=context,
                retrieved_count=len(retrieved),
                merged_count=len(merged_candidates),
                survived_city_count=0,
                eliminated_cities=tuple(pruned_groups.eliminated_cities),
            ),
            needs_clarification=True,
            clarifying_question="현재 조건에 맞는 후보 도시를 찾지 못했습니다.",
        )

    primary_budget, reserve_budget = candidate_budgets_for_trip(
        context.candidate_input.trip_type,
    )
    scored_groups = _score_groups(
        pruned_groups.survived_groups,
        context=context,
        scoring=scoring,
    )
    city_rankings = _rank_cities(
        scored_groups,
        context=context,
        scoring=scoring,
        primary_budget=primary_budget,
    )
    if not city_rankings:
        return _package_failure(
            context,
            status="no_candidate",
            failure_signal="no_scored_city",
            retrieval_audit=_retrieval_audit(
                context=context,
                retrieved_count=len(retrieved),
                merged_count=len(merged_candidates),
                survived_city_count=len(pruned_groups.survived_groups),
                eliminated_cities=tuple(pruned_groups.eliminated_cities),
            ),
            needs_clarification=True,
            clarifying_question="현재 조건에 맞는 후보 도시를 찾지 못했습니다.",
        )

    selected_city_id = city_rankings[0]["city_id"]
    selected_group = scored_groups[selected_city_id]
    selected_places = selection.select_primary_with_theme_quotas(
        selected_group,
        context.theme_split.searchable_place_themes,
        primary_budget=primary_budget,
        reserve_budget=reserve_budget,
        required_themes=context.theme_split.active_required_themes,
        external_link_themes=context.theme_split.external_link_themes,
    )
    recommended_places = _lightweight_selected_places(selected_places.primary, selected_group)
    reserve_places = _lightweight_selected_places(selected_places.reserve, selected_group)
    status = _status_from_selection(selected_places.coverage_audit)
    selected_city = _selected_city(
        selected_city_id,
        selected_group,
        context=context,
        status=status,
    )

    return CandidateEvidencePackage(
        status=status,
        mode=context.mode,
        selected_city=selected_city,
        city_anchor=context.candidate_input.city_anchor,
        city_rankings=tuple(city_rankings),
        recommended_places=recommended_places,
        reserve_places=reserve_places,
        coverage_audit=selected_places.coverage_audit,
        retrieval_audit=_retrieval_audit(
            context=context,
            retrieved_count=len(retrieved),
            merged_count=len(merged_candidates),
            survived_city_count=len(pruned_groups.survived_groups),
            eliminated_cities=tuple(pruned_groups.eliminated_cities),
        ),
        candidate_counts={
            "retrieved": len(retrieved),
            "merged": len(merged_candidates),
            "scored": sum(len(group) for group in scored_groups.values()),
            "city_count": len(city_rankings),
            "recommended_places": len(recommended_places),
            "reserve_places": len(reserve_places),
        },
        fallback_audit={
            "planner_consumable": True,
            "status_reason": status,
        },
    )


def _retrieve_by_theme(
    destination_search: Any,
    *,
    query_vector: Sequence[float],
    themes: Sequence[str],
    city_id: str | None,
) -> tuple[AttractionCandidate, ...]:
    """Call attraction retrieval once per searchable theme."""

    candidates: list[AttractionCandidate] = []
    for theme in themes:
        candidates.extend(
            destination_search.search_candidates(
                query_vector,
                city_id=city_id,
                theme=theme,
            ),
        )
    return tuple(candidates)


def _merge_duplicate_candidates(
    candidates: Sequence[AttractionCandidate],
) -> tuple[AttractionCandidate, ...]:
    """Merge duplicate vector hits by stable ``place_id``."""

    by_place_id: dict[str, AttractionCandidate] = {}
    for candidate in candidates:
        previous = by_place_id.get(candidate.place_id)
        if previous is None or candidate.distance < previous.distance:
            by_place_id[candidate.place_id] = candidate
    return tuple(by_place_id.values())


def _score_groups(
    groups: Mapping[str, Sequence[AttractionCandidate]],
    *,
    context: CandidateEvidenceContext,
    scoring: ScoringTool,
) -> dict[str, tuple[PlaceScoreResult, ...]]:
    """Score each survived city's attraction candidates."""

    scored_groups: dict[str, tuple[PlaceScoreResult, ...]] = {}
    for city_id, candidates in groups.items():
        scored = tuple(
            result
            for candidate in candidates
            if (
                result := scoring.score_place(
                    candidate,
                    context.theme_split.searchable_place_themes,
                )
            ).scored
        )
        if scored:
            scored_groups[city_id] = scored
    return scored_groups


def _rank_cities(
    scored_groups: Mapping[str, Sequence[PlaceScoreResult]],
    *,
    context: CandidateEvidenceContext,
    scoring: ScoringTool,
    primary_budget: int,
) -> tuple[dict[str, Any], ...]:
    """Rank cities by deterministic city score."""

    rankings: list[dict[str, Any]] = []
    for city_id, places in scored_groups.items():
        city_score = scoring.score_city(
            city_id=city_id,
            places=places,
            active_themes=context.theme_split.searchable_place_themes,
            user_location=context.candidate_input.user_location,
            primary_budget=primary_budget,
        )
        ranking = city_score.to_dict()
        ranking["city_name_ko"] = _city_name_from_group(places) or city_id
        rankings.append(ranking)
    return tuple(
        sorted(
            rankings,
            key=lambda item: (item["city_score"], item["candidate_count"]),
            reverse=True,
        ),
    )


def _lightweight_selected_places(
    selected_payloads: Sequence[Mapping[str, Any]],
    scored_places: Sequence[PlaceScoreResult],
) -> tuple[dict[str, Any], ...]:
    """Return selected candidates without raw retrieval payloads or details."""

    scored_by_id = {place.place_id: place for place in scored_places}
    result: list[dict[str, Any]] = []
    for payload in selected_payloads:
        place_id = _mapping_text(payload, "place_id")
        scored = scored_by_id[place_id]
        result.append(
            {
                "place_id": scored.place_id,
                "title": scored.title,
                "city_id": scored.city_id,
                "city_name_ko": _candidate_attr(scored.place, "city_name_ko"),
                "theme_tags": list(scored.theme_tags),
                "latitude": scored.latitude,
                "longitude": scored.longitude,
                "ddb_pk": _candidate_attr(scored.place, "ddb_pk"),
                "ddb_sk": _candidate_attr(scored.place, "ddb_sk"),
                "slot_role": payload.get("slot_role"),
                "assigned_theme": payload.get("assigned_theme"),
                "score_audit": {
                    "place_score": scored.place_score,
                    "score_components": dict(scored.score_components),
                },
            },
        )
    return tuple(result)


def _status_from_selection(coverage_audit: Mapping[str, Any]) -> str:
    """Return package status from selected evidence coverage."""

    if coverage_audit.get("unfilled_primary_slots", 0) > 0:
        return "insufficient_candidates"
    if coverage_audit.get("candidate_sufficiency") == "insufficient":
        return "insufficient_candidates"
    return "ok"


def _selected_city(
    city_id: str,
    scored_places: Sequence[PlaceScoreResult],
    *,
    context: CandidateEvidenceContext,
    status: str,
) -> SelectedCity:
    """Build the selected city summary for Planner input."""

    reason_codes = ["anchored_city"] if context.fixed_city_id else ["city_score_rank_1"]
    if status == "ok":
        reason_codes.append("candidate_sufficiency")
    else:
        reason_codes.append("insufficient_candidates")
    return SelectedCity(
        city_id=city_id,
        city_name_ko=_city_name_from_group(scored_places) or city_id,
        country=context.candidate_input.country,
        selection_reason_code=tuple(reason_codes),
    )


def _package_failure(
    context: CandidateEvidenceContext,
    *,
    status: str,
    failure_signal: str,
    needs_clarification: bool,
    clarifying_question: str | None = None,
    retrieval_audit: Mapping[str, Any] | None = None,
) -> CandidateEvidencePackage:
    """Build a valid failure package at the Candidate Evidence boundary."""

    return CandidateEvidencePackage(
        status=status,
        failure_signals=(failure_signal,),
        needs_clarification=needs_clarification,
        clarifying_question=clarifying_question,
        mode=context.mode,
        city_anchor=context.candidate_input.city_anchor,
        retrieval_audit=dict(retrieval_audit or {}),
        candidate_counts={},
        fallback_audit={
            "planner_consumable": False,
            "failure_signal": failure_signal,
        },
    )


def _retrieval_audit(
    *,
    context: CandidateEvidenceContext,
    retrieved_count: int,
    merged_count: int,
    survived_city_count: int,
    eliminated_cities: Sequence[str],
) -> dict[str, Any]:
    """Build compact retrieval audit fields for review/debug."""

    return {
        "mode": context.mode,
        "searchable_place_themes": list(context.theme_split.searchable_place_themes),
        "external_link_themes": list(context.theme_split.external_link_themes),
        "fixed_city_id": context.fixed_city_id,
        "retrieved_candidate_count": retrieved_count,
        "merged_candidate_count": merged_count,
        "survived_city_count": survived_city_count,
        "eliminated_cities": list(eliminated_cities),
    }


def _city_name_from_group(scored_places: Sequence[PlaceScoreResult]) -> str | None:
    """Read the first available city display name from scored evidence."""

    for place in scored_places:
        city_name = _candidate_attr(place.place, "city_name_ko")
        if isinstance(city_name, str) and city_name.strip():
            return city_name.strip()
    return None


def _candidate_attr(candidate: Any, field_name: str) -> Any:
    """Read a lightweight candidate field from dataclass/object/mapping."""

    if isinstance(candidate, Mapping):
        return candidate.get(field_name)
    return getattr(candidate, field_name, None)


def _mapping_text(payload: Mapping[str, Any], field_name: str) -> str:
    """Read a required text field from a mapping."""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


__all__ = [
    "ANCHORED_PLACE_SEARCH_MODE",
    "CITY_DISCOVERY_MODE",
    "EXTERNAL_LINK_THEME_LABELS",
    "FESTIVAL_SEEDED_CITY_DISCOVERY_MODE",
    "FESTIVAL_THEME_MARKERS",
    "NODE_NAME",
    "OUT_OF_SCOPE",
    "RESPONSIBILITY",
    "CandidateEvidenceAgent",
    "CandidateEvidenceContext",
    "CandidateThemeSplit",
    "ensure_candidate_evidence_input",
    "prepare_candidate_evidence_context",
    "resolve_candidate_evidence_mode",
    "split_candidate_themes",
]
