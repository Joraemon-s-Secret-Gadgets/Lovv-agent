"""Candidate Evidence Agent orchestration helpers.

The Candidate Evidence node owns the search-side preparation that happens after
Intent normalization and before Planner receives an internal evidence package.
Task 6.1 keeps this module deliberately small: it resolves the execution mode
and splits active travel themes into place-search and external-link groups.
Retrieval, scoring, festival seed lookup, and package construction are added by
later Task 6 subtasks.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from lovv_agent.adapters.bedrock_converse import (
    RuntimeInvoker,
    build_structured_converse_request,
    invoke_structured_output,
)
from lovv_agent.config import DEFAULT_SCHEMA_RETRY_LIMIT
from lovv_agent.models.schemas import (
    CandidateEvidenceInput,
    CandidateEvidencePackage,
    CandidateReasonClaim,
    SchemaValidationError,
    SelectedCity,
)
from lovv_agent.prompts.registry import (
    CANDIDATE_REASON_CLAIM_PROMPT_ID,
    prompt_text,
)
from lovv_agent.tools.candidate_selection import (
    CandidateSelectionHelper,
    candidate_budgets_for_trip,
    itinerary_place_count_for_trip,
)
from lovv_agent.tools.destination_search import AttractionCandidate
from lovv_agent.tools.dynamo_lookup import FestivalCandidate, FestivalSeedResult
from lovv_agent.tools.scoring import PlaceScoreResult, ScoringTool

NODE_NAME = "candidate_evidence_agent"

RESPONSIBILITY = "Build grounded city/place evidence for Planner input."

OUT_OF_SCOPE = (
    "final_user_response",
    "itinerary_generation",
    "festival_date_verification",
)

# 실행 mode 상수는 Intent와 Candidate Evidence 계약이 공유하므로
# 누적 task report와 맞도록 문자열 값을 안정적으로 유지한다.
CITY_DISCOVERY_MODE = "city_discovery"
ANCHORED_PLACE_SEARCH_MODE = "anchored_place_search"
FESTIVAL_SEEDED_CITY_DISCOVERY_MODE = "festival_seeded_city_discovery"

# 미식과 축제 요청은 일반 관광지 vector 검색이 아니다.
EXTERNAL_LINK_THEME_LABELS: frozenset[str] = frozenset({"미식·노포"})
FESTIVAL_THEME_MARKERS: frozenset[str] = frozenset(
    {
        "festival",
        "festival_event",
        "축제",
        "축제·이벤트",
    },
)

CANDIDATE_REASON_CLAIM_SCHEMA_NAME = "candidate_reason_claim_output"
CANDIDATE_REASON_CLAIM_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidate_reason_claims"],
    "properties": {
        "candidate_reason_claims": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "claim_id",
                    "scope",
                    "text_ko",
                    "evidence_refs",
                    "required_place_ids",
                    "public_eligible",
                ],
                "properties": {
                    "claim_id": {"type": "string"},
                    "scope": {
                        "type": "string",
                        "enum": [
                            "city_selection",
                            "place_pool",
                            "festival_anchor",
                            "candidate_shortage",
                            "external_link_policy",
                            "fallback_notice",
                        ],
                    },
                    "text_ko": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "required_place_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "public_eligible": {"type": "boolean"},
                },
            },
        },
    },
}

REASON_CLAIM_UNSAFE_TOKENS: tuple[str, ...] = (
    "place_score",
    "score_components",
    "raw_s3_uri",
    "raw retrieval",
    "topK",
    "top_k",
    "vector distance",
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
        dynamo_lookup: Any | None = None,
        scoring: ScoringTool | None = None,
        selection: CandidateSelectionHelper | None = None,
        reason_claim_runtime: RuntimeInvoker | None = None,
        schema_retry_limit: int = DEFAULT_SCHEMA_RETRY_LIMIT,
    ) -> None:
        self.destination_search = destination_search
        self.dynamo_lookup = dynamo_lookup
        self.scoring = scoring or ScoringTool()
        self.selection = selection or CandidateSelectionHelper()
        self.reason_claim_runtime = reason_claim_runtime
        self.schema_retry_limit = schema_retry_limit

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
        soft_query_vector: Sequence[float] | None = None,
    ) -> CandidateEvidencePackage:
        """Build a Candidate Evidence Package for non-festival search modes."""

        context = self.prepare_context(candidate_input)
        if self.destination_search is None:
            raise SchemaValidationError("destination_search tool is required")
        festival_seed_result: FestivalSeedResult | None = None
        allowed_city_ids: tuple[str, ...] | None = None
        if context.include_festivals:
            festival_seed_result = _run_festival_seed_lookup(
                context=context,
                dynamo_lookup=self.dynamo_lookup,
            )
            if festival_seed_result.status != "ok":
                return _festival_seed_failure_package(context, festival_seed_result)
            allowed_city_ids = (
                (context.fixed_city_id,)
                if context.fixed_city_id is not None
                else festival_seed_result.seed_city_ids
            )
        if not context.theme_split.searchable_place_themes:
            return _package_failure(
                context,
                status="no_candidate",
                failure_signal="no_searchable_place_theme",
                needs_clarification=True,
                clarifying_question="현재 조건에서는 검색 가능한 관광 테마가 없습니다.",
                festival_seed_result=festival_seed_result,
            )
        package = _run_attraction_search(
            context=context,
            query_vector=query_vector,
            soft_query_vector=soft_query_vector,
            destination_search=self.destination_search,
            scoring=self.scoring,
            selection=self.selection,
            allowed_city_ids=allowed_city_ids,
            festival_seed_result=festival_seed_result,
        )
        return _attach_candidate_reason_claims(
            package,
            context=context,
            runtime=self.reason_claim_runtime,
            retry_limit=self.schema_retry_limit,
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
    soft_query_vector: Sequence[float] | None = None,
    destination_search: Any,
    scoring: ScoringTool,
    selection: CandidateSelectionHelper,
    allowed_city_ids: Sequence[str] | None = None,
    festival_seed_result: FestivalSeedResult | None = None,
) -> CandidateEvidencePackage:
    """Run retrieval, city scoring, final city selection, and quota selection."""

    retrieved = _retrieve_by_theme(
        destination_search,
        query_vector=query_vector,
        soft_query_vector=soft_query_vector,
        themes=context.theme_split.searchable_place_themes,
        city_id=context.fixed_city_id,
    )
    merged_candidates = _merge_duplicate_candidates(retrieved)
    allowed = _allowed_city_ids(context=context, allowed_city_ids=allowed_city_ids)
    pruned_groups = destination_search.prune_cities(
        merged_candidates,
        context.theme_split.searchable_place_themes,
        allowed_city_ids=allowed,
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
            festival_seed_result=festival_seed_result,
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
            festival_seed_result=festival_seed_result,
        )

    required_place_count = itinerary_place_count_for_trip(
        context.candidate_input.trip_type,
    )
    selection_by_city = {
        ranking["city_id"]: selection.select_primary_with_theme_quotas(
            scored_groups[ranking["city_id"]],
            context.theme_split.searchable_place_themes,
            primary_budget=primary_budget,
            reserve_budget=reserve_budget,
            required_themes=context.theme_split.active_required_themes,
            external_link_themes=context.theme_split.external_link_themes,
        )
        for ranking in city_rankings
    }
    selected_rank_index = _select_city_rank_index(
        city_rankings,
        selection_by_city=selection_by_city,
        required_place_count=required_place_count,
        fixed_city_id=context.fixed_city_id,
    )
    selected_city_id = city_rankings[selected_rank_index]["city_id"]
    selected_group = scored_groups[selected_city_id]
    selected_places = selection_by_city[selected_city_id]
    recommended_places = _lightweight_selected_places(selected_places.primary, selected_group)
    reserve_places = _lightweight_selected_places(selected_places.reserve, selected_group)
    available_place_count = len(recommended_places)
    coverage_audit = _itinerary_coverage_audit(
        selected_places.coverage_audit,
        required_place_count=required_place_count,
        available_place_count=available_place_count,
    )
    status = _status_from_selection(
        required_place_count=required_place_count,
        available_place_count=available_place_count,
    )
    selected_city = _selected_city(
        selected_city_id,
        selected_group,
        context=context,
        status=status,
        selected_rank_index=selected_rank_index,
    )
    annotated_rankings = _annotate_city_rankings(
        city_rankings,
        selection_by_city=selection_by_city,
        required_place_count=required_place_count,
        selected_city_id=selected_city_id,
    )

    return CandidateEvidencePackage(
        status=status,
        mode=context.mode,
        selected_city=selected_city,
        city_anchor=context.candidate_input.city_anchor,
        city_rankings=annotated_rankings,
        recommended_places=recommended_places,
        reserve_places=reserve_places,
        festival_candidates=_festival_candidate_payloads(festival_seed_result),
        selected_festival_candidates=_festival_candidate_payloads(
            festival_seed_result,
            city_id=selected_city_id,
        ),
        festival_seed_audit=_festival_seed_audit(festival_seed_result),
        coverage_audit=coverage_audit,
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
            "available_places": available_place_count,
            "required_itinerary_places": required_place_count,
            "reserve_places_considered_for_itinerary": False,
        },
        fallback_audit={
            "planner_consumable": True,
            "status_reason": status,
            "festival_seed_applied": festival_seed_result is not None,
            "selected_city_rank": selected_rank_index + 1,
            "city_reselected_for_itinerary_capacity": selected_rank_index > 0,
        },
    )


def _run_festival_seed_lookup(
    *,
    context: CandidateEvidenceContext,
    dynamo_lookup: Any | None,
) -> FestivalSeedResult:
    """Run month/theme festival seed lookup before attraction retrieval."""

    theme_pool = context.theme_split.active_required_themes
    if not theme_pool:
        return FestivalSeedResult(
            status="no_candidate",
            failure_signals=("no_required_theme_for_festival_seed",),
            needs_clarification=True,
        )
    if dynamo_lookup is None:
        return FestivalSeedResult(
            status="error",
            failure_signals=("festival_lookup_tool_required",),
            needs_clarification=False,
        )
    return dynamo_lookup.search_festival_city_seeds(
        country=context.candidate_input.country,
        travel_month=context.candidate_input.travel_month,
        theme_pool=theme_pool,
        city_id=context.fixed_city_id,
    )


def _festival_seed_failure_package(
    context: CandidateEvidenceContext,
    festival_seed_result: FestivalSeedResult,
) -> CandidateEvidencePackage:
    """Build the hard-gate failure package for festival seed misses."""

    failure_signals = festival_seed_result.failure_signals or (
        "festival_seed_lookup_failed",
    )
    clarifying_question = (
        "현재 조건에 맞는 축제 후보가 없습니다. 여행 월이나 테마를 조정해 주세요."
        if festival_seed_result.needs_clarification
        else None
    )
    return _package_failure(
        context,
        status=festival_seed_result.status,
        failure_signal=failure_signals[0],
        failure_signals=failure_signals,
        needs_clarification=festival_seed_result.needs_clarification,
        clarifying_question=clarifying_question,
        festival_seed_result=festival_seed_result,
    )


def build_candidate_reason_claim_request(
    package: CandidateEvidencePackage,
    *,
    context: CandidateEvidenceContext,
) -> dict[str, Any]:
    """Build a schema-enforced Korean claim-generation request."""

    safe_summary = _reason_claim_safe_summary(package, context=context)
    return build_structured_converse_request(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": json.dumps(safe_summary, ensure_ascii=False),
                    },
                ],
            },
        ],
        system=[
            {
                "text": prompt_text(CANDIDATE_REASON_CLAIM_PROMPT_ID),
            },
        ],
        schema_name=CANDIDATE_REASON_CLAIM_SCHEMA_NAME,
        schema=CANDIDATE_REASON_CLAIM_OUTPUT_SCHEMA,
        schema_description="Candidate Evidence Korean reason claim candidates",
    )


def validate_candidate_reason_claim_output(
    payload: Mapping[str, Any],
) -> tuple[CandidateReasonClaim, ...]:
    """Validate model-produced Candidate Evidence reason claims."""

    if not isinstance(payload, Mapping):
        raise SchemaValidationError("candidate reason claim output must be an object")
    if set(payload) != {"candidate_reason_claims"}:
        raise SchemaValidationError(
            "candidate reason claim output contains unsupported fields",
        )
    raw_claims = payload.get("candidate_reason_claims")
    if not isinstance(raw_claims, (list, tuple)) or not raw_claims:
        raise SchemaValidationError("candidate_reason_claims must be a non-empty list")
    claims = tuple(CandidateReasonClaim.from_mapping(item) for item in raw_claims)
    for claim in claims:
        _validate_reason_claim_safety(claim)
    return claims


def _attach_candidate_reason_claims(
    package: CandidateEvidencePackage,
    *,
    context: CandidateEvidenceContext,
    runtime: RuntimeInvoker | None,
    retry_limit: int,
) -> CandidateEvidencePackage:
    """Attach claim candidates without changing package decisions."""

    if not _package_permits_reason_claims(package):
        return package
    if runtime is None:
        return replace(
            package,
            candidate_reason_claims=_template_reason_claims(package, context=context),
        )

    request = build_candidate_reason_claim_request(package, context=context)
    result = invoke_structured_output(
        runtime=runtime,
        request=request,
        retry_limit=retry_limit,
        validator=validate_candidate_reason_claim_output,
    )
    if result.ok:
        return replace(package, candidate_reason_claims=result.value)

    warnings = dict(package.warnings)
    warnings["candidate_reason_claim_generation"] = {
        "status": "schema_failure",
        "attempts": result.attempts,
        "validation_errors": list(result.validation_errors),
    }
    return replace(
        package,
        candidate_reason_claims=_template_reason_claims(
            package,
            context=context,
            public_eligible=False,
        ),
        warnings=warnings,
    )


def _package_permits_reason_claims(package: CandidateEvidencePackage) -> bool:
    """Return whether Planner may consume this package for claim validation."""

    return (
        package.status in {"ok", "insufficient_candidates"}
        and package.selected_city is not None
        and not package.needs_clarification
    )


def _template_reason_claims(
    package: CandidateEvidencePackage,
    *,
    context: CandidateEvidenceContext,
    public_eligible: bool = True,
) -> tuple[CandidateReasonClaim, ...]:
    """Build deterministic fallback claim candidates from safe package fields."""

    claims: list[CandidateReasonClaim] = [
        CandidateReasonClaim(
            claim_id="city_reason_1",
            scope="city_selection",
            text_ko="선택 도시는 요청 테마 후보를 바탕으로 추천 후보가 구성되었습니다.",
            evidence_refs=("selected_city", "city_rankings:selected", "coverage_audit"),
            required_place_ids=(),
            public_eligible=public_eligible,
        ),
    ]
    place_ids = tuple(
        str(place["place_id"])
        for place in package.recommended_places[:3]
        if isinstance(place.get("place_id"), str)
    )
    if place_ids:
        claims.append(
            CandidateReasonClaim(
                claim_id="place_pool_1",
                scope="place_pool",
                text_ko="대표 후보들은 사용자의 여행 테마와 연결되는 관광지 후보입니다.",
                evidence_refs=tuple(f"recommended_places:{place_id}" for place_id in place_ids),
                required_place_ids=place_ids,
                public_eligible=public_eligible,
            ),
        )
    if package.selected_festival_candidates:
        claims.append(
            CandidateReasonClaim(
                claim_id="festival_anchor_1",
                scope="festival_anchor",
                text_ko="선택 도시에 여행 월과 테마가 맞는 축제 후보가 있습니다.",
                evidence_refs=("selected_festival_candidates", "festival_seed_audit"),
                required_place_ids=(),
                public_eligible=public_eligible,
            ),
        )
    external_themes = package.coverage_audit.get("external_link_themes", [])
    if external_themes:
        claims.append(
            CandidateReasonClaim(
                claim_id="external_link_policy_1",
                scope="external_link_policy",
                text_ko="미식 테마는 선택 도시 기준 외부 음식 검색 링크로 이어집니다.",
                evidence_refs=("coverage_audit.external_link_themes",),
                required_place_ids=(),
                public_eligible=public_eligible,
            ),
        )
    if package.status == "insufficient_candidates":
        claims.append(
            CandidateReasonClaim(
                claim_id="candidate_shortage_1",
                scope="candidate_shortage",
                text_ko="후보 수가 충분하지 않아 Planner 단계에서 보수적으로 처리해야 합니다.",
                evidence_refs=("coverage_audit", "candidate_counts"),
                required_place_ids=(),
                public_eligible=False,
            ),
        )
    return tuple(claims[:5])


def _reason_claim_safe_summary(
    package: CandidateEvidencePackage,
    *,
    context: CandidateEvidenceContext,
) -> dict[str, Any]:
    """Return LLM-visible evidence without raw scores or raw retrieval payloads."""

    return {
        "status": package.status,
        "mode": package.mode,
        "selected_city": _selected_city_summary(package.selected_city),
        "active_required_themes": list(context.theme_split.active_required_themes),
        "searchable_place_themes": list(context.theme_split.searchable_place_themes),
        "external_link_themes": list(context.theme_split.external_link_themes),
        "raw_query": context.candidate_input.cleaned_raw_query,
        "soft_query": context.candidate_input.soft_preference_query,
        "recommended_places": [
            {
                "place_id": place.get("place_id"),
                "title": place.get("title"),
                "theme_tags": place.get("theme_tags", []),
                "assigned_theme": place.get("assigned_theme"),
            }
            for place in package.recommended_places[:5]
        ],
        "selected_festival_candidates": [
            {
                "festival_id": festival.get("festival_id"),
                "name": festival.get("name"),
                "city_id": festival.get("city_id"),
                "assigned_theme": festival.get("assigned_theme"),
                "theme_tags": festival.get("theme_tags", []),
            }
            for festival in package.selected_festival_candidates[:3]
        ],
        "coverage_audit_summary": {
            "candidate_sufficiency": package.coverage_audit.get("candidate_sufficiency"),
            "unfilled_primary_slots": package.coverage_audit.get(
                "unfilled_primary_slots",
            ),
            "min_quota_shortfalls": package.coverage_audit.get(
                "min_quota_shortfalls",
                {},
            ),
        },
        "candidate_counts": dict(package.candidate_counts),
    }


def _validate_reason_claim_safety(claim: CandidateReasonClaim) -> None:
    """Reject claim text that leaks raw retrieval or scoring implementation data."""

    haystack = " ".join(
        (
            claim.text_ko,
            *claim.evidence_refs,
            *claim.required_place_ids,
        ),
    )
    lowered = haystack.casefold()
    for token in REASON_CLAIM_UNSAFE_TOKENS:
        if token.casefold() in lowered:
            raise SchemaValidationError(
                f"candidate reason claim includes unsafe internal token: {token}",
            )


def _selected_city_summary(selected_city: SelectedCity | None) -> dict[str, Any] | None:
    """Return an LLM-visible selected city summary."""

    if selected_city is None:
        return None
    return {
        "city_id": selected_city.city_id,
        "city_name_ko": selected_city.city_name_ko,
        "country": selected_city.country,
        "selection_reason_code": list(selected_city.selection_reason_code),
    }


def _retrieve_by_theme(
    destination_search: Any,
    *,
    query_vector: Sequence[float],
    themes: Sequence[str],
    city_id: str | None,
    soft_query_vector: Sequence[float] | None = None,
) -> tuple[AttractionCandidate, ...]:
    """Call attraction retrieval once per searchable theme.

    soft_query_vector가 주어지면 같은 테마로 soft 임베딩 검색을 한 번 더 수행해
    후보별 soft_distance를 주입한다. ScoringTool은 이 soft_distance로 soft_similarity를
    계산하므로 soft preference가 실제 랭킹에 반영된다.
    """

    candidates: list[AttractionCandidate] = []
    for theme in themes:
        theme_candidates = list(
            destination_search.search_candidates(
                query_vector,
                city_id=city_id,
                theme=theme,
            ),
        )
        if soft_query_vector is not None:
            soft_distance_by_place = {
                candidate.place_id: candidate.distance
                for candidate in destination_search.search_candidates(
                    soft_query_vector,
                    city_id=city_id,
                    theme=theme,
                )
            }
            theme_candidates = [
                replace(candidate, soft_distance=soft_distance_by_place[candidate.place_id])
                if candidate.place_id in soft_distance_by_place
                else candidate
                for candidate in theme_candidates
            ]
        candidates.extend(theme_candidates)
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


def _select_city_rank_index(
    city_rankings: Sequence[Mapping[str, Any]],
    *,
    selection_by_city: Mapping[str, Any],
    required_place_count: int,
    fixed_city_id: str | None,
) -> int:
    """Select the highest-ranked city that can fill the itinerary."""

    if fixed_city_id is not None:
        return 0
    for index, ranking in enumerate(city_rankings):
        selected = selection_by_city[str(ranking["city_id"])]
        if len(selected.primary) >= required_place_count:
            return index
    return 0


def _annotate_city_rankings(
    city_rankings: Sequence[Mapping[str, Any]],
    *,
    selection_by_city: Mapping[str, Any],
    required_place_count: int,
    selected_city_id: str,
) -> tuple[dict[str, Any], ...]:
    """Attach itinerary-capacity audit fields to each city ranking."""

    annotated: list[dict[str, Any]] = []
    for ranking in city_rankings:
        city_id = str(ranking["city_id"])
        selected = selection_by_city[city_id]
        available_place_count = len(selected.primary)
        payload = dict(ranking)
        payload.update(
            {
                "available_place_count": available_place_count,
                "required_place_count": required_place_count,
                "itinerary_sufficient": available_place_count >= required_place_count,
                "selected": city_id == selected_city_id,
            },
        )
        annotated.append(payload)
    return tuple(annotated)


def _itinerary_coverage_audit(
    coverage_audit: Mapping[str, Any],
    *,
    required_place_count: int,
    available_place_count: int,
) -> dict[str, Any]:
    """Extend quota audit with primary-only Planner capacity."""

    result = dict(coverage_audit)
    result.update(
        {
            "itinerary_required_place_count": required_place_count,
            "available_place_count": available_place_count,
            "reserve_places_considered": False,
            "itinerary_sufficiency": (
                "sufficient"
                if available_place_count >= required_place_count
                else "insufficient"
            ),
        },
    )
    return result


def _status_from_selection(
    *,
    required_place_count: int,
    available_place_count: int,
) -> str:
    """Return package status from Planner-facing itinerary capacity."""

    if available_place_count < required_place_count:
        return "insufficient_candidates"
    return "ok"


def _selected_city(
    city_id: str,
    scored_places: Sequence[PlaceScoreResult],
    *,
    context: CandidateEvidenceContext,
    status: str,
    selected_rank_index: int,
) -> SelectedCity:
    """Build the selected city summary for Planner input."""

    reason_codes = (
        ["anchored_city"]
        if context.fixed_city_id
        else [f"city_score_rank_{selected_rank_index + 1}"]
    )
    if selected_rank_index > 0:
        reason_codes.append("itinerary_capacity_fallback")
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
    failure_signals: Sequence[str] | None = None,
    needs_clarification: bool,
    clarifying_question: str | None = None,
    retrieval_audit: Mapping[str, Any] | None = None,
    festival_seed_result: FestivalSeedResult | None = None,
) -> CandidateEvidencePackage:
    """Build a valid failure package at the Candidate Evidence boundary."""

    return CandidateEvidencePackage(
        status=status,
        failure_signals=tuple(failure_signals or (failure_signal,)),
        needs_clarification=needs_clarification,
        clarifying_question=clarifying_question,
        mode=context.mode,
        city_anchor=context.candidate_input.city_anchor,
        festival_candidates=_festival_candidate_payloads(festival_seed_result),
        selected_festival_candidates=(),
        festival_seed_audit=_festival_seed_audit(festival_seed_result),
        retrieval_audit=dict(retrieval_audit or {}),
        candidate_counts={},
        fallback_audit={
            "planner_consumable": False,
            "failure_signal": failure_signal,
            "festival_seed_applied": festival_seed_result is not None,
        },
    )


def _allowed_city_ids(
    *,
    context: CandidateEvidenceContext,
    allowed_city_ids: Sequence[str] | None,
) -> tuple[str, ...] | None:
    """Return the city pool restriction for prune/scoring."""

    if allowed_city_ids is not None:
        normalized = tuple(dict.fromkeys(allowed_city_ids))
        return normalized or None
    if context.fixed_city_id is not None:
        return (context.fixed_city_id,)
    return None


def _festival_candidate_payloads(
    festival_seed_result: FestivalSeedResult | None,
    *,
    city_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Serialize festival candidates, optionally limited to one selected city."""

    if festival_seed_result is None:
        return ()
    return tuple(
        _festival_candidate_payload(candidate)
        for candidate in festival_seed_result.candidates
        if city_id is None or candidate.city_id == city_id
    )


def _festival_candidate_payload(candidate: FestivalCandidate) -> dict[str, Any]:
    """Return a compact festival candidate payload for the internal package."""

    return {
        "festival_id": candidate.festival_id,
        "name": candidate.name,
        "country": candidate.country,
        "city_id": candidate.city_id,
        "city_name": candidate.city_name,
        "month": candidate.month,
        "theme": candidate.theme,
        "theme_tags": list(candidate.theme_tags),
        "assigned_theme": candidate.assigned_theme,
        "event_start_date": candidate.event_start_date,
        "event_end_date": candidate.event_end_date,
        "source": candidate.source,
    }


def _festival_seed_audit(
    festival_seed_result: FestivalSeedResult | None,
) -> dict[str, Any]:
    """Return compact festival seed audit fields."""

    if festival_seed_result is None:
        return {}
    return {
        "status": festival_seed_result.status,
        "candidate_count": len(festival_seed_result.candidates),
        "seed_city_ids": list(festival_seed_result.seed_city_ids),
        "failure_signals": list(festival_seed_result.failure_signals),
        "needs_clarification": festival_seed_result.needs_clarification,
    }


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
    "CANDIDATE_REASON_CLAIM_OUTPUT_SCHEMA",
    "CANDIDATE_REASON_CLAIM_SCHEMA_NAME",
    "ensure_candidate_evidence_input",
    "build_candidate_reason_claim_request",
    "prepare_candidate_evidence_context",
    "resolve_candidate_evidence_mode",
    "split_candidate_themes",
    "validate_candidate_reason_claim_output",
]
