"""
Unit tests for invoke_subagent safety checks.
Feature: feature-01-core-orchestrator
Covers: Req 4.8 (hop limit), Req 4.9 (cycle detection), Req 4.10 (token budget)
"""
import hashlib
import json


from src.orchestrator.nodes.invoke_subagent import _check_safety_limits, invoke_subagent


def _base_state(**overrides):
    state = {
        "raw_request": "test",
        "task_category": None,
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [
            {
                "step_index": 0,
                "agent_id": "agent-a",
                "tool_name": "some_tool",
                "tool_inputs": {"key": "value"},
                "expected_output_schema": {},
                "confidence_score": 0.9,
                "is_flagged": False,
                "flag_rationale": None,
                "requires_approval": False,
                "description": "step",
                "expected_category": "monitoring_query",
                "required_capability": "metrics",
            }
        ],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-1",
        "user_id": "user-1",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    state.update(overrides)
    return state


# ── Hop limit ────────────────────────────────────────────────────────────────

class TestHopLimit:
    def test_safe_when_hop_count_below_limit(self):
        state = _base_state(hop_count=9)
        is_safe, error = _check_safety_limits(state)
        assert is_safe is True
        assert error is None

    def test_halts_when_hop_count_equals_limit(self):
        state = _base_state(hop_count=10)
        is_safe, error = _check_safety_limits(state)
        assert is_safe is False
        assert error["type"] == "hop_limit_exceeded"
        assert "10" in error["message"]

    def test_halts_when_hop_count_exceeds_limit(self):
        state = _base_state(hop_count=15)
        is_safe, error = _check_safety_limits(state)
        assert is_safe is False
        assert error["type"] == "hop_limit_exceeded"

    def test_invoke_subagent_sets_error_on_hop_limit(self):
        state = _base_state(hop_count=10)
        result = invoke_subagent(state)
        assert result["error"] is not None
        assert result["error"]["type"] == "hop_limit_exceeded"


# ── Cycle detection ──────────────────────────────────────────────────────────

def _step_key(agent_id: str, tool_inputs: dict) -> str:
    inputs_hash = hashlib.sha256(
        json.dumps(tool_inputs, sort_keys=True).encode()
    ).hexdigest()[:16]
    return f"{agent_id}:{inputs_hash}"


class TestCycleDetection:
    def test_safe_when_no_prior_visits(self):
        state = _base_state(visited_steps=[])
        is_safe, error = _check_safety_limits(state)
        assert is_safe is True

    def test_halts_when_same_agent_and_inputs_revisited(self):
        tool_inputs = {"key": "value"}
        key = _step_key("agent-a", tool_inputs)
        state = _base_state(visited_steps=[key])
        is_safe, error = _check_safety_limits(state)
        assert is_safe is False
        assert error["type"] == "cycle_detected"
        assert "agent-a" in error["message"]

    def test_safe_when_same_agent_different_inputs(self):
        key = _step_key("agent-a", {"key": "other"})
        state = _base_state(visited_steps=[key])
        is_safe, error = _check_safety_limits(state)
        assert is_safe is True

    def test_safe_when_different_agent_same_inputs(self):
        key = _step_key("agent-b", {"key": "value"})
        state = _base_state(visited_steps=[key])
        is_safe, error = _check_safety_limits(state)
        assert is_safe is True

    def test_invoke_subagent_sets_error_on_cycle(self):
        tool_inputs = {"key": "value"}
        key = _step_key("agent-a", tool_inputs)
        state = _base_state(visited_steps=[key])
        result = invoke_subagent(state)
        assert result["error"]["type"] == "cycle_detected"


# ── Token budget ─────────────────────────────────────────────────────────────

class TestTokenBudget:
    def test_safe_when_under_budget(self):
        state = _base_state(token_budget_used=50_000, token_budget_limit=100_000)
        is_safe, error = _check_safety_limits(state)
        assert is_safe is True

    def test_halts_when_budget_exactly_reached(self):
        state = _base_state(token_budget_used=100_000, token_budget_limit=100_000)
        is_safe, error = _check_safety_limits(state)
        assert is_safe is False
        assert error["type"] == "token_budget_exceeded"

    def test_halts_when_budget_exceeded(self):
        state = _base_state(token_budget_used=200_000, token_budget_limit=100_000)
        is_safe, error = _check_safety_limits(state)
        assert is_safe is False
        assert error["type"] == "token_budget_exceeded"
        assert "200000" in error["message"]
        assert "100000" in error["message"]

    def test_safe_when_budget_limit_is_zero(self):
        # limit=0 means no budget configured — should not halt
        state = _base_state(token_budget_used=0, token_budget_limit=0)
        is_safe, error = _check_safety_limits(state)
        assert is_safe is True

    def test_invoke_subagent_sets_error_on_budget_exceeded(self):
        state = _base_state(token_budget_used=100_000, token_budget_limit=100_000)
        result = invoke_subagent(state)
        assert result["error"]["type"] == "token_budget_exceeded"


# ── Priority ordering ────────────────────────────────────────────────────────

class TestSafetyPriority:
    def test_hop_limit_checked_before_cycle(self):
        """Hop limit takes priority over cycle detection."""
        tool_inputs = {"key": "value"}
        key = _step_key("agent-a", tool_inputs)
        state = _base_state(hop_count=10, visited_steps=[key])
        is_safe, error = _check_safety_limits(state)
        assert is_safe is False
        assert error["type"] == "hop_limit_exceeded"

    def test_safe_state_passes_all_checks(self):
        state = _base_state(hop_count=0, visited_steps=[], token_budget_used=0, token_budget_limit=100_000)
        is_safe, error = _check_safety_limits(state)
        assert is_safe is True
        assert error is None
