"""Bedrock Converse adapter placeholder.

This module defines the future boundary for schema-enforced LLM calls. Task 1.1
must not import provider SDKs or instantiate model clients.
"""

from __future__ import annotations

ADAPTER_NAME = "BedrockConverseAdapter"

RESPONSIBILITY = "Provide schema-oriented LLM calls through an injected runtime."

__all__ = ["ADAPTER_NAME", "RESPONSIBILITY"]
