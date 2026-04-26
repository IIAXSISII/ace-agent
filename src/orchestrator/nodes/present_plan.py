from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState


def present_plan(state: "OrchestratorState") -> "OrchestratorState":
    """
    Signal that the execution plan is ready for user review.

    In F01 (no real interrupt mechanism), auto-approves the plan so execution
    proceeds immediately. Sets pending_approval = False so _route_present_plan
    routes to validate_step_pre exactly once and does not loop back to generate_plan.

    In a future feature with LangGraph interrupt support, this node would set
    pending_approval = True and yield control to the Chainlit UI for explicit
    user confirmation before resuming.
    """
    return {**state, "pending_approval": False}
