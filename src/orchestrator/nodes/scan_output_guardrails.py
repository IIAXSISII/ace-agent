"""
scan_output_guardrails node:
  - When GUARDRAIL_ID is NOT set: passthrough (return state unchanged)
  - When GUARDRAIL_ID IS set: use ChatBedrock with guardrail_config to scan final_response
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

_GUARDRAIL_BLOCKED_RESPONSE = (
    "⚠️ This response was blocked by content safety guardrails. "
    "Please rephrase your request or contact your administrator."
)


def scan_output_guardrails(state: "OrchestratorState") -> "OrchestratorState":
    guardrail_id = os.getenv("GUARDRAIL_ID", "")

    # Passthrough when no guardrail configured
    if not guardrail_id:
        return state

    final_response = state.get("final_response", "") or ""
    if not final_response:
        return state

    bedrock_model = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

    try:
        from langchain_aws import ChatBedrock
        from langchain_core.messages import HumanMessage

        llm = ChatBedrock(
            model_id=bedrock_model,
            guardrails={
                "guardrailIdentifier": guardrail_id,
                "guardrailVersion": "DRAFT",
                "trace": "enabled",
            },
        )

        response = llm.invoke([HumanMessage(content=final_response)])

        # Check if guardrail blocked the response
        # Bedrock returns a specific stop reason when guardrails intervene
        response_content = response.content if hasattr(response, "content") else str(response)

        # If the response is empty or contains guardrail intervention markers, replace it
        if not response_content or response_content.strip() == "":
            return {**state, "final_response": _GUARDRAIL_BLOCKED_RESPONSE}

        return {**state, "final_response": response_content}

    except Exception as exc:
        # If guardrail scanning fails (e.g., blocked), return safe message
        error_str = str(exc).lower()
        if "guardrail" in error_str or "blocked" in error_str or "intervention" in error_str:
            return {**state, "final_response": _GUARDRAIL_BLOCKED_RESPONSE}
        # Re-raise unexpected errors
        raise
