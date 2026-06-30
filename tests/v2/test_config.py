"""Unit tests for V2 MemorySettings and RuntimeConfig."""

from __future__ import annotations

import pytest

from lovv_agent_v2.infra.config import ConfigError, MemorySettings, RuntimeConfig


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
