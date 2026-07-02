from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from time import time
from typing import Any, Protocol

from lovv_agent_v2.models.profile import LovvUserProfile, THEME_ID_TO_LABEL


THEME_LABEL_TO_ID = {label: theme_id for theme_id, label in THEME_ID_TO_LABEL.items()}


class SavedItinerarySignalsTool(Protocol):
    def fetch_saved_itinerary_signals(
        self,
        *,
        actor_id: str,
        thread_id: str,
        recent_limit: int,
        liked_limit: int,
    ) -> Mapping[str, Any] | None: ...


class ProfileEvidenceCache(Protocol):
    def get(
        self,
        key: ProfileEvidenceCacheKey,
        *,
        now_epoch: float,
    ) -> ProfileEvidenceRecord | None: ...

    def put(
        self,
        key: ProfileEvidenceCacheKey,
        record: ProfileEvidenceRecord,
        *,
        now_epoch: float,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ProfileEvidenceCacheKey:
    actor_id: str
    thread_id: str


@dataclass(frozen=True, slots=True)
class SavedPlaceEvidence:
    place_name: str
    content_id: str | None
    place_id: str | None
    day_index: int | None
    sort_order: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "place_name": self.place_name,
            "content_id": self.content_id,
            "place_id": self.place_id,
            "day_index": self.day_index,
            "sort_order": self.sort_order,
        }


@dataclass(frozen=True, slots=True)
class TripStyleEvidence:
    trip_type: str | None
    duration_label: str | None
    preference_snapshot: Mapping[str, Any]
    conditions_snapshot_json: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trip_type": self.trip_type,
            "duration_label": self.duration_label,
            "preference_snapshot": dict(self.preference_snapshot),
            "conditions_snapshot_json": dict(self.conditions_snapshot_json),
        }


@dataclass(frozen=True, slots=True)
class ProfileEvidenceRecord:
    actor_id: str
    thread_id: str
    lovv_user_profile: LovvUserProfile
    destinations: tuple[Mapping[str, Any], ...]
    places: tuple[SavedPlaceEvidence, ...]
    trip_styles: tuple[TripStyleEvidence, ...]
    liked_itinerary_count: int
    source: str

    def to_profile_record(self) -> dict[str, Any]:
        return {
            "profile_id": f"saved-itinerary://{self.actor_id}",
            "actor_id": self.actor_id,
            "profile_status": "found",
            "lovv_user_profile": {
                "saved_trip_count": self.lovv_user_profile.saved_trip_count,
                "saved_theme_counts": dict(self.lovv_user_profile.saved_theme_counts),
            },
            "saved_itinerary_evidence": {
                "source": self.source,
                "thread_id": self.thread_id,
                "destinations": [dict(destination) for destination in self.destinations],
                "places": [place.to_dict() for place in self.places],
                "trip_styles": [style.to_dict() for style in self.trip_styles],
                "liked_itinerary_count": self.liked_itinerary_count,
            },
        }


@dataclass(frozen=True, slots=True)
class ProfileEvidenceResolution:
    record: ProfileEvidenceRecord | None
    audit: Mapping[str, Any]


@dataclass(slots=True)
class InMemoryProfileEvidenceCache:
    ttl_seconds: int
    _entries: dict[ProfileEvidenceCacheKey, tuple[float, ProfileEvidenceRecord]] = field(
        default_factory=dict,
        init=False,
    )

    def get(
        self,
        key: ProfileEvidenceCacheKey,
        *,
        now_epoch: float,
    ) -> ProfileEvidenceRecord | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, record = entry
        if expires_at <= now_epoch:
            self._entries.pop(key, None)
            return None
        return record

    def put(
        self,
        key: ProfileEvidenceCacheKey,
        record: ProfileEvidenceRecord,
        *,
        now_epoch: float,
    ) -> None:
        self._entries[key] = (now_epoch + self.ttl_seconds, record)


@dataclass(frozen=True, slots=True)
class ProfileEvidenceResolver:
    cache: ProfileEvidenceCache
    tool: SavedItinerarySignalsTool | None
    clock: Callable[[], float] = time
    recent_limit: int = 5
    liked_limit: int = 5

    def resolve(
        self,
        *,
        actor_id: str | None,
        thread_id: str | None,
    ) -> ProfileEvidenceResolution:
        if not actor_id or not thread_id:
            return ProfileEvidenceResolution(
                record=None,
                audit={
                    "cache_status": "skipped",
                    "fallback_reason": "skipped_no_actor",
                },
            )

        key = ProfileEvidenceCacheKey(actor_id=actor_id, thread_id=thread_id)
        now_epoch = self.clock()
        try:
            cached = self.cache.get(key, now_epoch=now_epoch)
        except Exception:  # noqa: BROAD_EXCEPT_OK
            return ProfileEvidenceResolution(
                record=None,
                audit={
                    "cache_status": "read_failed",
                    "fallback_reason": "cache_read_failed",
                },
            )
        if cached is not None:
            return ProfileEvidenceResolution(
                record=cached,
                audit={"cache_status": "hit"},
            )
        if self.tool is None:
            return ProfileEvidenceResolution(
                record=None,
                audit={
                    "cache_status": "miss",
                    "fallback_reason": "skipped_no_tool",
                },
            )

        try:
            signals = self.tool.fetch_saved_itinerary_signals(
                actor_id=actor_id,
                thread_id=thread_id,
                recent_limit=self.recent_limit,
                liked_limit=self.liked_limit,
            )
        except Exception:  # noqa: BROAD_EXCEPT_OK
            return ProfileEvidenceResolution(
                record=None,
                audit={
                    "cache_status": "miss",
                    "fallback_reason": "tool_failed",
                },
            )

        record = build_profile_evidence_record(
            signals,
            actor_id=actor_id,
            thread_id=thread_id,
        )
        if record is None:
            return ProfileEvidenceResolution(
                record=None,
                audit={
                    "cache_status": "miss",
                    "fallback_reason": "no_evidence",
                },
            )

        audit: dict[str, Any] = {"cache_status": "miss", "tool_status": "success"}
        try:
            self.cache.put(key, record, now_epoch=now_epoch)
        except Exception:  # noqa: BROAD_EXCEPT_OK
            audit["cache_write_status"] = "write_failed"
        else:
            audit["cache_write_status"] = "stored"
        return ProfileEvidenceResolution(record=record, audit=audit)

    def enrich_graph_payload(
        self,
        payload: Mapping[str, Any],
        *,
        actor_id: str | None,
        thread_id: str | None,
    ) -> dict[str, Any]:
        resolution = self.resolve(actor_id=actor_id, thread_id=thread_id)
        enriched = dict(payload)
        profile_value = enriched.get("profile", {})
        profile = dict(profile_value) if isinstance(profile_value, Mapping) else {}
        if resolution.record is not None:
            profile["profile_record"] = resolution.record.to_profile_record()
        profile["saved_itinerary_evidence_audit"] = dict(resolution.audit)
        enriched["profile"] = profile
        return enriched


def build_profile_evidence_record(
    payload: Mapping[str, Any] | None,
    *,
    actor_id: str,
    thread_id: str,
) -> ProfileEvidenceRecord | None:
    if not isinstance(payload, Mapping):
        return None
    saved_trip_count = _optional_int(payload.get("saved_trip_count"))
    if saved_trip_count is None and "saved_trip_count" in payload:
        return None

    recent_itineraries = _mapping_tuple(payload.get("recent_itineraries", ()))
    liked_itineraries = _mapping_tuple(payload.get("liked_itineraries", ()))
    if recent_itineraries is None or liked_itineraries is None:
        return None

    theme_counts = {theme_id: 0 for theme_id in THEME_ID_TO_LABEL}
    destinations: list[Mapping[str, Any]] = []
    places: list[SavedPlaceEvidence] = []
    trip_styles: list[TripStyleEvidence] = []

    _add_aggregate_themes(theme_counts, payload.get("themes"))
    for itinerary in recent_itineraries:
        _add_itinerary_evidence(
            itinerary,
            theme_counts=theme_counts,
            destinations=destinations,
            places=places,
            trip_styles=trip_styles,
            weight=1,
        )
    for itinerary in liked_itineraries:
        _add_itinerary_evidence(
            itinerary,
            theme_counts=theme_counts,
            destinations=destinations,
            places=places,
            trip_styles=trip_styles,
            weight=1,
        )

    liked_count = len(liked_itineraries)
    effective_saved_trip_count = max(
        saved_trip_count or 0,
        len(recent_itineraries) + liked_count,
    )
    if effective_saved_trip_count <= 0 and not any(theme_counts.values()):
        return None

    return ProfileEvidenceRecord(
        actor_id=actor_id,
        thread_id=thread_id,
        lovv_user_profile=LovvUserProfile(
            saved_trip_count=effective_saved_trip_count,
            saved_theme_counts=theme_counts,
        ),
        destinations=tuple(destinations),
        places=tuple(places),
        trip_styles=tuple(trip_styles),
        liked_itinerary_count=liked_count,
        source=_text_or_default(payload.get("source"), "saved_itinerary_signals_tool"),
    )


def _add_aggregate_themes(theme_counts: dict[str, int], value: Any) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return
    for item in value:
        if isinstance(item, Mapping):
            theme_id = _theme_id(item.get("theme_id") or item.get("id") or item.get("label"))
            count = _optional_int(item.get("count")) or 0
            liked_count = _optional_int(item.get("liked_count")) or 0
            if theme_id is not None:
                theme_counts[theme_id] += count + liked_count
        else:
            theme_id = _theme_id(item)
            if theme_id is not None:
                theme_counts[theme_id] += 1


def _add_itinerary_evidence(
    itinerary: Mapping[str, Any],
    *,
    theme_counts: dict[str, int],
    destinations: list[Mapping[str, Any]],
    places: list[SavedPlaceEvidence],
    trip_styles: list[TripStyleEvidence],
    weight: int,
) -> None:
    destination = itinerary.get("destination_json")
    if isinstance(destination, Mapping):
        destinations.append(dict(destination))
    for theme_id in _theme_ids(itinerary.get("themes_json") or itinerary.get("themes")):
        theme_counts[theme_id] += weight
    trip_styles.append(
        TripStyleEvidence(
            trip_type=_text_or_none(itinerary.get("trip_type")),
            duration_label=_text_or_none(itinerary.get("duration_label")),
            preference_snapshot=_mapping_or_empty(itinerary.get("preference_snapshot")),
            conditions_snapshot_json=_mapping_or_empty(
                itinerary.get("conditions_snapshot_json"),
            ),
        ),
    )
    for item in _mapping_tuple(itinerary.get("items", ())) or ():
        place = _place_from_mapping(item)
        if place is not None:
            places.append(place)


def _theme_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        theme_id = _theme_id(value)
        return (theme_id,) if theme_id is not None else ()
    if not isinstance(value, Sequence):
        return ()
    ids: list[str] = []
    for item in value:
        theme_id = _theme_id(item)
        if theme_id is not None:
            ids.append(theme_id)
    return tuple(ids)


def _theme_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized in THEME_ID_TO_LABEL:
        return normalized
    return THEME_LABEL_TO_ID.get(normalized)


def _place_from_mapping(item: Mapping[str, Any]) -> SavedPlaceEvidence | None:
    place_name = _text_or_none(item.get("place_name"))
    if place_name is None:
        return None
    return SavedPlaceEvidence(
        place_name=place_name,
        content_id=_text_or_none(item.get("content_id")),
        place_id=_text_or_none(item.get("place_id")),
        day_index=_optional_int(item.get("day_index")),
        sort_order=_optional_int(item.get("sort_order")),
    )


def _mapping_tuple(value: Any) -> tuple[Mapping[str, Any], ...] | None:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        return None
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        result.append(item)
    return tuple(result)


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _text_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _text_or_default(value: Any, default: str) -> str:
    return _text_or_none(value) or default


__all__ = [
    "InMemoryProfileEvidenceCache",
    "ProfileEvidenceCache",
    "ProfileEvidenceCacheKey",
    "ProfileEvidenceRecord",
    "ProfileEvidenceResolution",
    "ProfileEvidenceResolver",
    "SavedItinerarySignalsTool",
    "build_profile_evidence_record",
]
