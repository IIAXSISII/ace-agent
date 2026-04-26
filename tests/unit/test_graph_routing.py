"""
Unit tests for all graph routing functions in src/orchestrator/graph.py.

Tests assert the correct node name is returned for every branch condition
in each of the five routing functions:
  - _route_classify_request
  - _route_detect_missing_inputs
  - _route_present_plan
  - _route_validate_step_pre
  - _route_validate_step_post
"""

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("MOCK_STORAGE", "true")
os.environ.setdefault("MOCK_PROMPTS", "true")

# Stub out langchain_aws before any node module is imported (not installed in test venv)
if "langchain_aws" not in sys.modules:
    _stub = ModuleType("langchain_aws")
    _stub.ChatBedrock = MagicMock()  # type: ignore[attr-defined]
    sys.modules["langchain_aws"] = _stub

from src.orchestrator.graph import (
    OrchestratorState,
    _route_classify_request,
    _route_detect_missing_inputs,
    _route_present_plan,
    _route_validate_step_pre,
    _route_validate_step_post,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def minimal_state(**overrides) -> OrchestratorState:
    """Return a minimal valid OrchestratorState with sensible defaults."""
    base: OrchestratorState = {
        "raw_request": "test request",
        "task_category": None,
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 50000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "test-session",
        "user_id": "test-user",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    base.update(overrides)
    return base


# ── _route_classify_request ───────────────────────────────────────────────────

class TestRouteClassifyRequest:
    def test_high_confidence_routes_to_retrieve_knowledge(self):
        state = minimal_state(confidence_score=0.7)
        assert _route_classify_request(state) == "retrieve_knowledge"

    def test_confidence_above_threshold_routes_to_retrieve_knowledge(self):
        state = minimal_state(confidence_score=0.95)
        assert _route_classify_request(state) == "retrieve_knowledge"

    def test_confidence_exactly_at_threshold_routes_to_retrieve_knowledge(self):
        # Boundary: 0.7 is the minimum for "high confidence"
        state = minimal_state(confidence_score=0.7)
        assert _route_classify_request(state) == "retrieve_knowledge"

    def test_low_confidence_routes_to_prompt_user(self):
        state = minimal_state(confidence_score=0.5)
        assert _route_classify_request(state) == "prompt_user"

    def test_confidence_just_below_threshold_routes_to_prompt_user(self):
        state = minimal_state(confidence_score=0.69)
        assert _route_classify_request(state) == "prompt_user"

    def test_zero_confidence_routes_to_prompt_user(self):
        state = minimal_state(confidence_score=0.0)
        assert _route_classify_request(state) == "prompt_user"

    def test_missing_confidence_score_defaults_to_prompt_user(self):
        # When confidence_score key is absent, default 0.0 < 0.7 → prompt_user
        state = minimal_state()
        del state["confidence_score"]
        assert _route_classify_request(state) == "prompt_user"


# ── _route_detect_missing_inputs ──────────────────────────────────────────────

class TestRouteDetectMissingInputs:
    def test_no_missing_inputs_routes_to_generate_plan(self):
        state = minimal_state(missing_inputs=[])
        assert _route_detect_missing_inputs(state) == "generate_plan"

    def test_with_missing_inputs_routes_to_prompt_user(self):
        # In F01, _route_detect_missing_inputs always routes to generate_plan
        # regardless of missing_inputs (no real interrupt mechanism yet)
        state = minimal_state(missing_inputs=[{"name": "environment", "type": "str"}])
        assert _route_detect_missing_inputs(state) == "generate_plan"

    def test_multiple_missing_inputs_routes_to_prompt_user(self):
        # In F01, always routes to generate_plan
        state = minimal_state(missing_inputs=[
            {"name": "environment", "type": "str"},
            {"name": "region", "type": "str"},
        ])
        assert _route_detect_missing_inputs(state) == "generate_plan"

    def test_missing_inputs_key_absent_routes_to_generate_plan(self):
        # Falsy default (None / missing) → generate_plan
        state = minimal_state()
        del state["missing_inputs"]
        assert _route_detect_missing_inputs(state) == "generate_plan"


# ── _route_present_plan ───────────────────────────────────────────────────────

class TestRoutePresentPlan:
    def test_pending_approval_true_routes_to_validate_step_pre(self):
        # pending_approval=True means user requested modification → regenerate plan
        # pending_approval=False means auto-approved → proceed to validate_step_pre
        # NOTE: In F01, present_plan sets pending_approval=False (auto-approve)
        # so True means "user wants to modify" → generate_plan
        state = minimal_state(pending_approval=True)
        assert _route_present_plan(state) == "generate_plan"

    def test_pending_approval_false_routes_to_generate_plan(self):
        # False = auto-approved → proceed to execution
        state = minimal_state(pending_approval=False)
        assert _route_present_plan(state) == "validate_step_pre"

    def test_pending_approval_absent_routes_to_generate_plan(self):
        # Absent defaults to False → auto-approved → validate_step_pre
        state = minimal_state()
        del state["pending_approval"]
        assert _route_present_plan(state) == "validate_step_pre"


# ── _route_validate_step_pre ──────────────────────────────────────────────────

class TestRouteValidateStepPre:
    def test_no_step_results_routes_to_invoke_subagent(self):
        state = minimal_state(step_results=[])
        assert _route_validate_step_pre(state) == "invoke_subagent"

    def test_last_step_not_failed_routes_to_invoke_subagent(self):
        state = minimal_state(step_results=[{"pre_validation_failed": False}])
        assert _route_validate_step_pre(state) == "invoke_subagent"

    def test_last_step_pre_validation_failed_routes_to_aggregate_results(self):
        state = minimal_state(step_results=[{"pre_validation_failed": True}])
        assert _route_validate_step_pre(state) == "aggregate_results"

    def test_only_last_step_result_is_checked(self):
        # First step failed, last step passed → should route to invoke_subagent
        state = minimal_state(step_results=[
            {"pre_validation_failed": True},
            {"pre_validation_failed": False},
        ])
        assert _route_validate_step_pre(state) == "invoke_subagent"

    def test_step_results_key_absent_routes_to_invoke_subagent(self):
        state = minimal_state()
        del state["step_results"]
        assert _route_validate_step_pre(state) == "invoke_subagent"


# ── _route_validate_step_post ─────────────────────────────────────────────────

class TestRouteValidateStepPost:
    # ── Pass branch ──────────────────────────────────────────────────────────

    def test_pass_with_more_steps_routes_to_validate_step_pre(self):
        state = minimal_state(
            execution_plan=[{"step_index": 0}, {"step_index": 1}],
            current_step_index=0,
            step_results=[{"post_validation_passed": True, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "validate_step_pre"

    def test_pass_on_last_step_routes_to_aggregate_results(self):
        state = minimal_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": True, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"

    def test_pass_with_empty_plan_routes_to_aggregate_results(self):
        state = minimal_state(
            execution_plan=[],
            current_step_index=0,
            step_results=[{"post_validation_passed": True, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"

    # ── Fail + retry branch ──────────────────────────────────────────────────

    def test_fail_with_zero_retries_routes_to_invoke_subagent(self):
        state = minimal_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "invoke_subagent"

    def test_fail_with_one_retry_routes_to_invoke_subagent(self):
        state = minimal_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False, "retry_count": 1}],
        )
        assert _route_validate_step_post(state) == "invoke_subagent"

    def test_fail_with_two_retries_exhausted_routes_to_aggregate_results(self):
        # retry_count == 2 means retries are exhausted → escalate
        state = minimal_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False, "retry_count": 2}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"

    def test_fail_with_retry_count_above_limit_routes_to_aggregate_results(self):
        state = minimal_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False, "retry_count": 5}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"

    # ── Edge cases ───────────────────────────────────────────────────────────

    def test_no_step_results_defaults_to_aggregate_results(self):
        # No last result → post_validation_passed is falsy, retry_count defaults to 0
        # retry_count 0 < 2 → invoke_subagent
        state = minimal_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[],
        )
        assert _route_validate_step_post(state) == "invoke_subagent"

    def test_only_last_step_result_is_checked_for_post_validation(self):
        # Earlier step failed, last step passed with more steps remaining
        state = minimal_state(
            execution_plan=[{"step_index": 0}, {"step_index": 1}, {"step_index": 2}],
            current_step_index=1,
            step_results=[
                {"post_validation_passed": False, "retry_count": 2},
                {"post_validation_passed": True, "retry_count": 0},
            ],
        )
        assert _route_validate_step_post(state) == "validate_step_pre"
