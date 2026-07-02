# Profile Tool Verification Report

## 검증 대상

- Source tool boundary: `src/lovv_agent_v2/agents/profile/evidence.py`
- Packaged copy boundary: `app/LovvAgentV2/lovv_agent_v2/agents/profile/evidence.py`
- 핵심 객체:
  - `SavedItinerarySignalsTool`
  - `ProfileEvidenceResolver`
  - `InMemoryProfileEvidenceCache`
  - `build_profile_evidence_record`
  - `profile_node`

## 결론

로컬 코드 기준으로 profile에서 만든 saved-itinerary evidence tool 경로는 정상 동작한다.

- fake `SavedItinerarySignalsTool` 응답을 `ProfileEvidenceResolver`가 읽었다.
- 첫 호출은 cache miss 후 tool success로 `profile_record`를 만들고 cache에 저장했다.
- 같은 actor/thread의 두 번째 resolve는 cache hit로 tool을 다시 호출하지 않았다.
- `profile_node`가 주입된 `profile_record.lovv_user_profile`을 읽어 `theme_weights`를 `city_select_input`에 적용했다.
- `app/LovvAgentV2` packaged copy에서도 같은 `build_profile_evidence_record` 경로가 import되고 profile record를 생성했다.

단, 현재 repo에는 별도 외부 API 구현체 클래스가 아니라 `SavedItinerarySignalsTool` Protocol이 있고, 이번 검증은 fake implementation을 꽂은 protocol/adapter 경로 검증이다. 실제 외부 저장 일정 API 또는 live AgentCore runtime 성공까지는 이번 실행 범위에 포함하지 않았다.

## 실행 결과

```text
UV_CACHE_DIR=.cache/uv PYTHONUTF8=1 uv run pytest tests/v2/test_profile_evidence.py tests/v2/test_profile_agent.py tests/v2/test_mock_profile_injector.py tests/v2/test_profile_rescore_compare.py -q -p no:cacheprovider --basetemp .cache/pytest-profile-suite
16 passed in 0.11s
```

```text
UV_CACHE_DIR=.cache/uv PYTHONUTF8=1 uv run pytest tests/v2/test_profile_evidence.py -q -p no:cacheprovider --basetemp .cache/pytest-profile-evidence
7 passed in 0.05s
```

```text
PYTHONPATH=app/LovvAgentV2 PYTHONUTF8=1 uv run python <app copy smoke>
has_record=true
module_file=app/LovvAgentV2/lovv_agent_v2/agents/profile/evidence.py
```

## 수동 시나리오 관찰

Evidence file: `manual_profile_evidence_scenario.json`

- `tool_call_count`: `1`
- first audit:
  - `cache_status`: `miss`
  - `tool_status`: `success`
  - `cache_write_status`: `stored`
- second audit:
  - `cache_status`: `hit`
- generated `profile_record`:
  - `profile_id`: `saved-itinerary://actor-1`
  - `saved_trip_count`: `3`
  - `saved_theme_counts.sea_coast`: `4`
  - `saved_theme_counts.nature_trekking`: `1`
  - `saved_theme_counts.history_tradition`: `1`
- `profile_node` output:
  - `theme_weights.바다·해안`: `1.3`
  - `theme_weights.자연·트레킹`: `0.95`
  - `theme_weights.역사·전통`: `0.95`
  - 기존 profile payload field `existing=preserved` 유지

## 저장된 증거 파일

- `local_profile_pytest_output.txt`
- `profile_evidence_pytest_output.txt`
- `manual_profile_evidence_scenario.json`
- `app_copy_profile_smoke.json`
- `summary.md`

## 제약 사항

- 이번 검증은 local protocol/fake tool path와 packaged copy import smoke 범위다.
- 이전 live AgentCore 결과서는 runtime 500 원인을 `langgraph_checkpoint_aws` packaging 문제로 기록하고 있으므로, live runtime까지 확인하려면 `app/LovvAgentV2` 재배포 후 같은 payload로 invoke 재검증이 필요하다.
