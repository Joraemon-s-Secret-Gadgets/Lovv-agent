# AgentV2 Intent 테스트 Input/Output 결과

이 파일은 실제 AgentV2 parser, modify parser, intent node를 호출해 생성한 input/output 결과다.

## 선호 테마 추출

### Input

```json
{
  "raw_query": "바다랑 로컬 맛집 위주로 2박 3일 여행지를 추천해줘"
}
```

### Output

```json
{
  "cleaned_raw_query": "바다랑 로컬 맛집 위주로 2박 3일 여행지를 추천해줘",
  "preferred_theme_ids": [
    "sea_coast",
    "food_local"
  ],
  "disliked_theme_ids": [],
  "preferred_region_ids": [],
  "preferred_region_names": [],
  "disliked_region_ids": [],
  "disliked_region_names": [],
  "active_theme_labels": [
    "바다·해안",
    "미식·노포"
  ],
  "needs_clarification": false,
  "clarifying_question": null,
  "contradiction_reasons": []
}
```

## 선호/비선호 테마 분리

### Input

```json
{
  "raw_query": "전시는 좋지만 등산이나 트레킹 코스는 빼줘"
}
```

### Output

```json
{
  "cleaned_raw_query": "전시는 좋지만 등산이나 트레킹 코스는 빼줘",
  "preferred_theme_ids": [
    "art_sense"
  ],
  "disliked_theme_ids": [
    "nature_trekking"
  ],
  "preferred_region_ids": [],
  "preferred_region_names": [],
  "disliked_region_ids": [],
  "disliked_region_names": [],
  "active_theme_labels": [
    "예술·감성"
  ],
  "needs_clarification": false,
  "clarifying_question": null,
  "contradiction_reasons": []
}
```

## 선호/비선호 지역 분리

### Input

```json
{
  "raw_query": "속초 말고 안동이나 경주처럼 역사 있는 곳으로 추천해줘"
}
```

### Output

```json
{
  "cleaned_raw_query": "속초 말고 안동이나 경주처럼 역사 있는 곳으로 추천해줘",
  "preferred_theme_ids": [
    "history_tradition"
  ],
  "disliked_theme_ids": [],
  "preferred_region_ids": [
    "andong",
    "gyeongju"
  ],
  "preferred_region_names": [
    "안동",
    "경주"
  ],
  "disliked_region_ids": [
    "sokcho"
  ],
  "disliked_region_names": [
    "속초"
  ],
  "active_theme_labels": [
    "역사·전통"
  ],
  "needs_clarification": false,
  "clarifying_question": null,
  "contradiction_reasons": []
}
```

## 지역 선호 충돌 감지

### Input

```json
{
  "raw_query": "강원도는 싫은데 강원도 바다 여행지를 추천해줘"
}
```

### Output

```json
{
  "cleaned_raw_query": "강원도는 싫은데 강원도 바다 여행지를 추천해줘",
  "preferred_theme_ids": [
    "sea_coast"
  ],
  "disliked_theme_ids": [],
  "preferred_region_ids": [
    "gangwon"
  ],
  "preferred_region_names": [
    "강원도"
  ],
  "disliked_region_ids": [
    "gangwon"
  ],
  "disliked_region_names": [
    "강원도"
  ],
  "active_theme_labels": [
    "바다·해안"
  ],
  "needs_clarification": true,
  "clarifying_question": "선호와 비선호가 동시에 언급된 테마나 지역이 있어 우선순위를 확인해야 합니다.",
  "contradiction_reasons": [
    "region:gangwon"
  ]
}
```

## intent_node request handoff

### Input

```json
{
  "request": {
    "country": "KR",
    "travel_month": 8,
    "travel_year": 2026,
    "trip_type": "couple",
    "include_festivals": true,
    "raw_query": "강원도 말고 경북 바다랑 미식 여행지 추천해줘"
  }
}
```

### Output

```json
{
  "intent": {
    "city_select_input": {
      "country": "KR",
      "travel_month": 8,
      "travel_year": 2026,
      "trip_type": "couple",
      "active_required_themes": [
        "바다·해안",
        "미식·노포"
      ],
      "include_festivals": true,
      "cleaned_raw_query": "강원도 말고 경북 바다랑 미식 여행지 추천해줘",
      "soft_preference_query": "",
      "unsupported_conditions": [],
      "destination_id": null,
      "user_location": null,
      "execution_mode": "city_discovery",
      "congestion_pref": "neutral",
      "transport_pref": "unknown",
      "theme_weights": null,
      "city_key": null,
      "ddb_pk": null,
      "destination_label": null
    },
    "cleaned_raw_query": "강원도 말고 경북 바다랑 미식 여행지 추천해줘",
    "soft_preference_query": "",
    "unsupported_conditions": [],
    "preferred_theme_ids": [
      "sea_coast",
      "food_local"
    ],
    "disliked_theme_ids": [],
    "preferred_region_ids": [
      "gyeongbuk"
    ],
    "disliked_region_ids": [
      "gangwon"
    ],
    "preferred_region_names": [
      "경북"
    ],
    "disliked_region_names": [
      "강원도"
    ],
    "needs_clarification": false,
    "clarifying_question": null,
    "contradiction_reasons": []
  }
}
```

## 수정 턴 테마 업데이트

### Input

```json
{
  "raw_query": "2일차 오후는 바다 말고 숲길이랑 온천 중심으로 바꿔줘"
}
```

### Output

```json
{
  "cleaned_raw_query": "2일차 오후는 바다 말고 숲길이랑 온천 중심으로 바꿔줘",
  "preferred_theme_ids": [
    "nature_trekking",
    "healing_rest"
  ],
  "disliked_theme_ids": [
    "sea_coast"
  ],
  "preferred_region_ids": [],
  "preferred_region_names": [],
  "disliked_region_ids": [],
  "disliked_region_names": [],
  "active_theme_labels": [
    "자연·트레킹",
    "온천·휴양"
  ],
  "needs_clarification": false,
  "clarifying_question": null,
  "contradiction_reasons": []
}
```

## 수정 턴 지역 업데이트

### Input

```json
{
  "raw_query": "속초는 빼고 안동 쪽으로 바꿔줘"
}
```

### Output

```json
{
  "cleaned_raw_query": "속초는 빼고 안동 쪽으로 바꿔줘",
  "preferred_theme_ids": [],
  "disliked_theme_ids": [],
  "preferred_region_ids": [
    "andong"
  ],
  "preferred_region_names": [
    "안동"
  ],
  "disliked_region_ids": [
    "sokcho"
  ],
  "disliked_region_names": [
    "속초"
  ],
  "active_theme_labels": [],
  "needs_clarification": false,
  "clarifying_question": null,
  "contradiction_reasons": []
}
```

