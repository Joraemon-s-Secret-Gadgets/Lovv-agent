"""Composition Root for Lovv Agent V2.

This module initializes dependencies (infra) and passes them to the graph components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.agents.intent.tools import IntentPromptRuntime
from lovv_agent_v2.infra.adapters.bedrock_converse import create_bedrock_converse_runtime
from lovv_agent_v2.infra.aws_clients import create_boto3_client_provider
from lovv_agent_v2.infra.config import LLM_NODE_INTENT, RuntimeConfig, resolve_llm_model_id
from lovv_agent_v2.infra.memory.checkpointer import build_checkpointer
from lovv_agent_v2.core.graph import compile_v2_graph


@dataclass(frozen=True, slots=True)
class LovvLangGraphV2Harness:
    """Compiled LangGraph V2 plus its runtime configuration."""

    graph: Any
    config: RuntimeConfig
    runtime: dict[str, Any] | None = None

    def invoke(
        self,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        graph_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke the V2 graph and return the output."""

        config = dict(graph_config or {})
        return self.graph.invoke(self._payload_with_runtime(payload), config=config)

    def _payload_with_runtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        graph_payload = dict(payload)
        if self.runtime is not None and "runtime" not in graph_payload:
            graph_payload["runtime"] = self.runtime
        return graph_payload


def build_v2_harness(
    config: RuntimeConfig,
    checkpointer: Any | None = None,
    runtime: dict[str, Any] | None = None,
) -> LovvLangGraphV2Harness:
    """Build and compile the V2 recommendation graph."""

    graph = compile_v2_graph(checkpointer=checkpointer)
    return LovvLangGraphV2Harness(graph=graph, config=config, runtime=runtime)


def build_live_harness(
    config: RuntimeConfig | None = None,
) -> LovvLangGraphV2Harness:
    """Build a live harness from injected or environment config with checkpointer."""

    resolved_config = RuntimeConfig.from_env() if config is None else config
    checkpointer = build_checkpointer(resolved_config.memory)
    client_provider = create_boto3_client_provider(config=resolved_config)
    runtime = {
        "intent_prompt_runtime": _build_live_intent_prompt_runtime(
            resolved_config,
            bedrock_runtime_client=client_provider.create_bedrock_runtime_client(),
        ),
    }
    return build_v2_harness(
        config=resolved_config,
        checkpointer=checkpointer,
        runtime=runtime,
    )


def _build_live_intent_prompt_runtime(
    config: RuntimeConfig,
    *,
    bedrock_runtime_client: Any,
) -> IntentPromptRuntime:
    model_id = resolve_llm_model_id(config.llm, LLM_NODE_INTENT)
    bedrock_runtime = (
        None
        if model_id is None
        else create_bedrock_converse_runtime(
            client=bedrock_runtime_client,
            model_id=model_id,
        )
    )
    return IntentPromptRuntime(
        runtime=bedrock_runtime,
        schema_retry_limit=config.retries.schema_retry_limit,
    )


__all__ = ["LovvLangGraphV2Harness", "build_v2_harness", "build_live_harness"]

