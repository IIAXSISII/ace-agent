"""
validate_step_pre node — checks before executing a plan step:
  1. All required inputs are present in tool_inputs
  2. Sub-agent is available in subagent-registry (ACTIVE + HEALTHY)
  3. Action (tool_name) is within the sub-agent's allowedActions list
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from src.storage.dynamodb import query

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState


def validate_step_pre(state: "OrchestratorState") -> "OrchestratorState":
    execution_plan = state.get("execution_plan", [])
    current_step_index = state.get("current_step_index", 0)
    step = execution_plan[current_step_index] if current_step_index < len(execution_plan) else {}

    step_results = list(state.get("step_results", []))

    # ── Check 1: required inputs present ─────────────────────────────────────
    tool_inputs = step.get("tool_inputs", {})
    expected_schema = step.get("expected_output_schema", {})
    required_fields = expected_schema.get("required", [])

    missing_fields = [f for f in required_fields if f not in tool_inputs]
    if not tool_inputs and not required_fields:
        # No schema constraints — treat as inputs present
        pass
    elif missing_fields:
        step_results.append({
            "step_index": current_step_index,
            "pre_validation_failed": True,
            "pre_validation_error": f"Missing required tool inputs: {missing_fields}",
            "retry_count": 0,
            "post_validation_passed": False,
        })
        return {**state, "step_results": step_results}

    # ── Check 2: sub-agent available in registry ──────────────────────────────
    category = step.get("expected_category", "")
    agents = query(
        "subagent-registry",
        "category = :cat",
        {":cat": category},
    )
    active_healthy = [
        a for a in agents
        if a.get("status") == "ACTIVE" and a.get("healthStatus") == "HEALTHY"
    ]
    if not active_healthy:
        step_results.append({
            "step_index": current_step_index,
            "pre_validation_failed": True,
            "pre_validation_error": (
                f"No ACTIVE/HEALTHY sub-agent found for category '{category}'"
            ),
            "retry_count": 0,
            "post_validation_passed": False,
        })
        return {**state, "step_results": step_results}

    # ── Check 3: action within allowedActions ─────────────────────────────────
    tool_name = step.get("tool_name", "")
    allowed = any(tool_name in a.get("allowedActions", []) for a in active_healthy)
    if tool_name and not allowed:
        step_results.append({
            "step_index": current_step_index,
            "pre_validation_failed": True,
            "pre_validation_error": (
                f"Action '{tool_name}' is not in allowedActions for any available "
                f"sub-agent in category '{category}'"
            ),
            "retry_count": 0,
            "post_validation_passed": False,
        })
        return {**state, "step_results": step_results}

    # ── All checks passed ─────────────────────────────────────────────────────
    step_results.append({
        "step_index": current_step_index,
        "pre_validation_failed": False,
        "pre_validation_error": None,
        "retry_count": 0,
        "post_validation_passed": False,
    })
    return {**state, "step_results": step_results}
