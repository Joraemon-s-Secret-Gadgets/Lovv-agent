# V2 Weather Alternative Itinerary Implementation Tasks

Status: implementation directive - remaining work after first weather-risk slice
Date: 2026-07-05

This document tracks the remaining implementation scope for weather-aware alternative itineraries.
The source directive is `docs/reports/v2/V2_32_ALTERNATIVE_ITINERARY_WEATHER_DIRECTIVE.md`.

## 1. Current Baseline

Implemented in the first slice:
- Planner has a `weather_alternative` post-assembly step.
- Weather risk is loaded from `city_monthly_weather_risks.json` by `(city_id, travel_month)`.
- Threshold logic is isolated in a policy module so ratios and notice rules can be changed later.
- Itinerary items preserve `indoor_outdoor` internally and expose additive `indoorOutdoor` in public item payloads.
- Missing weather-map coverage is non-fatal:
  - `weather_audit.status = unavailable`
  - `weather_audit.unavailable_reason = city_weather_map_missing`
- Response packager can expose `alternativeItinerary` when planner later provides one.

Not implemented yet:
- Real alternative itinerary item generation.
- Weather-specific clarification prompt and resume action handling.
- Weather-aware live smoke matrix.

## 2. Design Constraints

The primary itinerary must not be silently mutated.

Weather handling is a backup surface:
- same city only;
- same trip type and day count;
- preserve seed/festival items unless explicitly unsafe and intentionally replaceable;
- replace only weather-sensitive non-seed slots;
- do not use alternative-city fallback for weather.

Weather map gaps must not block generation.
If the city is outside the weather map, record audit only and return the normal itinerary.

## 3. Remaining Implementation Tasks

### 3.1 Reserve-based alternative generation

Use existing planner candidate reserves before doing any new retrieval.

Candidate source priority:
1. `planner.validation_result.itinerary_structure.reserve`
2. `state.planner.modify_context.reserve_pool`
3. selected-but-unused same-city planner pool if made available later

Replacement policy:
- target only outdoor/mixed non-seed items;
- prefer `indoor`;
- allow `mixed` only when there are not enough indoor candidates;
- keep the original day/order shape;
- require same city id;
- exclude current itinerary content ids.

Output:
- `state.planner.alternative_itinerary`
- `planner_output.alternative_itinerary`
- `validation_result.weather_audit.alternative_generation`

Failure mode:
- if reliable reserve candidates are insufficient, keep only the weather notice;
- do not fabricate indoor replacements.
- if no feasible backup is produced, do not ask the user whether to view a weather alternative.

### 3.2 Affected-day route feasibility

Alternative replacements must pass route feasibility for the affected day.

Use the same route constraints already used by slot replace:
- hard leg threshold;
- walk-specific stricter leg threshold;
- affected day only.

If a replacement fails feasibility:
- try the next reserve candidate;
- if none pass, record `alternative_generation = route_infeasible`;
- keep primary itinerary unchanged.

### 3.3 Optional retrieval fallback

Only add this after reserve-based quality is measured.

Fallback retrieval should:
- search within the same city;
- reuse active themes and weather-resilient subtype hints;
- prefer indoor subtypes from `attraction_subtypes.json`;
- avoid raw weather reason codes in user-facing text.

This should be a separate step from the first reserve-based implementation so the added S3 Vector cost is measurable.

### 3.4 Weather clarification and resume

Weather alternatives are precomputed before asking the user.
The user chooses whether to view/apply that already-computed backup.

Target UX:

```text
평년 기준 날씨 리스크가 높은 달이라 야외 일정 비중이 큽니다.
날씨 대체 일정을 보시겠습니까?
```

If the user answers yes:
- do not regenerate;
- read the checkpointed `planner_output.alternative_itinerary`;
- show that alternative itinerary as the new visible itinerary.

If the user answers no:
- keep the primary itinerary unchanged.

Clarification shape:
- `reason_code = weather_alternative_available`
- `then = weather_alternative`
- `options[]`:
  - `use_weather_alternative`
  - `keep_primary_itinerary`

Checkpoint requirements:
- preserve `planner_output.itinerary`;
- preserve `planner_output.alternative_itinerary`;
- preserve `validation_result.weather_audit`;
- preserve enough response context to repackage without re-running retrieval.

Implementation split:
- This weather task should implement precomputed `alternativeItinerary` and the clarification payload.
- Application-level resume meaning handling may remain deferred until the global clarification loop is finished.

Current expected behavior:
- when `alternativeItinerary` exists, response may ask whether the user wants to view it;
- user selection is not automatically applied through resume until the global resume handler consumes `weather_alternative`.

### 3.5 Policy configurability

Keep all tunable ratios in the weather policy module.

Currently fixed defaults:
- medium notice ratio: `0.40`
- high notice ratio: `0.25`
- high alternative ratio: `0.50`

Future extension:
- move ratios to config/env only if smoke data shows runtime tuning is needed;
- otherwise keep code-level policy constants for reviewability.

### 3.6 Smoke and analysis

Add a small smoke set before expanding.

Required cases:
- high-risk city-month with outdoor-heavy itinerary;
- high-risk city-month with mostly indoor itinerary;
- medium-risk city-month around threshold boundary;
- low-risk city-month;
- city missing from weather map;
- festival seed included.

Metrics to record:
- weather map coverage rate;
- known exposure ratio;
- weather-sensitive ratio;
- notice level;
- alternative generation status;
- route feasibility failures.

## 4. Acceptance Criteria

The remaining implementation is complete when:
- primary itinerary remains unchanged in all weather cases;
- weather audit is present for every planner output;
- map-missing cities return normal itineraries without user-visible weather notice;
- high-risk outdoor-heavy cases either return a feasible `alternativeItinerary` or an explicit no-candidate audit;
- weather alternative prompt is shown only when a feasible `alternativeItinerary` exists;
- yes/no weather alternative options are checkpoint-safe and do not trigger regeneration by themselves;
- response payload shape remains backward compatible;
- targeted unit tests and at least one live smoke batch pass.
