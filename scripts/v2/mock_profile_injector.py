from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lovv_agent_v2.agents.profile.node import profile_node
from lovv_agent_v2.models.schemas import SchemaValidationError


class ProfileInjectionError(ValueError):
    pass


def build_city_select_input(
    intent_mock: Mapping[str, Any],
    profile_store: Mapping[str, Any],
    *,
    actor_id: str,
) -> dict[str, Any]:
    intent_output = _intent_output(intent_mock)
    state = {
        "intent": {"city_select_input": intent_output},
        "profile": {"profile_record": _find_profile_record(profile_store, actor_id)},
    }
    result = profile_node(state)
    city_input = dict(result["intent"]["city_select_input"])
    city_input["profile_mock"] = result["profile"]["audit"]
    return city_input


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProfileInjectionError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _intent_output(intent_mock: Mapping[str, Any]) -> Mapping[str, Any]:
    value = intent_mock.get("intent_output", intent_mock)
    if not isinstance(value, Mapping):
        raise ProfileInjectionError("intent mock must contain an object intent_output")
    return value


def _find_profile_record(profile_store: Mapping[str, Any], actor_id: str) -> Mapping[str, Any]:
    records = profile_store.get("records")
    if not isinstance(records, list):
        raise ProfileInjectionError("profile store is missing records")
    candidates = {actor_id}
    if not actor_id.startswith("mock://profile/"):
        candidates.add(f"mock://profile/{actor_id}")
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if record.get("actor_id") in candidates or record.get("profile_id") == actor_id:
            return record
    raise ProfileInjectionError(f"unknown actor_id: {actor_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject a synthetic profile into a V2 intent mock")
    parser.add_argument("--intent-mock", required=True)
    parser.add_argument("--actor-id")
    parser.add_argument("--persona-id")
    parser.add_argument(
        "--profiles",
        default="src/lovv_agent_v2/resources/mock_user_profiles.json",
    )
    parser.add_argument("--out")
    args = parser.parse_args()
    actor_id = args.actor_id or args.persona_id
    if not actor_id:
        raise ProfileInjectionError("--actor-id or --persona-id is required")
    try:
        payload = build_city_select_input(
            load_json(Path(args.intent_mock)),
            load_json(Path(args.profiles)),
            actor_id=actor_id,
        )
    except SchemaValidationError as exc:
        raise ProfileInjectionError(str(exc)) from exc
    if args.out:
        write_json(Path(args.out), payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
