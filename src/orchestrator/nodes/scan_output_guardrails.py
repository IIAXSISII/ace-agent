"""
scan_output_guardrails node:
  - When BEDROCK_GUARDRAIL_ID is NOT set: passthrough (return state unchanged)
  - When BEDROCK_GUARDRAIL_ID IS set: use get_guardrailed_llm() to scan final_response;
    log violations to guardrail-violations DynamoDB table on block events.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from src.guardrails.bedrock import get_guardrailed_llm, log_violation

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

_GUARDRAIL_BLOCKED_RESPONSE = (
    "⚠️ This response was blocked by content safety guardrails. "
    "Please rephrase your request or contact your administrator."
)


def scan_output_guardrails(state: "OrchestratorState") -> "OrchestratorState":
    guardrail_id = os.getenv("BEDROCK_GUARDRAIL_ID", "")

    # Passthrough when no guardrail configured (local dev)
    if not guardrail_id:
        return state

    final_response = state.get("final_response", "") or ""
    if not final_response:
        return state

    llm = get_guardrailed_llm()
    try:
        response = llm.invoke([HumanMessage(content=final_response)])
        response_content = response.content if hasattr(response, "content") else str(response)

        # Empty response means guardrail blocked the content
        if not response_content or response_content.strip() == "":
            log_violation(
                violation_type="CONTENT",
                severity="HIGH",
                redacted_content=final_response[:500],
                request_id=state.get("session_id", "unknown"),
            )
            return {**state, "final_response": _GUARDRAIL_BLOCKED_RESPONSE}

        return {**state, "final_response": response_content}

    except Exception as exc:
        error_str = str(exc).lower()
        if "guardrail" in error_str or "blocked" in error_str or "intervention" in error_str:
            log_violation(
                violation_type="INJECTION",
                severity="HIGH",
                redacted_content=final_response[:500],
                request_id=state.get("session_id", "unknown"),
            )
            return {**state, "final_response": _GUARDRAIL_BLOCKED_RESPONSE}
        raise
