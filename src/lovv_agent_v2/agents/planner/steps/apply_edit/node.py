from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from lovv_agent_v2.agents.intent.modify_current_order import current_order
from lovv_agent_v2.agents.planner.domain.place_model import (
    PlannerPlace,
    coerce_place,
    selection_sort_key,
)
from lovv_agent_v2.agents.planner.state.context import candidate_payloads, planner_city_input, runtime_tools
from lovv_agent_v2.agents.planner.steps.route_days.route_metrics import DurationLookup, max_leg_min
from lovv_agent_v2.agents.planner.steps.route_days.trim_policy import MAX_HARD_LEG_MIN
from lovv_agent_v2.agents.planner.steps.apply_edit.current_order_snapshot import request_with_current_order
from lovv_agent_v2.agents.planner.steps.apply_edit.result import (
    applied_update,
    failed_update,
    finalized_update,
)


def apply_edit_node(state: Mapping[str, Any]) -> dict[str, Any]:
    modify_intent = _modify_intent(state)
    operations = _operations(modify_intent)
    if not operations:
        return failed_update(state, _failed_edit("modify_multi_edit_deferred"))
    current_state: Mapping[str, Any] = state
    for operation in operations:
        current_state = _merged_state(current_state, _apply_operation(current_state, operation))
    return finalized_update(current_state, len(operations))


def _apply_operation(state: Mapping[str, Any], operation: Mapping[str, Any]) -> dict[str, Any]:
    order = current_order(_request(state), state)
    target = _target_item(order, _mapping(operation.get("target")))
    if target is None:
        return failed_update(
            state,
            _failed_edit(
                "modify_target_unresolved",
                requested_target=_mapping(operation.get("target")),
            ),
        )
    candidates = _candidate_pool(state, operation, target)
    selected, failed_route_count = _first_feasible_candidate(candidates, order, target)
    if selected is None:
        reason = "slot_replace_route_infeasible" if candidates else "slot_replace_no_candidate"
        return failed_update(
            state,
            _failed_edit(
                reason,
                target=target,
                tried_candidate_count=len(candidates),
                failed_route_candidate_count=failed_route_count,
            ),
        )
    return applied_update(state, operation, order, target, selected, candidates)


def _merged_state(state: Mapping[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    next_state = dict(state)
    next_state.update(update)
    if "planner" in update:
        next_state["request"] = request_with_current_order(next_state)
    return next_state


def _candidate_pool(
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    target: Mapping[str, Any],
) -> tuple[PlannerPlace, ...]:
    condition = _mapping(operation.get("condition"))
    query = _optional_text(condition.get("replacement_query"))
    payloads = _retrieved_candidates(state, operation, target, query) if query else _reserve_pool(state)
    excluded = _excluded_ids(state, target, condition)
    candidates = tuple(
        _seed_adjusted(_coerced(candidate), operation, target)
        for candidate in payloads
        if _candidate_id(candidate) not in excluded and _same_destination(candidate, state, target)
    )
    themes = _preferred_themes(state, condition, target)
    sorted_candidates = sorted(candidates, key=selection_sort_key, reverse=True)
    if not themes:
        return tuple(sorted_candidates)
    preferred = [place for place in sorted_candidates if _matches_any_theme(place, themes)]
    others = [place for place in sorted_candidates if not _matches_any_theme(place, themes)]
    return tuple((*preferred, *others))


def _retrieved_candidates(
    state: Mapping[str, Any],
    operation: Mapping[str, Any],
    target: Mapping[str, Any],
    query: str,
) -> tuple[Mapping[str, Any], ...]:
    runtime = runtime_tools(state)
    if runtime is None:
        return ()
    condition = _mapping(operation.get("condition"))
    return candidate_payloads(
        runtime.destination_search.search_candidates(
            runtime.embedding.embed_query(query),
            top_k=50,
            city_id=_destination_id(state, target),
            ddb_pk=None,
            theme=_optional_text(condition.get("theme")),
        ),
        similarity_key="raw_similarity",
    )


def _first_feasible_candidate(
    candidates: Sequence[PlannerPlace],
    order: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
) -> tuple[PlannerPlace | None, int]:
    failed_route_count = 0
    for candidate in candidates:
        if _day_max_leg(order, target, candidate) <= MAX_HARD_LEG_MIN:
            return candidate, failed_route_count
        failed_route_count += 1
    return None, failed_route_count


def _day_max_leg(
    order: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    candidate: PlannerPlace,
) -> float:
    places = tuple(
        candidate if _same_slot(item, target) else _order_place(item)
        for item in sorted(order, key=lambda item: (_int(item.get("day")), _int(item.get("order"))))
        if _int(item.get("day")) == _int(target.get("day"))
    )
    return max_leg_min(places, DurationLookup())


def _reserve_pool(state: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    planner = _planner_group(state)
    context = _mapping(planner.get("modify_context"))
    value = context.get("reserve_pool")
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _excluded_ids(
    state: Mapping[str, Any],
    target: Mapping[str, Any],
    condition: Mapping[str, Any],
) -> set[str]:
    excluded = {_candidate_id(item) for item in current_order(_request(state), state)}
    excluded.update(str(item) for item in condition.get("avoid_content_ids", ()) if isinstance(item, str))
    memory = _mapping(state.get("memory"))
    history = _mapping(memory.get("modify_history"))
    excluded.update(str(item) for item in history.get("replaced_content_ids", ()) if isinstance(item, str))
    target_id = _optional_text(target.get("contentId", target.get("content_id")))
    if target_id is not None:
        excluded.add(target_id)
    return {item for item in excluded if item}


def _coerced(candidate: Mapping[str, Any]) -> PlannerPlace:
    return coerce_place(candidate)


def _seed_adjusted(place: PlannerPlace, operation: Mapping[str, Any], target: Mapping[str, Any]) -> PlannerPlace:
    policy = _mapping(operation.get("seed_policy"))
    if policy.get("policy") != "same_theme_required":
        return place
    required = _optional_text(policy.get("required_theme")) or _optional_text(target.get("theme"))
    if required is None or required in place.theme_tags:
        return replace(place, is_seed=True)
    return place


def _preferred_themes(
    state: Mapping[str, Any],
    condition: Mapping[str, Any],
    target: Mapping[str, Any],
) -> tuple[str, ...]:
    explicit_theme = _optional_text(condition.get("theme"))
    if explicit_theme is not None:
        return (explicit_theme,)
    active_themes = tuple(
        theme
        for theme in planner_city_input(state).get("active_required_themes", ())
        if isinstance(theme, str) and theme.strip()
    )
    if active_themes:
        return active_themes
    target_theme = _optional_text(target.get("theme"))
    return (target_theme,) if target_theme is not None else ()


def _matches_any_theme(place: PlannerPlace, themes: Sequence[str]) -> bool:
    return any(theme in place.theme_tags for theme in themes)


def _same_destination(candidate: Mapping[str, Any], state: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    destination_id = _destination_id(state, target)
    city_id = _optional_text(candidate.get("city_id", candidate.get("cityId")))
    return city_id is None or destination_id is None or city_id == destination_id


def _destination_id(state: Mapping[str, Any], target: Mapping[str, Any]) -> str | None:
    request = _request(state)
    modify = _modify_intent(state)
    city_input = planner_city_input(state)
    for value in (
        request.get("destinationId", request.get("destination_id")),
        modify.get("destination_id"),
        city_input.get("destination_id"),
        target.get("cityId", target.get("city_id")),
    ):
        text = _optional_text(value)
        if text is not None:
            return text
    return None


def _order_place(item: Mapping[str, Any]) -> PlannerPlace:
    content_id = _optional_text(item.get("contentId", item.get("content_id"))) or "unknown"
    theme = _optional_text(item.get("theme"))
    return PlannerPlace(
        place_id=content_id,
        title=str(item.get("title", content_id)),
        theme_tags=(theme,) if theme else (),
        similarity=0.0,
        soft_similarity=0.0,
        latitude=_float(item.get("latitude")),
        longitude=_float(item.get("longitude")),
        payload=dict(item),
        is_seed=item.get("isSeed") is True,
    )


def _target_item(
    order: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    for item in order:
        if _same_slot(item, target):
            return item
    return None


def _same_slot(item: Mapping[str, Any], target: Mapping[str, Any]) -> bool:
    return _int(item.get("day")) == _int(target.get("day")) and _int(item.get("order")) == _int(target.get("order"))


def _operations(modify_intent: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    ops = modify_intent.get("edit_ops")
    if not isinstance(ops, list):
        return ()
    return tuple(op for op in ops if isinstance(op, Mapping))


def _failed_edit(reason_code: str, **fields: Any) -> dict[str, Any]:
    return {
        "reason_code": reason_code,
        "suggested_theme_expansion_options": ("broaden_theme", "active_themes_only"),
        **fields,
    }


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("contentId", candidate.get("content_id", candidate.get("place_id", candidate.get("placeId"))))
    return value.strip() if isinstance(value, str) else ""


def _request(state: Mapping[str, Any]) -> Mapping[str, Any]:
    request = state.get("request")
    return request if isinstance(request, Mapping) else {}


def _modify_intent(state: Mapping[str, Any]) -> Mapping[str, Any]:
    intent = _mapping(state.get("intent"))
    modify = intent.get("modify_intent")
    return modify if isinstance(modify, Mapping) else {}


def _planner_group(state: Mapping[str, Any]) -> dict[str, Any]:
    planner = state.get("planner")
    return dict(planner) if isinstance(planner, Mapping) else {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
