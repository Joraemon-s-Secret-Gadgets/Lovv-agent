"""Repeatable Bedrock playground for Lovv Intent prompt/schema experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PLAYGROUND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PLAYGROUND_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lovv_agent.adapters.bedrock_converse import (  # noqa: E402
    build_structured_converse_request,
    create_bedrock_converse_runtime,
    extract_structured_output,
)


def main() -> int:
    args = parse_args()
    prompt_path = resolve_path(args.prompt)
    schema_path = resolve_path(args.schema)
    cases_path = resolve_path(args.cases)
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    schema = load_json_object(schema_path)
    cases = load_cases(cases_path, case_id=args.case_id)
    if not cases:
        raise PlaygroundError("no cases selected")

    model_id = args.model_id or os.environ.get("LOVV_LLM_MODEL_ID")
    if not args.dry_run and not model_id:
        raise PlaygroundError(
            "model id is required: use --model-id or LOVV_LLM_MODEL_ID",
        )

    run_dir = make_run_dir(resolve_path(args.output_dir))
    prompt_sha256 = sha256_text(prompt)
    schema_sha256 = sha256_text(json.dumps(schema, ensure_ascii=False, sort_keys=True))
    requests_path = run_dir / "requests.jsonl"
    results_path = run_dir / "results.jsonl"

    runtime = None if args.dry_run else build_runtime(args, model_id)
    results: list[dict[str, Any]] = []

    for case in cases:
        for repetition in range(1, args.repeat + 1):
            request = build_request(
                prompt=prompt,
                schema=schema,
                case_input=case["input"],
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            )
            request_record = {
                "case_id": case["id"],
                "repetition": repetition,
                "model_id": model_id,
                "prompt_sha256": prompt_sha256,
                "schema_sha256": schema_sha256,
                "request": request,
            }
            append_jsonl(requests_path, request_record)

            if args.dry_run:
                print(
                    f"[DRY-RUN] {case['id']} repetition={repetition} "
                    f"request={requests_path}",
                )
                continue

            result = execute_case(
                runtime=runtime,
                request=request,
                case=case,
                repetition=repetition,
                model_id=model_id,
                prompt_sha256=prompt_sha256,
                schema_sha256=schema_sha256,
            )
            results.append(result)
            append_jsonl(results_path, result)
            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"[{status}] {case['id']} repetition={repetition} "
                f"latency_ms={result['latency_ms']}",
            )

    summary = build_summary(
        dry_run=args.dry_run,
        model_id=model_id,
        prompt_path=prompt_path,
        schema_path=schema_path,
        cases_path=cases_path,
        prompt_sha256=prompt_sha256,
        schema_sha256=schema_sha256,
        selected_cases=len(cases),
        repeat=args.repeat,
        results=results,
    )
    write_json(run_dir / "summary.json", summary)
    print(f"Results: {run_dir}")
    return 0 if args.dry_run or summary["failed"] == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeatable Lovv Intent prompt/schema experiments.",
    )
    parser.add_argument("--prompt", default=str(PLAYGROUND_DIR / "prompt.md"))
    parser.add_argument("--schema", default=str(PLAYGROUND_DIR / "schema.json"))
    parser.add_argument("--cases", default=str(PLAYGROUND_DIR / "cases.jsonl"))
    parser.add_argument("--output-dir", default=str(PLAYGROUND_DIR / "results"))
    parser.add_argument("--case-id")
    parser.add_argument("--repeat", type=positive_int, default=1)
    parser.add_argument("--model-id")
    parser.add_argument("--region", default=os.environ.get("LOVV_AWS_REGION", "us-east-1"))
    parser.add_argument("--profile", default=os.environ.get("LOVV_AWS_PROFILE"))
    parser.add_argument("--max-tokens", type=positive_int, default=1600)
    parser.add_argument("--temperature", type=bounded_temperature, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def build_request(
    *,
    prompt: str,
    schema: dict[str, Any],
    case_input: dict[str, Any],
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    user_payload = {
        "task": (
            "API structured input은 변경하지 말고, 자연어 보조 입력에서 "
            "검색용 의미 신호와 core field 변경 요청만 추출하세요."
        ),
        "api_structured_input": case_input.get("api_structured_input", {}),
        "conversation_summary": case_input.get("conversation_summary"),
        "messages": case_input.get("messages", []),
    }
    request = build_structured_converse_request(
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
            },
        ],
        system=[{"text": prompt}],
        schema_name="intent_agent_playground_output",
        schema=schema,
        schema_description="Experimental Lovv Intent Agent structured output",
    )
    request["inferenceConfig"] = {
        "maxTokens": max_tokens,
        "temperature": temperature,
    }
    return request


def build_runtime(args: argparse.Namespace, model_id: str):
    import boto3

    session_kwargs: dict[str, Any] = {"region_name": args.region}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    session = boto3.Session(**session_kwargs)
    client = session.client("bedrock-runtime")
    return create_bedrock_converse_runtime(client=client, model_id=model_id)


def execute_case(
    *,
    runtime: Any,
    request: dict[str, Any],
    case: dict[str, Any],
    repetition: int,
    model_id: str,
    prompt_sha256: str,
    schema_sha256: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    raw_response: Any = None
    parsed_output: dict[str, Any] | None = None
    error: str | None = None
    assertion_results: list[dict[str, Any]] = []

    try:
        raw_response = runtime(request)
        parsed_output = dict(extract_structured_output(raw_response))
        resolved_theme_state = resolve_theme_state(
            case["input"].get("api_structured_input", {}),
            parsed_output,
        )
        evaluation_payload = {
            **parsed_output,
            "resolved_theme_state": resolved_theme_state,
        }
        assertion_results = evaluate_assertions(
            evaluation_payload,
            case.get("assertions", []),
        )
    except Exception as exc:  # noqa: BLE001 - playground records provider/schema errors.
        error = f"{type(exc).__name__}: {exc}"

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    passed = error is None and all(result["passed"] for result in assertion_results)
    return {
        "case_id": case["id"],
        "description": case.get("description", ""),
        "repetition": repetition,
        "model_id": model_id,
        "prompt_sha256": prompt_sha256,
        "schema_sha256": schema_sha256,
        "latency_ms": latency_ms,
        "passed": passed,
        "assertions": assertion_results,
        "parsed_output": parsed_output,
        "resolved_theme_state": (
            resolve_theme_state(
                case["input"].get("api_structured_input", {}),
                parsed_output,
            )
            if parsed_output is not None
            else None
        ),
        "raw_response": json_safe(raw_response),
        "error": error,
    }


def evaluate_assertions(
    payload: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for assertion in assertions:
        path = required_text(assertion.get("path"), "assertion.path")
        operator = required_text(assertion.get("op"), "assertion.op")
        expected = assertion.get("value")
        actual, found = resolve_json_path(payload, path)
        passed = apply_operator(
            operator=operator,
            actual=actual,
            expected=expected,
            found=found,
        )
        results.append(
            {
                "path": path,
                "op": operator,
                "expected": expected,
                "actual": actual if found else None,
                "found": found,
                "passed": passed,
            },
        )
    return results


def resolve_theme_state(
    api_structured_input: dict[str, Any],
    semantic_output: dict[str, Any],
    *,
    max_active_themes: int = 3,
) -> dict[str, list[str]]:
    """Resolve active and backup themes without letting the model rewrite API input."""

    selected = dedupe_strings(api_structured_input.get("themes", []))
    mentioned = dedupe_strings(semantic_output.get("mentioned_theme_ids", []))
    excluded = set(dedupe_strings(semantic_output.get("excluded_theme_ids", [])))

    selected = [theme for theme in selected if theme not in excluded]
    mentioned = [theme for theme in mentioned if theme not in excluded]

    if mentioned:
        active = mentioned[:max_active_themes]
        backup = [theme for theme in selected if theme not in active]
        backup.extend(theme for theme in mentioned[max_active_themes:] if theme not in backup)
    else:
        active = selected[:max_active_themes]
        backup = selected[max_active_themes:]

    return {
        "active_theme_ids": active,
        "backup_theme_ids": backup,
        "excluded_theme_ids": sorted(excluded),
    }


def dedupe_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ),
    )


def resolve_json_path(payload: Any, path: str) -> tuple[Any, bool]:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return None, False
    return current, True


def apply_operator(
    *,
    operator: str,
    actual: Any,
    expected: Any,
    found: bool,
) -> bool:
    if operator == "equals":
        return found and actual == expected
    if operator == "not_equals":
        return found and actual != expected
    if operator == "contains":
        return found and isinstance(actual, str) and str(expected) in actual
    if operator == "not_contains":
        return found and isinstance(actual, str) and str(expected) not in actual
    if operator == "includes":
        return found and isinstance(actual, list) and expected in actual
    if operator == "not_includes":
        return found and isinstance(actual, list) and expected not in actual
    if operator == "is_null":
        return found and actual is None
    if operator == "not_null":
        return found and actual is not None
    if operator == "length_equals":
        return found and hasattr(actual, "__len__") and len(actual) == expected
    raise PlaygroundError(f"unsupported assertion operator: {operator}")


def load_cases(path: Path, *, case_id: str | None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            case = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise PlaygroundError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(case, dict):
            raise PlaygroundError(f"{path}:{line_number}: case must be an object")
        current_id = required_text(case.get("id"), "case.id")
        if current_id in seen_ids:
            raise PlaygroundError(f"duplicate case id: {current_id}")
        seen_ids.add(current_id)
        if not isinstance(case.get("input"), dict):
            raise PlaygroundError(f"{current_id}: input must be an object")
        assertions = case.get("assertions", [])
        if not isinstance(assertions, list):
            raise PlaygroundError(f"{current_id}: assertions must be a list")
        if case_id is None or current_id == case_id:
            cases.append(case)
    if case_id and not cases:
        raise PlaygroundError(f"case id not found: {case_id}")
    return cases


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PlaygroundError(f"{path}: expected a JSON object")
    return value


def build_summary(
    *,
    dry_run: bool,
    model_id: str | None,
    prompt_path: Path,
    schema_path: Path,
    cases_path: Path,
    prompt_sha256: str,
    schema_sha256: str,
    selected_cases: int,
    repeat: int,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    passed = sum(1 for result in results if result["passed"])
    failed = len(results) - passed
    latencies = [result["latency_ms"] for result in results]
    return {
        "dry_run": dry_run,
        "model_id": model_id,
        "prompt_path": str(prompt_path),
        "schema_path": str(schema_path),
        "cases_path": str(cases_path),
        "prompt_sha256": prompt_sha256,
        "schema_sha256": schema_sha256,
        "selected_cases": selected_cases,
        "repeat": repeat,
        "executions": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / len(results), 4) if results else None,
        "average_latency_ms": (
            round(sum(latencies) / len(latencies), 2) if latencies else None
        ),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def make_run_dir(base_dir: Path) -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlaygroundError(f"{field_name} must be a non-empty string")
    return value.strip()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return parsed


def bounded_temperature(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("temperature must be between 0 and 1")
    return parsed


class PlaygroundError(RuntimeError):
    """Raised for invalid playground configuration or case data."""


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PlaygroundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
