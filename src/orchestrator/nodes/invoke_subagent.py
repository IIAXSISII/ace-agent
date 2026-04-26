"""
invoke_subagent node — selects and invokes a sub-agent for the current plan step.

Safety checks (hop limit, cycle detection, token budget) run first.
Then performs two-phase capability matching against subagent-registry,
invokes the selected agent with a 120s timeout, and updates state.
"""
from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import TYPE_CHECKING, Optional, Tuple

from src.storage.dynamodb import query

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

HOP_LIMIT = 10
INVOCATION_TIMEOUT_SECONDS = 120


def _check_safety_limits(state: "OrchestratorState") -> Tuple[bool, Optional[dict]]:
    """
    Returns (is_safe, error_dict).
    is_safe=False means execution should halt and route to aggregate_results.
    """
    hop_count = state.get("hop_count", 0)
    if hop_count >= HOP_LIMIT:
        return False, {
            "type": "hop_limit_exceeded",
            "message": f"Execution halted: maximum hop limit of {HOP_LIMIT} reached (hop_count={hop_count}).",
        }

    # Cycle detection: check if (agent_id, inputs_hash) already in visited_steps
    execution_plan = state.get("execution_plan", [])
    current_step_index = state.get("current_step_index", 0)
    current_step = execution_plan[current_step_index] if current_step_index < len(execution_plan) else {}
    agent_id = current_step.get("agent_id", "")
    tool_inputs = current_step.get("tool_inputs", {})
    inputs_hash = hashlib.sha256(json.dumps(tool_inputs, sort_keys=True).encode()).hexdigest()[:16]
    step_key = f"{agent_id}:{inputs_hash}"
    visited_steps = state.get("visited_steps", [])
    if step_key in visited_steps:
        return False, {
            "type": "cycle_detected",
            "message": f"Execution halted: cycle detected for agent '{agent_id}' with identical inputs (key={step_key}).",
        }

    token_budget_used = state.get("token_budget_used", 0)
    token_budget_limit = state.get("token_budget_limit", 0)
    if token_budget_limit > 0 and token_budget_used >= token_budget_limit:
        return False, {
            "type": "token_budget_exceeded",
            "message": f"Execution halted: token budget exceeded (used={token_budget_used}, limit={token_budget_limit}).",
        }

    return True, None


def _match_agent(agents: list, required_capability: str) -> Optional[dict]:
    """
    Two-phase capability match:
      Phase 1: agents already filtered by category (caller's responsibility)
      Phase 2: score by word overlap between required_capability and capabilityDescriptor
    """
    best = None
    best_score = -1
    req_words = set(required_capability.lower().split())
    for agent in agents:
        desc_words = set(agent.get("capabilityDescriptor", "").lower().split())
        score = len(req_words & desc_words)
        if score > best_score:
            best_score = score
            best = agent
    return best


def _invoke_with_timeout(agent, task: str, context_window: list, tool_inputs: dict) -> dict:
    """Invoke agent.invoke() with a 120s timeout using ThreadPoolExecutor."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(agent.invoke, task, context_window, tool_inputs)
        try:
            return future.result(timeout=INVOCATION_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            return {
                "result": None,
                "confidence_score": 0.0,
                "sources": [],
                "error": f"Sub-agent invocation timed out after {INVOCATION_TIMEOUT_SECONDS}s",
            }


def invoke_subagent(state: "OrchestratorState") -> "OrchestratorState":
    # ── Safety checks ─────────────────────────────────────────────────────────
    is_safe, error = _check_safety_limits(state)
    if not is_safe:
        return {**state, "error": error}

    execution_plan = state.get("execution_plan", [])
    current_step_index = state.get("current_step_index", 0)
    step = execution_plan[current_step_index] if current_step_index < len(execution_plan) else {}

    category = step.get("expected_category", "")
    required_capability = step.get("required_capability", "")
    tool_name = step.get("tool_name", "")
    tool_inputs = step.get("tool_inputs", {})
    description = step.get("description", tool_name)

    # ── Phase 1: filter registry by category ─────────────────────────────────
    agents = query(
        "subagent-registry",
        "category = :cat",
        {":cat": category},
    )
    active_agents = [
        a for a in agents
        if a.get("status") == "ACTIVE" and a.get("healthStatus") == "HEALTHY"
    ]

    # ── Phase 2: capability match ─────────────────────────────────────────────
    selected_agent_meta = _match_agent(active_agents, required_capability) if active_agents else None

    # ── Invoke agent ──────────────────────────────────────────────────────────
    context_window = state.get("context_window", [])

    use_mock = os.getenv("MOCK_STORAGE", "").lower() == "true"
    gateway_endpoint = os.getenv("AGENTCORE_GATEWAY_ENDPOINT", "")

    if use_mock or not gateway_endpoint:
        from src.agents.mock.agent import MockSubAgent
        agent = MockSubAgent()
        result = _invoke_with_timeout(agent, description, context_window, tool_inputs)
    else:
        # HTTP invocation via AgentCore Gateway
        import urllib.request
        payload = json.dumps({
            "task": description,
            "context_window": [str(doc) for doc in context_window],
            "tool_inputs": tool_inputs,
        }).encode()
        req = urllib.request.Request(
            gateway_endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            def _http_call():
                with urllib.request.urlopen(req, timeout=INVOCATION_TIMEOUT_SECONDS) as resp:
                    return json.loads(resp.read())
            future = executor.submit(_http_call)
            try:
                result = future.result(timeout=INVOCATION_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                result = {
                    "result": None,
                    "confidence_score": 0.0,
                    "sources": [],
                    "error": f"Sub-agent invocation timed out after {INVOCATION_TIMEOUT_SECONDS}s",
                }

    # ── Track hop_count and visited_steps ─────────────────────────────────────
    agent_id = selected_agent_meta.get("agentId", step.get("agent_id", "unknown")) if selected_agent_meta else step.get("agent_id", "unknown")
    inputs_hash = hashlib.sha256(json.dumps(tool_inputs, sort_keys=True).encode()).hexdigest()[:16]
    step_key = f"{agent_id}:{inputs_hash}"

    new_hop_count = state.get("hop_count", 0) + 1
    new_visited = list(state.get("visited_steps", [])) + [step_key]

    # ── Update last step_result with agent output ─────────────────────────────
    step_results = list(state.get("step_results", []))
    if step_results:
        last = dict(step_results[-1])
        last["agent_result"] = result
        last["agent_id"] = agent_id
        last["tool_name"] = tool_name
        step_results[-1] = last

    # ── Update context_window with agent output ───────────────────────────────
    new_context = list(context_window)
    if result.get("result"):
        new_context.append({
            "type": "agent_output",
            "step_index": current_step_index,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "content": result["result"],
            "confidence_score": result.get("confidence_score", 0.0),
        })

    return {
        **state,
        "hop_count": new_hop_count,
        "visited_steps": new_visited,
        "step_results": step_results,
        "context_window": new_context,
    }
