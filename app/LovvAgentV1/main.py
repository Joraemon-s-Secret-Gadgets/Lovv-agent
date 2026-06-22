"""AgentCore Runtime app for LovvAgentV1."""

from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from lovv_agent.agentcore_entrypoint import handle_invocation

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context):
    """Invoke the Lovv recommendation graph inside AgentCore Runtime."""

    return handle_invocation(payload, context)


if __name__ == "__main__":
    app.run()
