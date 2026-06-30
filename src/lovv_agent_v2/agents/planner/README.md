# Planner Agent

Planner turns a selected city into an in-city itinerary.

Read in this order:

1. `node.py` - parent graph entrypoint.
2. `subgraph.py` - local planner graph shape.
3. `state_adapter.py` - `UnifiedAgentState` to planner request/result boundary.
4. `agent.py` - deterministic planner core.
5. `steps/` - implementation details for each subgraph step.

## Shape

`node.py`
exposes the single parent-graph entrypoint: `planner_node`.

`subgraph.py`
wires the local step graph:

1. `retrieve_places`
2. `route_days`
3. `assemble_itinerary`
4. optional `retry_alternative_city`

`state_adapter.py`
is the only planner module that should understand planner scratch and graph
state adaptation.

`agent.py`
owns the core planner orchestration. It receives `PlannerAgentRequest` and
`PlannerAgentTools`, then retrieves places, selects a working set, and routes
the itinerary.

## Step Packages

`steps/retrieve_places/`
contains festival seed conversion used during place retrieval.

`steps/route_days/`
contains selection, theme quota, subtype diversity, slot preference, travel
metrics, and day routing policies.

`steps/assemble_itinerary/`
builds `planner_output`, validation, audit, notices, and fallback metadata.

`steps/retry_alternative_city/`
detects thin primary-city itineraries and swaps state to the alternative city
when city-select supplied one.

## Shared Modules

`context.py`
extracts planner input from state.

`scratch.py`
owns planner scratch read/write helpers.

`tools.py`
adapts external runtime capabilities such as vector search, embeddings, and
travel-time providers.

`place_model.py`
normalizes candidate place records for selection and routing.

`travel_time.py`, `ors_provider.py`
define travel-time provider contracts and ORS integration.

`in_city_itinerary.py`
is a compatibility helper. Prefer `agent.py` plus `state_adapter.py` for planner
work.

## Rule Of Thumb

Change graph wiring in `subgraph.py`.
Change state shape in `state_adapter.py` or `context.py`.
Change planning behavior in `agent.py` or the matching `steps/` package.
Change external capability wiring in `tools.py`.
