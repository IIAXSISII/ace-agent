"""
validate_step_post node — validates sub-agent output after execution:
  1. Output schema check: result must have 'result' and 'confidence_score' fields
  2. Confidence threshold: confidence_score >= 0.7
  3. On pass: set post_validation_passed=True, advance current_step_index
  4. On fail: increment retry_count, set post_validation_passed=False
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

CONFIDENCE_THRESHOLD = 0.7


def validate_step_post(state: "OrchestratorState") -> "OrchestratorState":
    step_results = list(state.get("step_results", []))
    execution_plan = state.get("execution_plan", [])
    current_step_index = state.get("current_step_index", 0)

    if not step_results:
        return state

    last = dict(step_results[-1])
    agent_result = last.get("agent_result", {}) or {}

    # ── Check 1: output schema ────────────────────────────────────────────────
    has_result = "result" in agent_result
    has_confidence = "confidence_score" in agent_result

    if not has_result or not has_confidence:
        last["retry_count"] = last.get("retry_count", 0) + 1
        last["post_validation_passed"] = False
        last["post_validation_error"] = (
            "Output missing required fields: "
            + ", ".join(f for f, present in [("result", has_result), ("confidence_score", has_confidence)] if not present)
        )
        step_results[-1] = last
        return {**state, "step_results": step_results}

    # ── Check 2: confidence threshold ─────────────────────────────────────────
    confidence = agent_result.get("confidence_score", 0.0)
    if confidence < CONFIDENCE_THRESHOLD:
        last["retry_count"] = last.get("retry_count", 0) + 1
        last["post_validation_passed"] = False
        last["post_validation_error"] = (
            f"confidence_score {confidence:.2f} is below threshold {CONFIDENCE_THRESHOLD}"
        )
        step_results[-1] = last
        return {**state, "step_results": step_results}

    # ── Validation passed ─────────────────────────────────────────────────────
    last["post_validation_passed"] = True
    last["post_validation_error"] = None
    step_results[-1] = last

    # Advance step index if more steps remain
    new_step_index = current_step_index
    if current_step_index < len(execution_plan) - 1:
        new_step_index = current_step_index + 1

    return {**state, "step_results": step_results, "current_step_index": new_step_index}
