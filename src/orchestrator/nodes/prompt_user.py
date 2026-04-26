"""
prompt_user node — handles two cases:
  1. Missing inputs: consolidates all missing_inputs into a single prompt
  2. Clarifying question: surfaces clarifying_question to the user

Sets clarifying_question to the consolidated prompt so the Chainlit UI
layer can surface it via LangGraph's interrupt mechanism.
Clears missing_inputs and the original clarifying_question after processing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState


def prompt_user(state: "OrchestratorState") -> "OrchestratorState":
    clarifying_question = state.get("clarifying_question")
    missing_inputs = state.get("missing_inputs", [])

    # ── Case 1: missing inputs — consolidate into a single prompt ─────────────
    if missing_inputs:
        lines = ["I need the following information to proceed:\n"]
        for i, item in enumerate(missing_inputs, start=1):
            if isinstance(item, dict):
                name = item.get("name") or item.get("field") or item.get("key", f"input_{i}")
                description = item.get("description") or item.get("reason", "")
                example = item.get("example", "")
                line = f"{i}. **{name}**"
                if description:
                    line += f": {description}"
                if example:
                    line += f" (example: `{example}`)"
                lines.append(line)
            else:
                lines.append(f"{i}. {item}")

        consolidated_prompt = "\n".join(lines)
        return {
            **state,
            "clarifying_question": consolidated_prompt,
            "missing_inputs": [],
        }

    # ── Case 2: clarifying question already set ───────────────────────────────
    if clarifying_question:
        # Store the question as the pending prompt; clear it to avoid infinite loops
        # The raw_request is updated to include context so re-classification works
        pending_prompt = clarifying_question
        return {
            **state,
            "clarifying_question": pending_prompt,
            "missing_inputs": [],
        }

    # ── No action needed ──────────────────────────────────────────────────────
    return state
