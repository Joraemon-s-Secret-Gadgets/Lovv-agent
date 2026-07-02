# V2_34 — Modify Intent Schema

> Purpose: contract for the teammate implementing the real Intent Agent modify path.
> Source priority: `V2_31_SESSION_HANDOFF.md` overrides older `V2_11` seed-reject wording. Front request shape remains `V2_30_MODIFY_REQUEST_SCHEMA.md`.

---

## 0. Scope

This document defines the **Intent Agent output** for itinerary modification.

It does not redefine the front request. The front still sends:

- `entryType: "modify"`
- `threadId`
- `itineraryRevision`
- `rawModifyQuery`
- full `currentOrder`

The front does **not** send `edit_ops`.

Intent parses `rawModifyQuery`, resolves target items against the current itinerary context, and emits a typed `modify_intent` for Supervisor/Planner.

---

## 1. Top-Level Shape

```json
{
  "intent_type": "modification",
  "status": "ok",
  "thread_id": "thread-id",
  "itinerary_revision": "rev-001",
  "raw_modify_query": "1일차 오후 장소를 조용한 자연 쪽으로 바꿔줘",
  "kind": "slot_replace",
  "edit_ops": [],
  "reset": null,
  "clarification": null,
  "unsupported_reasons": [],
  "routing_hint": "planner_apply_edit",
  "audit": {}
}
```

### Fields

| field | type | required | meaning |
|---|---:|---:|---|
| `intent_type` | `"modification"` | yes | Discriminator. |
| `status` | `"ok" \| "needs_clarification" \| "unsupported"` | yes | Whether backend may execute. |
| `thread_id` | string | yes | Checkpoint resume key copied from request. |
| `itinerary_revision` | string | yes | Stale-detection token copied from request. |
| `raw_modify_query` | string | yes | Original modify utterance, non-empty. |
| `kind` | `slot_replace \| reset \| confirm_plan_b \| backlog` | yes | Intent class. |
| `edit_ops` | `EditOperation[]` | yes | Non-empty only for `slot_replace`. |
| `reset` | `ResetIntent \| null` | yes | Non-null only for `reset`. |
| `clarification` | `Clarification \| null` | yes | Non-null when `status=needs_clarification`. |
| `unsupported_reasons` | string[] | yes | Non-empty when `status=unsupported`. |
| `routing_hint` | string | yes | Supervisor hint, not final authority. |
| `audit` | object | yes | Parser trace for tests/debugging. |

---

## 2. Status And Routing

| status | kind | routing_hint | downstream |
|---|---|---|---|
| `ok` | `slot_replace` | `planner_apply_edit` | Planner edit mode. Skip profile/city_select/festival. |
| `ok` | `reset` | `city_select_rediscovery` | Re-run city discovery with session avoid. |
| `ok` | `confirm_plan_b` | `planner_apply_weather_alternative` | Future/on-demand weather Plan B path. |
| `needs_clarification` | any | `response_packager_wait_user` | Ask user; do not execute edit. |
| `unsupported` | `backlog` | `response_packager_notice` | Explain unsupported modify scope. |

`routing_hint` is intentionally a hint. Supervisor still decides the next node from state.

---

## 3. EditOperation

```json
{
  "op_id": "op-1",
  "op": "REPLACE",
  "target": {
    "item_id": "item-2",
    "content_id": "attraction#127691",
    "item_type": "attraction",
    "day": 1,
    "order": 2,
    "target_text": "이이 유적",
    "resolution": "exact"
  },
  "condition": {
    "replacement_query": "조용히 산책하기 좋은 자연",
    "theme": "자연·트레킹",
    "mood": "quiet",
    "place_type": "walk",
    "location": null,
    "avoid_content_ids": ["attraction#127691"]
  },
  "seed_policy": {
    "target_is_seed": false,
    "policy": "not_seed"
  }
}
```

### EditOperation Rules

1. `op` is always `"REPLACE"` in V2.0.
2. `target.item_id` is preferred. `content_id` is included for audit and fallback.
3. `target.resolution` is one of:
   - `exact`: one item resolved
   - `ambiguous`: multiple possible items
   - `unresolved`: no item resolved
4. `condition.replacement_query` is the slot-local query used for re-retrieval.
5. `condition` must describe only the replacement slot, not a full itinerary rewrite.
6. `avoid_content_ids` should include the replaced item so Planner does not immediately pick the same place unless no alternative exists and policy allows fallback.

---

## 4. Seed Policy

Latest V2 policy is **not** "seed always rejected".

| target | Intent behavior | Planner behavior |
|---|---|---|
| non-seed item | emit `policy=not_seed` | replace normally |
| seed item, same-theme request | emit `policy=same_theme_required` | may replace only with same theme |
| seed item, different-theme/city-changing request | `needs_clarification` or `unsupported` | do not execute |

Seed policy shape:

```json
{
  "target_is_seed": true,
  "policy": "same_theme_required",
  "required_theme": "역사·전통"
}
```

Intent may set `required_theme` only when it can read the original item theme from checkpoint-enriched context. If not available, omit it and Planner must derive it from checkpoint.

---

## 5. ResetIntent

`reset` is for broad dissatisfaction such as "다 별로야", "다른 느낌으로 다시 짜줘", or "이 도시는 빼고 다시".

```json
{
  "avoid": {
    "city_ids": ["KR-47-130"],
    "theme_ids": [],
    "content_ids": []
  },
  "reason": "user_rejected_current_itinerary"
}
```

Reset rules:

1. Reset does not create `edit_ops`.
2. Reset writes session avoid only. It does not update long-term profile.
3. Reset routes to city rediscovery.
4. Targeted city change like "속초로 바꿔" remains V2.1/backlog unless the current approved product decision changes.

---

## 6. Clarification Cases

Intent must return `status=needs_clarification` when execution would be unsafe.

Required cases:

- target item cannot be resolved
- multiple items match the same target phrase
- same slot receives contradictory conditions
- multiple ops conflict with each other
- user asks to change a seed in a way that is not same-theme

Clarification shape:

```json
{
  "reason_code": "modify_target_ambiguous",
  "prompt": "어떤 장소를 바꿀까요?",
  "options": [
    {
      "option_id": "target:item-2",
      "label": "1일차 2번째 장소",
      "apply": {"target_item_id": "item-2"}
    }
  ]
}
```

---

## 7. Unsupported Backlog Cases

Return `status=unsupported`, `kind=backlog` for recognized but non-V2.0 requests.

Backlog reasons:

- `add_place`
- `remove_place`
- `reorder_only`
- `targeted_city_change`
- `trip_length_change`
- `travel_month_change`
- `transport_mode_replan`
- `whole_itinerary_mood_rebuild`
- `reservation_or_booking`

Important distinction:

- Front drag-and-drop order changes are already represented by `currentOrder`; backend should accept that order as current truth.
- Natural-language reorder-only requests are not V2.0 edit ops.

---

## 8. Examples

### 8.1 Non-Seed Slot Replace

User:

```text
1일차 오후 이이 유적 말고, 조용히 산책하기 좋은 자연 쪽으로 바꿔줘.
```

Output:

```json
{
  "intent_type": "modification",
  "status": "ok",
  "kind": "slot_replace",
  "routing_hint": "planner_apply_edit",
  "edit_ops": [
    {
      "op_id": "op-1",
      "op": "REPLACE",
      "target": {
        "item_id": "item-2",
        "content_id": "attraction#127691",
        "item_type": "attraction",
        "day": 1,
        "order": 2,
        "target_text": "이이 유적",
        "resolution": "exact"
      },
      "condition": {
        "replacement_query": "조용히 산책하기 좋은 자연",
        "theme": "자연·트레킹",
        "mood": "quiet",
        "place_type": "walk",
        "location": null,
        "avoid_content_ids": ["attraction#127691"]
      },
      "seed_policy": {
        "target_is_seed": false,
        "policy": "not_seed"
      }
    }
  ],
  "reset": null,
  "clarification": null,
  "unsupported_reasons": [],
  "audit": {}
}
```

### 8.2 Seed Same-Theme Replace

User:

```text
대표 역사 장소는 유지하되, 비슷한 역사 장소로 바꿔줘.
```

Output policy:

```json
{
  "seed_policy": {
    "target_is_seed": true,
    "policy": "same_theme_required",
    "required_theme": "역사·전통"
  }
}
```

### 8.3 Backlog

User:

```text
2박 3일 말고 3박 4일로 늘려줘.
```

Output:

```json
{
  "intent_type": "modification",
  "status": "unsupported",
  "kind": "backlog",
  "edit_ops": [],
  "unsupported_reasons": ["trip_length_change"],
  "routing_hint": "response_packager_notice"
}
```

---

## 9. Implementation Checklist

- Parse front request into this schema only after checkpoint/current itinerary context is available.
- Resolve targets to `item_id`; do not let Planner guess vague text.
- Preserve `thread_id`, `itinerary_revision`, and `raw_modify_query`.
- Emit `slot_replace` with one or more `REPLACE` ops.
- Mark seed targets with `same_theme_required` instead of rejecting by default.
- Return clarification for ambiguous or contradictory executable edits.
- Return unsupported/backlog for add/remove/reorder-only/date/length/city-target replan.
- Never write long-term profile from modify utterances.
