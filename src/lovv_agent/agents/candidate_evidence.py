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

from lovv_agent.models.schemas import CandidateEvidenceInput, SchemaValidationError

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

    The class intentionally exposes preparation only in Task 6.1. Later subtasks
    extend it with retrieval, scoring, festival seed gating, package building,
    and reason-claim generation while preserving this deterministic entry
    contract.
    """

    def prepare_context(
        self,
        candidate_input: CandidateEvidenceInput | Mapping[str, Any],
    ) -> CandidateEvidenceContext:
        """Validate input and resolve mode/theme groups for this node."""

        return prepare_candidate_evidence_context(candidate_input)


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
