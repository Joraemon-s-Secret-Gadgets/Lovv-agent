#!/usr/bin/env python3
"""retrieval 검증용 입력 케이스 보강 — 현재 갭(미커버 페어·얇은 단일·3테마 부족·엣지)을 채운다.

목적: retrieval 특성 분석의 표본을 늘림(intent mock 충실도와 별개). 평면 포맷
{id, source, raw_query, soft_query, themes} 로 v2_retrieval_inputs/에 기록.
기존 37케이스는 건드리지 않음(id 100번대로 추가). 이후 retrieval_smoke를 전체 디렉터리에 재실행.

5 테마 라벨: 바다·해안 / 자연·트레킹 / 역사·전통 / 예술·감성 / 온천·휴양
"""
from __future__ import annotations
import json, os

OUT = "docs/tasks/results/v2_retrieval_inputs"
SRC = "v2gen_retrieval"

CASES = [
    # --- 미커버 페어 4 ---
    ("100_pair_coast_history", "바다도 보고 오래된 유적이나 한옥마을도 함께 둘러보는 2박3일 여행 추천해줘.",
     "사람 적고 조용한 해안 마을이면 좋겠어", ["바다·해안", "역사·전통"]),
    ("101_pair_coast_art", "해변 근처에서 미술관이나 감성적인 전시 공간을 즐기는 1박2일.",
     "사진 찍기 좋은 분위기 위주로", ["바다·해안", "예술·감성"]),
    ("102_pair_nature_art", "산이나 숲길을 걷고 근처 갤러리·예술 공간도 보는 여행.",
     "한적하고 여유로운 곳", ["자연·트레킹", "예술·감성"]),
    ("103_pair_history_healing", "역사 유적을 둘러보고 온천에서 푹 쉬는 2박3일 코스.",
     "느긋하게 휴식 위주로", ["역사·전통", "온천·휴양"]),
    # --- 얇은 단일 보강: 예술·감성 +3 ---
    ("104_single_art_solo", "감성적인 미술관과 전시를 천천히 보는 당일치기.",
     "혼자 조용히 둘러보고 싶어", ["예술·감성"]),
    ("105_single_art_mural", "벽화마을과 예쁜 카페에서 사진 찍으며 도는 여행.",
     "활기차고 볼거리 많은 동네", ["예술·감성"]),
    ("106_single_art_indoor", "갤러리와 예술 거리를 걷는 1박2일.",
     "비 와도 즐길 실내 위주", ["예술·감성"]),
    # --- 얇은 단일 보강: 온천·휴양 +3 ---
    ("107_single_healing_quiet", "온천에서 푹 쉬고 힐링하는 1박2일.",
     "조용하고 한적한 곳", ["온천·휴양"]),
    ("108_single_healing_family", "가족과 온천·스파에서 휴식하는 여행.",
     "아이와 함께 가기 좋은", ["온천·휴양"]),
    ("109_single_healing_forest", "따뜻한 온천과 휴양림에서 쉬는 2박3일.",
     "북적이지 않는 곳", ["온천·휴양"]),
    # --- 3테마 +3 ---
    ("110_triple_history_art_healing", "전통 유적도 보고 미술관도 가고 온천에서 마무리하는 3박4일.",
     "여유로운 일정", ["역사·전통", "예술·감성", "온천·휴양"]),
    ("111_triple_coast_nature_history", "바다와 산, 옛 유적까지 두루 보는 3박4일.",
     "느긋하게 도는", ["바다·해안", "자연·트레킹", "역사·전통"]),
    ("112_triple_nature_healing_art", "숲길을 걷고 온천 후 갤러리도 들르는 여행.",
     "조용한 소도시면 좋겠어", ["자연·트레킹", "온천·휴양", "예술·감성"]),
    # --- 엣지 ---
    ("113_anchored_gangneung_art", "강릉에서 미술관과 감성 카페 위주로 도는 당일치기.",
     "사진 찍기 좋은 곳", ["예술·감성"]),                       # anchored(강릉) + 얇은 테마
    ("114_named_attraction_history", "불국사 같은 역사 유적을 중심으로 경주를 도는 1박2일.",
     "", ["역사·전통"]),                                        # named entity in query
    ("115_no_candidate_inland_coast", "안동에서 바다와 해변을 즐기는 1박2일.",
     "조용한 해변", ["바다·해안"]),                              # 내륙(안동)+바다 = no_candidate 의도
]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    for cid, raw, soft, themes in CASES:
        obj = {"id": cid, "source": SRC, "raw_query": raw, "soft_query": soft, "themes": themes}
        path = os.path.join(OUT, cid + ".json")
        json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 커버리지 요약
    from itertools import combinations
    from collections import Counter
    THEMES = ["바다·해안", "자연·트레킹", "역사·전통", "예술·감성", "온천·휴양"]
    pairs = Counter(tuple(sorted(t)) for _, _, _, t in CASES if len(t) == 2)
    print(f"{len(CASES)}개 케이스 작성 → {OUT}")
    print("추가 페어:", [f"{a}+{b}" for (a, b) in pairs])
    print("추가 3테마:", sum(1 for _, _, _, t in CASES if len(t) >= 3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
