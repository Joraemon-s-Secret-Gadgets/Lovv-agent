"""Optional live AWS smoke tests for Task 10 runtime wiring.

These tests are skipped by default. Set ``LOVV_ENABLE_AWS_SMOKE=1`` when a
local environment has non-secret AWS routing config and credentials available.
The default LLM model used by this smoke harness is ``gpt-oss-120b``.
"""

from __future__ import annotations

import os
import unittest

from lovv_agent.adapters.boto3_clients import create_boto3_client_provider
from lovv_agent.config import RuntimeConfig

AWS_SMOKE_FLAG = "LOVV_ENABLE_AWS_SMOKE"
DEFAULT_AWS_SMOKE_LLM_MODEL_ID = "gpt-oss-120b"


def _smoke_enabled() -> bool:
    """Return whether optional live AWS smoke tests should run."""

    return os.environ.get(AWS_SMOKE_FLAG) == "1"


@unittest.skipUnless(
    _smoke_enabled(),
    f"set {AWS_SMOKE_FLAG}=1 to run optional live AWS smoke tests",
)
class AwsRuntimeSmokeTest(unittest.TestCase):
    """Validate live AWS client construction without hardcoded secrets."""

    def test_live_clients_can_be_created_from_env_config(self) -> None:
        env = dict(os.environ)
        env.setdefault("LOVV_LLM_MODEL_ID", DEFAULT_AWS_SMOKE_LLM_MODEL_ID)
        config = RuntimeConfig.from_env(env)

        provider = create_boto3_client_provider(config=config)
        clients = provider.create_runtime_clients()

        self.assertIsNotNone(clients.s3_vectors)
        self.assertIsNotNone(clients.dynamodb)
        self.assertIsNotNone(clients.bedrock_runtime)
        self.assertEqual(config.llm.model_id, env["LOVV_LLM_MODEL_ID"])


if __name__ == "__main__":
    unittest.main()
