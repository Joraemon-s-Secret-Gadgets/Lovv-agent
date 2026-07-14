from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

EXPLANATION_MARKERS = (
    "planner_copy_generation_used_llm",
    "detail_enrichment_warning_count",
    "detail_enrichment_warnings",
    "itinerary_explanation_item_count",
)


def explanation_place_ids(applied_edit: Mapping[str, Any]) -> tuple[str, ...]:
    replacement = _mapping(applied_edit.get("replacement"))
    replacement_id = _optional_text(replacement.get("content_id"))
    if replacement_id is not None:
        return (replacement_id,)
    replacements = _mapping_sequence(applied_edit.get("replacements"))
    return tuple(
        content_id
        for item in replacements
        if (content_id := _optional_text(item.get("content_id"))) is not None
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
