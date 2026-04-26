from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState


def present_plan(state: "OrchestratorState") -> "OrchestratorState":
    """
    Signal that the execution plan is ready for user review.

    Sets pending_approval = True so the graph routing function (_route_present_plan)
    can detect that the plan has been presented. In the full Chainlit integration,
    the graph is interrupted here via LangGraph's interrupt mechanism and the UI
    renders the plan for user approval. For local testing, _route_present_plan
    routes directly to validate_step_pre when pending_approval is True.
    """
    return {**state, "pending_approval": True}
