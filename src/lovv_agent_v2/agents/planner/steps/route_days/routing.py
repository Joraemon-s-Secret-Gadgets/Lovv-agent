from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from lovv_agent_v2.agents.planner.domain.place_model import PlannerPlace, selection_sort_key
from lovv_agent_v2.agents.planner.steps.route_days.day_profile import day_place_targets, trip_day_count
from lovv_agent_v2.agents.planner.steps.route_days.route_metrics import (
    DurationLookup,
    day_travel_min,
    max_leg_min,
    travel_time_from_group,
)

MAX_DRIVE_LEG_MIN = 60.0
MAX_DRIVE_DAY_MIN = 150.0


@dataclass(frozen=True, slots=True)
class RoutedPlace:
    place: PlannerPlace
    move_min_from_prev: int


@dataclass(frozen=True, slots=True)
class RouteDay:
    day: int
    anchor_place_id: str
    anchor_type: str
    places: tuple[RoutedPlace, ...]
    day_travel_min: int


@dataclass(frozen=True, slots=True)
class RoutingResult:
    days: tuple[RouteDay, ...]
    reserve: tuple[PlannerPlace, ...]
    audit: dict[str, object]


def route_days(
    places: Sequence[PlannerPlace],
    *,
    trip_type: str,
    transport_pref: str,
    durations: Mapping[tuple[str, str], float] | None = None,
    provider_audit: Mapping[str, object] | None = None,
) -> RoutingResult:
    lookup = DurationLookup(durations)
    if not places:
        return RoutingResult(days=(), reserve=(), audit=_audit(transport_pref, False, (), provider_audit))
    day_count = trip_day_count(trip_type)
    sorted_places = tuple(sorted(places, key=_sort_key, reverse=True))
    anchors = _anchors(sorted_places, day_count, lookup)
    day_targets = day_place_targets(trip_type, len(anchors))
    assignments = _assign_to_anchor_days(sorted_places, anchors, lookup, day_targets)
    reserve: list[PlannerPlace] = []
    days: list[RouteDay] = []
    for index, anchor in enumerate(anchors, start=1):
        assigned = assignments.get(anchor.place_id, (anchor,))
        ordered = _nearest_neighbor_order(assigned, anchor, lookup)
        kept, trimmed = _trim_over_limit(ordered, lookup)
        reserve.extend(trimmed)
        routed = _routed_places(kept, lookup)
        days.append(
            RouteDay(
                day=index,
                anchor_place_id=anchor.place_id,
                anchor_type="seed" if anchor.is_seed else "medoid",
                places=routed,
                day_travel_min=sum(place.move_min_from_prev for place in routed),
            ),
        )
    audit = _audit(transport_pref, _is_compact(days), tuple(reserve), provider_audit)
    audit["day_place_targets"] = day_targets
    audit["place_density_policy"] = "edge_days_lighter"
    return RoutingResult(days=tuple(days), reserve=tuple(reserve), audit=audit)


def _anchors(
    places: Sequence[PlannerPlace],
    day_count: int,
    lookup: DurationLookup,
) -> tuple[PlannerPlace, ...]:
    seeds = tuple(place for place in places if place.is_seed)
    anchors = list(seeds[:day_count])
    candidates = [place for place in places if place.place_id not in {a.place_id for a in anchors}]
    while len(anchors) < day_count and candidates:
        medoid = _medoid(candidates, lookup)
        anchors.append(medoid)
        candidates.remove(medoid)
    return tuple(anchors) if anchors else (places[0],)


def _assign_to_anchor_days(
    places: Sequence[PlannerPlace],
    anchors: Sequence[PlannerPlace],
    lookup: DurationLookup,
    day_targets: Sequence[int],
) -> dict[str, tuple[PlannerPlace, ...]]:
    buckets: dict[str, list[PlannerPlace]] = {anchor.place_id: [anchor] for anchor in anchors}
    target_by_anchor = {
        anchor.place_id: max(day_targets[index], 1)
        for index, anchor in enumerate(anchors)
    }
    anchor_ids = set(buckets)
    for place in places:
        if place.place_id in anchor_ids:
            continue
        anchor = min(
            anchors,
            key=lambda item: (
                len(buckets[item.place_id]) >= target_by_anchor[item.place_id],
                lookup.minutes(item, place),
                len(buckets[item.place_id]),
            ),
        )
        buckets[anchor.place_id].append(place)
    return {place_id: tuple(bucket) for place_id, bucket in buckets.items()}


def _nearest_neighbor_order(
    places: Sequence[PlannerPlace],
    anchor: PlannerPlace,
    lookup: DurationLookup,
) -> tuple[PlannerPlace, ...]:
    remaining = [place for place in places if place.place_id != anchor.place_id]
    ordered = [anchor]
    while remaining:
        previous = ordered[-1]
        next_place = min(remaining, key=lambda place: lookup.minutes(previous, place))
        ordered.append(next_place)
        remaining.remove(next_place)
    return tuple(ordered)


def _trim_over_limit(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> tuple[tuple[PlannerPlace, ...], tuple[PlannerPlace, ...]]:
    kept = list(places)
    trimmed: list[PlannerPlace] = []
    while len(kept) > 1 and (
        day_travel_min(tuple(kept), lookup) > MAX_DRIVE_DAY_MIN
        or max_leg_min(tuple(kept), lookup) > MAX_DRIVE_LEG_MIN
    ):
        candidate = _leg_limit_candidate(kept, lookup)
        if candidate is None:
            candidate = max(
                (place for place in kept if not place.is_seed),
                key=lambda place: travel_time_from_group(place, tuple(kept), lookup),
                default=None,
            )
        if candidate is None:
            break
        kept.remove(candidate)
        trimmed.append(candidate)
    return tuple(kept), tuple(trimmed)


def _routed_places(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> tuple[RoutedPlace, ...]:
    routed: list[RoutedPlace] = []
    previous: PlannerPlace | None = None
    for place in places:
        move_min = 0 if previous is None else round(lookup.minutes(previous, place))
        routed.append(RoutedPlace(place=place, move_min_from_prev=move_min))
        previous = place
    return tuple(routed)


def _medoid(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> PlannerPlace:
    return min(
        places,
        key=lambda place: (
            sum(lookup.minutes(place, other) for other in places),
            -place.similarity,
        ),
    )


def _leg_limit_candidate(
    places: Sequence[PlannerPlace],
    lookup: DurationLookup,
) -> PlannerPlace | None:
    worst_pair = max(
        zip(places, places[1:]),
        key=lambda pair: lookup.minutes(pair[0], pair[1]),
        default=None,
    )
    if worst_pair is None or lookup.minutes(worst_pair[0], worst_pair[1]) <= MAX_DRIVE_LEG_MIN:
        return None
    removable = tuple(place for place in worst_pair if not place.is_seed)
    if not removable:
        return None
    return min(removable, key=_sort_key)


def _is_compact(days: Sequence[RouteDay]) -> bool:
    leg_minutes = [
        routed.move_min_from_prev
        for day in days
        for routed in day.places
        if routed.move_min_from_prev > 0
    ]
    return bool(leg_minutes) and max(leg_minutes) <= 30


def _audit(
    transport_pref: str,
    compact_walkable: bool,
    reserve: Sequence[PlannerPlace],
    provider_audit: Mapping[str, object] | None,
) -> dict[str, object]:
    notice = "walkable_compact_city" if transport_pref == "walk" and compact_walkable else ""
    if transport_pref == "walk" and not compact_walkable:
        notice = "walking_preference_requires_transit_or_car"
    audit: dict[str, object] = {
        "duration_unit": "minutes",
        "duration_profile": "driving",
        "fallback_used": "haversine_duration",
        "max_leg_min": MAX_DRIVE_LEG_MIN,
        "day_limit_min": MAX_DRIVE_DAY_MIN,
        "outlier_anchor_policy": "medoid_not_farthest",
        "transport_notice": notice,
        "trimmed_place_ids": [place.place_id for place in reserve],
    }
    if provider_audit is not None:
        audit.update(provider_audit)
    return audit


def _sort_key(place: PlannerPlace) -> tuple[bool, float, float, float]:
    return selection_sort_key(place)
