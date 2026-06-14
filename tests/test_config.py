"""Tests for the Task 1.2 runtime configuration boundary."""

from __future__ import annotations

import unittest

from lovv_agent.config import (
    CONFIG_SECTIONS,
    ENV_KEYS,
    ConfigError,
    RuntimeConfig,
    SearchBudgetSettings,
    default_runtime_config,
)


class RuntimeConfigTest(unittest.TestCase):
    """Verify safe defaults, injection, and validation behavior."""

    def test_default_config_is_local_safe_and_has_no_fixed_model(self) -> None:
        config = default_runtime_config()

        self.assertEqual(config.aws.region, "us-east-1")
        self.assertIsNone(config.aws.profile_name)
        self.assertEqual(config.s3_vectors.bucket_name, "local-lovv-vector-bucket")
        self.assertEqual(config.dynamodb.table_name, "local-lovv-table")
        self.assertEqual(config.llm.adapter_id, "bedrock-converse")
        self.assertIsNone(config.llm.model_id)
        self.assertIsNone(config.embeddings.model_id)

    def test_config_sections_cover_required_runtime_boundaries(self) -> None:
        self.assertEqual(
            CONFIG_SECTIONS,
            (
                "aws",
                "s3_vectors",
                "dynamodb",
                "embeddings",
                "llm",
                "search_budget",
                "timeouts",
                "retries",
            ),
        )

    def test_from_env_uses_injected_mapping_without_real_credentials(self) -> None:
        config = RuntimeConfig.from_env(
            {
                "LOVV_AWS_REGION": "ap-northeast-2",
                "LOVV_AWS_PROFILE": "lovv-dev",
                "LOVV_S3_VECTOR_BUCKET": "lovv-vector-bucket",
                "LOVV_S3_VECTOR_INDEX": "attractions-index",
                "LOVV_DYNAMODB_TABLE": "lovv-dev-table",
                "LOVV_EMBEDDING_ADAPTER_ID": "bedrock-embedding",
                "LOVV_EMBEDDING_MODEL_ID": "embedding-model-from-runtime",
                "LOVV_LLM_ADAPTER_ID": "bedrock-converse",
                "LOVV_LLM_MODEL_ID": "model-from-runtime",
                "LOVV_SEARCH_PER_THEME_TOP_K": "8",
                "LOVV_SEARCH_RAW_SOFT_TOP_K": "4",
                "LOVV_MAX_FESTIVAL_SEED_CANDIDATES": "11",
                "LOVV_VERIFIER_CANDIDATE_K": "3",
                "LOVV_CONNECT_TIMEOUT_SECONDS": "1.5",
                "LOVV_READ_TIMEOUT_SECONDS": "9.5",
                "LOVV_MAX_RETRY_ATTEMPTS": "4",
                "LOVV_SCHEMA_RETRY_LIMIT": "2",
            },
        )

        self.assertEqual(config.aws.region, "ap-northeast-2")
        self.assertEqual(config.aws.profile_name, "lovv-dev")
        self.assertEqual(config.s3_vectors.index_name, "attractions-index")
        self.assertEqual(config.dynamodb.table_name, "lovv-dev-table")
        self.assertEqual(config.embeddings.adapter_id, "bedrock-embedding")
        self.assertEqual(config.llm.model_id, "model-from-runtime")
        self.assertEqual(config.search_budget.per_theme_attraction_top_k, 8)
        self.assertEqual(config.search_budget.raw_soft_channel_top_k, 4)
        self.assertEqual(config.search_budget.max_festival_seed_candidates, 11)
        self.assertEqual(config.search_budget.verifier_candidate_k, 3)
        self.assertEqual(config.timeouts.connect_seconds, 1.5)
        self.assertEqual(config.timeouts.read_seconds, 9.5)
        self.assertEqual(config.retries.max_attempts, 4)

    def test_search_budgets_reject_zero_or_negative_values(self) -> None:
        with self.assertRaises(ConfigError):
            SearchBudgetSettings(per_theme_attraction_top_k=0)

        with self.assertRaises(ConfigError):
            RuntimeConfig.from_env({"LOVV_VERIFIER_CANDIDATE_K": "-1"})

    def test_empty_required_env_values_are_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            RuntimeConfig.from_env({"LOVV_DYNAMODB_TABLE": " "})

    def test_supported_env_keys_do_not_include_secret_material(self) -> None:
        forbidden_fragments = ("SECRET", "ACCESS_KEY", "TOKEN", "PASSWORD")

        for key in ENV_KEYS:
            self.assertFalse(
                any(fragment in key for fragment in forbidden_fragments),
                f"{key} should not be a supported config env var",
            )

    def test_config_can_be_serialized_for_injection_debugging(self) -> None:
        config_dict = default_runtime_config().to_dict()

        self.assertEqual(config_dict["aws"]["region"], "us-east-1")
        self.assertIn("search_budget", config_dict)


if __name__ == "__main__":
    unittest.main()
