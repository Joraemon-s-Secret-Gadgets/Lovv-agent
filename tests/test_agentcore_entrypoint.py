"""Tests for the AgentCore Runtime entrypoint adapter."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from lovv_agent.agentcore_entrypoint import (
    extract_recommendation_payload,
    extract_request_id,
    handle_invocation,
)


REQUEST = {
    "entryType": "chat",
    "destinationId": None,
    "country": "KR",
    "travelYear": 2026,
    "travelMonth": 10,
    "tripType": "daytrip",
    "themes": ["sea_coast"],
    "includeFestivals": False,
    "naturalLanguageQuery": "조용한 바다",
    "userLocation": None,
}


class FakeHarness:
    """Small harness double used to avoid live AWS calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], str | None]] = []

    def invoke(
        self,
        payload: dict[str, object],
        *,
        request_id: str | None = None,
    ) -> dict[str, object]:
        """Record invocation and return a stable payload."""

        self.calls.append((payload, request_id))
        return {"recommendationId": request_id or "generated"}


class AgentCoreEntrypointTest(unittest.TestCase):
    """Validate AgentCore wrapper normalization."""

    def test_extracts_direct_recommendation_payload(self) -> None:
        self.assertEqual(extract_recommendation_payload(REQUEST), REQUEST)

    def test_extracts_json_body_recommendation_payload(self) -> None:
        event = {"body": json.dumps(REQUEST, ensure_ascii=False)}

        self.assertEqual(extract_recommendation_payload(event), REQUEST)

    def test_extracts_nested_input_recommendation_payload(self) -> None:
        event = {"input": REQUEST}

        self.assertEqual(extract_recommendation_payload(event), REQUEST)

    def test_extracts_prompt_file_json_recommendation_payload(self) -> None:
        event = {"prompt": json.dumps(REQUEST, ensure_ascii=False)}

        self.assertEqual(extract_recommendation_payload(event), REQUEST)

    def test_extracts_request_id_from_common_fields(self) -> None:
        self.assertEqual(extract_request_id({"sessionId": "session-1"}), "session-1")
        self.assertEqual(
            extract_request_id({"headers": {"x-request-id": "req-1"}}),
            "req-1",
        )

    def test_handle_invocation_uses_cached_live_harness_boundary(self) -> None:
        fake = FakeHarness()
        with patch(
            "lovv_agent.agentcore_entrypoint._cached_live_harness",
            return_value=fake,
        ):
            response = handle_invocation({"requestId": "REQ-1", "payload": REQUEST})

        self.assertEqual(response, {"recommendationId": "REQ-1"})
        self.assertEqual(fake.calls, [(REQUEST, "REQ-1")])


if __name__ == "__main__":
    unittest.main()
