from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, assert_never

from lovv_agent_v2.agents.intent.validator import validate_preference_sets

PreferencePolarity = Literal["preferred", "disliked"]

THEME_ID_TO_LABEL: Final[dict[str, str]] = {
    "sea_coast": "바다·해안",
    "nature_trekking": "자연·트레킹",
    "history_tradition": "역사·전통",
    "art_sense": "예술·감성",
    "healing_rest": "온천·휴양",
    "food_local": "미식·노포",
}

REGION_ID_TO_LABEL: Final[dict[str, str]] = {
    "gangwon": "강원도",
    "gyeongbuk": "경북",
    "sokcho": "속초",
    "andong": "안동",
    "gyeongju": "경주",
    "gangneung": "강릉",
    "samcheok": "삼척",
    "yeongju": "영주",
    "uljin": "울진",
}

_THEME_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "sea_coast": ("바다", "해안", "해변", "바닷가", "오션", "섬"),
    "nature_trekking": ("자연", "트레킹", "등산", "숲길", "숲", "산책", "산"),
    "history_tradition": ("역사", "전통", "유적", "문화재", "고택", "한옥"),
    "art_sense": ("예술", "감성", "전시", "미술관", "갤러리", "공방"),
    "healing_rest": ("온천", "휴양", "힐링", "스파", "쉼", "쉬는"),
    "food_local": ("미식", "맛집", "노포", "로컬 맛", "음식", "먹거리"),
}

_REGION_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "gangwon": ("강원", "강원도"),
    "gyeongbuk": ("경북", "경상북도"),
    "sokcho": ("속초",),
    "andong": ("안동",),
    "gyeongju": ("경주",),
    "gangneung": ("강릉",),
    "samcheok": ("삼척",),
    "yeongju": ("영주",),
    "uljin": ("울진",),
}

_NEGATIVE_SEPARATORS: Final[tuple[str, ...]] = (
    "제외하고",
    "빼고",
    "빼줘",
    "빼",
    "말고",
)
_CONTRAST_SEPARATORS: Final[tuple[str, ...]] = (
    "하지만",
    "그렇지만",
    "그러나",
    "근데",
    "는데",
    "은데",
    "지만",
)
_NEGATIVE_MARKERS: Final[tuple[str, ...]] = (
    "싫",
    "피하",
    "원하지",
    "별로",
    "제외",
    "빼",
    "말고",
    "안 가",
)


@dataclass(frozen=True, slots=True)
class IntentPreferenceResult:
    cleaned_raw_query: str
    preferred_theme_ids: tuple[str, ...] = ()
    disliked_theme_ids: tuple[str, ...] = ()
    preferred_region_ids: tuple[str, ...] = ()
    disliked_region_ids: tuple[str, ...] = ()
    contradiction_reasons: tuple[str, ...] = ()

    @property
    def active_theme_labels(self) -> tuple[str, ...]:
        return tuple(THEME_ID_TO_LABEL[theme_id] for theme_id in self.preferred_theme_ids)

    @property
    def preferred_region_names(self) -> tuple[str, ...]:
        return region_names(self.preferred_region_ids)

    @property
    def disliked_region_names(self) -> tuple[str, ...]:
        return region_names(self.disliked_region_ids)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.contradiction_reasons)

    @property
    def clarifying_question(self) -> str | None:
        if not self.needs_clarification:
            return None
        return "선호와 비선호가 동시에 언급된 테마나 지역이 있어 우선순위를 확인해야 합니다."


@dataclass(frozen=True, slots=True)
class _PolarizedSegment:
    text: str
    polarity: PreferencePolarity


def parse_initial_query(raw_query: str) -> IntentPreferenceResult:
    cleaned_raw_query = " ".join(raw_query.split())
    preferred_theme_ids, disliked_theme_ids = _extract_preferences(
        cleaned_raw_query,
        _THEME_KEYWORDS,
    )
    preferred_region_ids, disliked_region_ids = _extract_preferences(
        cleaned_raw_query,
        _REGION_KEYWORDS,
    )
    validation = validate_preference_sets(
        preferred_theme_ids=preferred_theme_ids,
        disliked_theme_ids=disliked_theme_ids,
        preferred_region_ids=preferred_region_ids,
        disliked_region_ids=disliked_region_ids,
    )
    return IntentPreferenceResult(
        cleaned_raw_query=cleaned_raw_query,
        preferred_theme_ids=preferred_theme_ids,
        disliked_theme_ids=disliked_theme_ids,
        preferred_region_ids=preferred_region_ids,
        disliked_region_ids=disliked_region_ids,
        contradiction_reasons=validation.contradiction_reasons,
    )


def theme_labels(theme_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(THEME_ID_TO_LABEL[theme_id] for theme_id in theme_ids)


def region_names(region_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(REGION_ID_TO_LABEL[region_id] for region_id in region_ids)


def _extract_preferences(
    text: str,
    keyword_map: dict[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    preferred_ids: list[str] = []
    disliked_ids: list[str] = []
    for segment in _polarized_segments(text):
        matched_ids = _matching_ids(segment.text, keyword_map)
        match segment.polarity:
            case "preferred":
                preferred_ids.extend(matched_ids)
            case "disliked":
                disliked_ids.extend(matched_ids)
            case unreachable:
                assert_never(unreachable)
    return _dedupe(preferred_ids), _dedupe(disliked_ids)


def _polarized_segments(text: str) -> tuple[_PolarizedSegment, ...]:
    for separator in _CONTRAST_SEPARATORS:
        if separator in text:
            segments: list[_PolarizedSegment] = []
            for part in text.split(separator):
                segments.extend(_polarized_segments(part))
            return tuple(segments)

    for separator in _NEGATIVE_SEPARATORS:
        if separator in text:
            left, right = text.split(separator, 1)
            segments = []
            if left.strip():
                segments.append(_PolarizedSegment(text=left, polarity="disliked"))
            if right.strip():
                segments.append(_PolarizedSegment(text=right, polarity="preferred"))
            return tuple(segments)

    polarity: PreferencePolarity = "disliked" if _has_negative_marker(text) else "preferred"
    return (_PolarizedSegment(text=text, polarity=polarity),)


def _has_negative_marker(text: str) -> bool:
    return any(marker in text for marker in _NEGATIVE_MARKERS)


def _matching_ids(
    text: str,
    keyword_map: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    return tuple(
        item_id
        for item_id, keywords in keyword_map.items()
        if any(keyword in text for keyword in keywords)
    )


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)
