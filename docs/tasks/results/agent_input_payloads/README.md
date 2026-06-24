# Agent Input Payload Fixtures

These JSON files are direct LovvAgentV1 invocation payload fixtures.

- `01` through `05` are raw `/recommendations` request payloads.
- `06` and `07` are AgentCore/HTTP wrapper payloads accepted by `extract_recommendation_payload()`.
- `99` is a negative schema fixture for validation checks.

Current public request fields:

- `entryType`: `map_marker`, `chat`, or `home_recommendation`
- `country`: `KR` or `JP`
- `travelYear`: positive integer
- `travelMonth`: `1` through `12`
- `tripType`: `daytrip`, `2d1n`, `3d2n`, `4d3n`, or `5d4n`
- `themes`: one to three canonical theme ids
- `includeFestivals`: boolean
- `destinationId`: required only for `map_marker`
- `naturalLanguageQuery`: optional free text
- `userLocation`: optional object with `latitude` and `longitude`
