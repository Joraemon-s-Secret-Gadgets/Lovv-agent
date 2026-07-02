"""Unit tests for V2 MemorySettings and RuntimeConfig."""

from __future__ import annotations

import pytest

from lovv_agent_v2.infra.config import (
    ConfigError,
    ENV_KEYS,
    LLM_NODE_EXPLANATION,
    LLM_ROUTING_NODES,
    RuntimeConfig,
)


def test_memory_settings_default() -> None:
    """Verify that memory is disabled by default."""
    config = RuntimeConfig.from_env(env={})
    assert config.memory.enabled is False
    assert config.memory.memory_id is None
    assert config.memory.event_expiry_days == 7
    assert config.memory.kms_key_arn is None
    assert config.search_budget.per_theme_attraction_top_k == 50


def test_memory_settings_parsing() -> None:
    """Verify correct env parsing for memory settings."""
    env = {
        "LOVV_MEMORY_ENABLED": "true",
        "LOVV_MEMORY_ID": "v2-test-memory",
        "LOVV_MEMORY_EVENT_EXPIRY_DAYS": "14",
        "LOVV_MEMORY_KMS_KEY_ARN": "arn:aws:kms:us-east-1:123456789012:key/test",
    }
    config = RuntimeConfig.from_env(env=env)
    assert config.memory.enabled is True
    assert config.memory.memory_id == "v2-test-memory"
    assert config.memory.event_expiry_days == 14
    assert config.memory.kms_key_arn == "arn:aws:kms:us-east-1:123456789012:key/test"


def test_memory_settings_invalid_expiry() -> None:
    """Verify validation boundaries for event_expiry_days."""
    # Under limit (0) - _positive_int catches this as not a positive integer
    with pytest.raises(ConfigError, match="LOVV_MEMORY_EVENT_EXPIRY_DAYS must be a positive integer"):
        RuntimeConfig.from_env(env={"LOVV_MEMORY_EVENT_EXPIRY_DAYS": "0"})

    # Over limit (366) - __post_init__ catches this
    with pytest.raises(ConfigError, match="event_expiry_days must be 1..365"):
        RuntimeConfig.from_env(env={"LOVV_MEMORY_EVENT_EXPIRY_DAYS": "366"})

    # Not an integer
    with pytest.raises(ConfigError, match="LOVV_MEMORY_EVENT_EXPIRY_DAYS must be a positive integer"):
        RuntimeConfig.from_env(env={"LOVV_MEMORY_EVENT_EXPIRY_DAYS": "invalid"})


def test_candidate_evidence_llm_config_is_removed() -> None:
    assert "candidate_evidence" not in LLM_ROUTING_NODES
    assert "LOVV_CANDIDATE_EVIDENCE_LLM_MODEL_ID" not in ENV_KEYS
    assert "LOVV_CANDIDATE_EVIDENCE_LLM_ADAPTER_ID" not in ENV_KEYS

    config = RuntimeConfig.from_env(
        env={
            "LOVV_CANDIDATE_EVIDENCE_LLM_MODEL_ID": "ignored-model",
            "LOVV_CANDIDATE_EVIDENCE_LLM_ADAPTER_ID": "ignored-adapter",
        },
    )

    assert config.llm.model_ids_by_node == {}
    assert config.llm.adapter_ids_by_node == {}


def test_explanation_llm_model_config_is_node_specific() -> None:
    config = RuntimeConfig.from_env(
        env={
            "LOVV_PLANNER_LLM_MODEL_ID": "planner-model",
            "LOVV_EXPLANATION_LLM_MODEL_ID": "explanation-model",
        },
    )

    assert LLM_NODE_EXPLANATION in LLM_ROUTING_NODES
    assert "planner" not in LLM_ROUTING_NODES
    assert "LOVV_PLANNER_LLM_MODEL_ID" not in ENV_KEYS
    assert "LOVV_EXPLANATION_LLM_MODEL_ID" in ENV_KEYS
    assert config.llm.model_ids_by_node[LLM_NODE_EXPLANATION] == "explanation-model"
    assert "planner" not in config.llm.model_ids_by_node
