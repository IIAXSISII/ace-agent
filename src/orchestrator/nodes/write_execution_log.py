"""
write_execution_log node — writes one ExecutionLogEntry per completed step
to the execution-logs DynamoDB table via src/storage/dynamodb.put_item().

TTL = current Unix timestamp + 90 days.
Redacts sensitive keys in toolInputs (password, secret, key, token).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.storage.dynamodb import put_item

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

_TTL_90_DAYS = 90 * 24 * 3600
_SENSITIVE_KEYWORDS = ("password", "secret", "key", "token")


def _redact_tool_inputs(tool_inputs: dict) -> dict:
    """Replace values for any key containing sensitive keywords with '[REDACTED]'."""
    redacted = {}
    for k, v in tool_inputs.items():
        if any(kw in k.lower() for kw in _SENSITIVE_KEYWORDS):
            redacted[k] = "[REDACTED]"
        else:
            redacted[k] = v
    return redacted


def write_execution_log(state: "OrchestratorState") -> "OrchestratorState":
    step_results = state.get("step_results", [])
    session_id = state.get("session_id", "unknown")
    execution_plan = state.get("execution_plan", [])
    now_unix = int(time.time())
    ttl = now_unix + _TTL_90_DAYS

    for result in step_results:
        step_index = result.get("step_index", 0)
        step = execution_plan[step_index] if step_index < len(execution_plan) else {}

        agent_result = result.get("agent_result", {}) or {}
        tool_inputs = step.get("tool_inputs", {})
        redacted_inputs = _redact_tool_inputs(tool_inputs)

        # Determine validation result
        if result.get("pre_validation_failed"):
            validation_result = "FAIL"
        elif result.get("post_validation_passed"):
            validation_result = "PASS"
        elif result.get("retry_count", 0) > 0:
            validation_result = "RETRY"
        else:
            validation_result = "FAIL"

        step_timestamp = datetime.now(timezone.utc).isoformat()

        entry = {
            "requestId": session_id,
            "stepTimestamp": step_timestamp,
            "stepIndex": step_index,
            "subAgent": result.get("agent_id", step.get("agent_id", "unknown")),
            "tool": result.get("tool_name", step.get("tool_name", "unknown")),
            "toolInputs": redacted_inputs,
            "toolOutput": agent_result,
            "validationResult": validation_result,
            "confidenceScore": agent_result.get("confidence_score", 0.0),
            "errorMessage": (
                result.get("pre_validation_error")
                or result.get("post_validation_error")
                or agent_result.get("error")
            ),
            "tokenCount": agent_result.get("token_count", 0),
            "promptTemplateId": result.get("prompt_template_id", "unknown"),
            "promptTemplateVersion": result.get("prompt_template_version", "unknown"),
            "ttl": ttl,
        }

        put_item("execution-logs", entry)

    return state
