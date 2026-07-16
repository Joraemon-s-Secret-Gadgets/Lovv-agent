from __future__ import annotations

from lovv_agent_v2.agents.planner.steps.apply_edit.node import apply_edit_node


def test_day_regenerate_preserves_latest_current_order_over_stale_checkpoint() -> None:
    result = apply_edit_node(
        {
            "request": {
                "request_id": "REQ-EDIT-CURRENT-ORDER",
                "destinationId": "KR-47-130",
                "currentOrder": [
                    _current_item(1, 1),
                    _current_item(1, 2),
                    _current_item(2, 1),
                    _current_item(2, 2),
                ],
            },
            "intent": {
                "modify_intent": {
                    "status": "ok",
                    "kind": "day_regenerate",
                    "routing_hint": "planner_apply_edit",
                    "day_regenerate": {
                        "day": 1,
                        "condition": {
                            "replacement_query": None,
                            "theme": None,
                            "avoid_content_ids": [],
                        },
                    },
                },
            },
            "planner": {
                "planner_output": {
                    "itinerary": [
                        _stale_planner_item(1, 1),
                        _stale_planner_item(1, 2),
                        _stale_planner_item(2, 1),
                        _stale_planner_item(2, 2),
                    ],
                    "validation_result": {"planner_status_gate": "ok"},
                },
                "modify_context": {
                    "reserve_pool": [
                        _candidate("attraction#new-1", "새 첫 장소"),
                        _candidate("attraction#new-2", "새 둘째 장소"),
                    ],
                },
            },
        },
    )

    itinerary = result["planner"]["planner_output"]["itinerary"]
    untouched_day = [item for item in itinerary if item["day"] == 2]
    assert [item["placeId"] for item in untouched_day] == [
        "attraction#latest-day2-1",
        "attraction#latest-day2-2",
    ]


def _current_item(day: int, order: int):
    return {
        "itemId": f"item-{day}-{order}",
        "contentId": f"attraction#latest-day{day}-{order}",
        "itemType": "attraction",
        "day": day,
        "order": order,
        "title": f"최신 {day}일차 {order}번째 장소",
        "isSeed": False,
        "cityId": "KR-47-130",
        "theme": "역사·전통",
        "latitude": 35.82 + (day / 100),
        "longitude": 129.21 + (order / 100),
    }


def _stale_planner_item(day: int, order: int):
    return {
        "day": day,
        "order": order,
        "placeId": f"attraction#stale-day{day}-{order}",
        "title": f"이전 {day}일차 {order}번째 장소",
        "latitude": 35.82 + (day / 100),
        "longitude": 129.21 + (order / 100),
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
        "isSeed": False,
    }


def _candidate(place_id: str, title: str):
    return {
        "place_id": place_id,
        "title": title,
        "latitude": 35.829,
        "longitude": 129.214,
        "city_id": "KR-47-130",
        "theme_tags": ("역사·전통",),
        "score_audit": {"score_components": {"raw_similarity": 0.82}},
    }
