# V2 포팅 핸드오프 (V1 → lovv_agent_v2)

> 작성일 2026-06-28 · 대상: Claude Code(repo 실행·pytest). 근거: `V2_12_DIRECTORY_STRUCTURE.md` §3.3.
> 목적: 검증된 V1 모듈을 `src/lovv_agent_v2/`로 **복사→import 재작성**해 baseline green을 만든다. C1/C2/C3 V2 델타는 그 위에 별도로 얹는다.
> 주의: 이 문서는 포팅 baseline 설명이다. V2 최종 state/API 정본은 `V2_23_STATE_CONTRACT_DIRECTIVE.md`이며, `CandidateEvidence*` 이름은 legacy 제거 대상이다.

## 0. 대원칙
1. **포팅 = 로직 변경 없음.** V1 동작 그대로 옮겨 import 되고 pytest green까지. **V2 델타(C1 capacity 제거·C2 soft 게이트·C3 seed·congestion_pref 직접사용)는 포팅에 섞지 않는다** — 포팅 후 슬라이스별로 각각 + 테스트.
2. **bottom-up.** infra → models → city_select 순(상위가 하위를 import).
3. **V2 clean drop은 포팅 시 생략**(아래 §5): reason_claims/quota 등 V2에서 폐기 확정된 LLM 부속은 옮기지 않는다.
4. **import 그래프 준수**(V2_12 §3.1): agents → {common, infra, core.state, models}만. agent→agent 금지. scoring↔retrieval은 **같은 city_select 슬라이스 내부**라 허용(intra-slice).

## 1. 포팅 순서
```
1) infra/        config · aws_clients · adapters(bedrock_converse·embeddings) · repositories(s3_vectors·dynamodb)  [+ dynamo_lookup 배치 결정]
2) models/schemas.py   ← V1 baseline import 후 V2 정본으로 정리 (SchemaValidationError·GeoPoint·CitySelectInput·EXECUTION_MODES·DTO, `CandidateEvidence*`는 legacy 제거 대상)
3) agents/city_select/  scoring · retrieval_node · selection · scoring_and_selection_node  (candidate_evidence 분해)
4) (이후) festival_verifier · planner · intent · supervisor · packager · profile
```

## 2. 파일 매핑
| V1 source | → V2 target | 방식 |
|---|---|---|
| `src/lovv_agent/config.py` | `infra/config.py` | 복사 + import 재작성 |
| `src/lovv_agent/adapters/aws_clients.py`·`boto3_clients.py`·`aws_runtime.py` | `infra/aws_clients.py`(+필요시 분리) | 복사. v2 경로로 wiring |
| `src/lovv_agent/adapters/bedrock_converse.py` | `infra/adapters/bedrock_converse.py` | 복사 |
| `src/lovv_agent/adapters/embeddings.py` | `infra/adapters/embeddings.py` | 복사(자족적, import 거의 없음) |
| `src/lovv_agent/repositories/s3_vectors.py` | `infra/repositories/s3_vectors.py` | 복사 |
| `src/lovv_agent/repositories/dynamodb.py` | `infra/repositories/dynamodb.py` | 복사 |
| `src/lovv_agent/tools/dynamo_lookup.py` | **`infra/dynamo_lookup.py`** ⚠ | 복사. city_select(visitor stats)+festival(seed) 공용이라 agent 밖(infra) 배치 — **Claude Code 확정** |
| `src/lovv_agent/models/schemas.py` | `models/schemas.py` | **V1 그대로 baseline** (V2 ±2필드는 나중) |
| `src/lovv_agent/tools/scoring.py` | `agents/city_select/scoring.py` | 복사 + import 재작성 |
| `src/lovv_agent/tools/destination_search.py` | `agents/city_select/retrieval_node.py`(검색 tool·prune·constants) | 복사. node wrapper는 같은 파일/별 함수 |
| `src/lovv_agent/tools/candidate_selection.py` | `agents/city_select/selection.py` | 복사 |
| `src/lovv_agent/agents/candidate_evidence.py` | **분해** → `retrieval_node.py` + `scoring_and_selection_node.py` | §4 (단순 복사 아님) |
| `src/lovv_agent/telemetry*.py` | `common/telemetry*.py` | 복사 |

## 3. import 재작성 규칙 (prefix 치환)
| V1 prefix | V2 prefix |
|---|---|
| `lovv_agent.models.schemas` | `lovv_agent_v2.models.schemas` |
| `lovv_agent.config` | `lovv_agent_v2.infra.config` |
| `lovv_agent.repositories.*` | `lovv_agent_v2.infra.repositories.*` |
| `lovv_agent.adapters.bedrock_converse`·`embeddings` | `lovv_agent_v2.infra.adapters.*` |
| `lovv_agent.adapters.{aws_clients,boto3_clients,aws_runtime}` | `lovv_agent_v2.infra.*` |
| `lovv_agent.tools.dynamo_lookup` | `lovv_agent_v2.infra.dynamo_lookup` |
| `lovv_agent.tools.scoring` | `lovv_agent_v2.agents.city_select.scoring` |
| `lovv_agent.tools.destination_search` | `lovv_agent_v2.agents.city_select.retrieval_node` |
| `lovv_agent.tools.candidate_selection` | `lovv_agent_v2.agents.city_select.selection` |
| `lovv_agent.telemetry*` | `lovv_agent_v2.common.telemetry*` |

> 구체 의존 예: `scoring.py`는 `SchemaValidationError`(→models.schemas)와 `ATTRACTION_ENTITY_TYPE·FESTIVAL_EXCLUDED_THEME_LABELS·GOURMET_EXTERNAL_THEME_LABELS`(→retrieval_node)를 import. `destination_search`는 `SearchBudgetSettings`(→infra.config)·`S3VectorRepository,extract_vector_records`(→infra.repositories.s3_vectors) import.

## 4. candidate_evidence.py 분해 (복사 아님)
한 파일을 2-node로 나눈다. **scoring 공식·게이트는 V1 그대로**(델타는 나중).

**→ `retrieval_node.py`** (검색·prune): `_retrieve_by_theme`, `_merge_duplicate_candidates`, `prune_cities` 호출, `_allowed_city_ids`, retrieval audit. 입력 = query_vector/soft_query_vector + themes + allowed_city_ids.

**→ `scoring_and_selection_node.py`** (스코어·선택·seed): `_score_groups`, `_rank_cities`(congestion 포함), `_select_city_rank_index`, `selection.select_primary_with_theme_quotas`, `_selected_city`, package 구성. 입력 = pruned groups.

**생략(§5)**: `_attach_candidate_reason_claims`·`build_candidate_reason_claim_request`·`_template_reason_claims`·`CANDIDATE_REASON_CLAIM_*` 전부. (V2 reason_claims 폐기)

## 5. 포팅 시 생략 (V2 clean drop)
- **reason_claims / candidate_reason_claim** 일체 — V2 폐기 확정. 옮기지 않는다.
- 그 외 V1 동작은 유지(candidate_sufficiency·AND 게이트·theme_match binary는 **baseline으로 유지** → C1/C2가 나중에 제거/교체하는 대상).

## 6. 검증 (Claude Code)
1. **import 스모크**: `python -c "import lovv_agent_v2.agents.city_select.scoring_and_selection_node"` 등 각 포팅 모듈 import 성공.
2. **단위 테스트 이식**: V1 `tests/test_scoring.py`·`test_destination_search.py`·`test_candidate_selection.py`를 `tests/v2/`로 포팅(import 경로 치환) → green. (reason_claim 관련 케이스는 제외)
3. **parity 불필요**: V1과 동일 동작 보장 목적 아님(reason_claims 등 의도적 차이). v2 테스트 green이 기준.

## 7. 포팅 후 (별도 작업, 각각 + 테스트)
C1 capacity 제거(`scoring.py`) → C2 soft 게이트(`retrieval_node.prune` + scoring) → C3 seed(`scoring_and_selection_node`) → congestion_pref 직접사용 · transport_pref. smoke(`scripts/v2/retrieval_smoke.py`) 결과로 C2/C3 파라미터 확정.

## 8. Claude Code 확정 필요(2)
- `dynamo_lookup` 배치: `infra/` 권장(공용) vs 다른 곳.
- `destination_search`의 node wrapper를 `retrieval_node.py` 한 파일에 둘지, `retrieval.py`(tool) + `retrieval_node.py`(node)로 더 쪼갤지.
