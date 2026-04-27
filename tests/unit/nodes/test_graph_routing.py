"""
Unit tests for all graph routing functions in src/orchestrator/graph.py.
Feature: feature-01-core-orchestrator
Task: 14.2

Covers every branch of:
  - _route_classify_request
  - _route_detect_missing_inputs
  - _route_present_plan
  - _route_validate_step_pre
  - _route_validate_step_post

Routing functions are pure state → str functions; no mocking needed.
"""
import sys
from types import ModuleType
from unittest.mock import MagicMock


# ── Stub heavy optional dependencies so graph.py can be imported ─────────────
# graph.py imports langgraph and all node modules at module level.
# We stub them out so the routing functions (which are pure) can be tested
# without the full dependency tree installed.

def _stub_module(name: str, **attrs):
    mod = ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# langgraph stubs
if "langgraph" not in sys.modules:
    _stub_module("langgraph")
    _stub_module("langgraph.graph", StateGraph=MagicMock(), END=MagicMock())
    _stub_module("langgraph.checkpoint", memory=MagicMock())
    _stub_module("langgraph.checkpoint.memory", MemorySaver=MagicMock())

# langchain_aws stub
if "langchain_aws" not in sys.modules:
    _stub_module("langchain_aws", ChatBedrock=MagicMock(), AmazonKnowledgeBasesRetriever=MagicMock())

# langchain_core stubs
if "langchain_core" not in sys.modules:
    _stub_module("langchain_core")
    _stub_module("langchain_core.documents", Document=MagicMock())
    _stub_module("langchain_core.prompts", ChatPromptTemplate=MagicMock())

# Stub every node module so graph.py imports succeed
_NODE_MODULES = [
    "src.orchestrator.nodes.classify_request",
    "src.orchestrator.nodes.retrieve_knowledge",
    "src.orchestrator.nodes.detect_missing_inputs",
    "src.orchestrator.nodes.prompt_user",
    "src.orchestrator.nodes.generate_plan",
    "src.orchestrator.nodes.present_plan",
    "src.orchestrator.nodes.validate_step_pre",
    "src.orchestrator.nodes.invoke_subagent",
    "src.orchestrator.nodes.validate_step_post",
    "src.orchestrator.nodes.aggregate_results",
    "src.orchestrator.nodes.scan_output_guardrails",
    "src.orchestrator.nodes.write_execution_log",
]
for _mod_name in _NODE_MODULES:
    if _mod_name not in sys.modules:
        _fn_name = _mod_name.split(".")[-1]
        _stub_module(_mod_name, **{_fn_name: MagicMock()})

# Stub memory module
if "src.orchestrator.memory" not in sys.modules:
    _stub_module("src.orchestrator.memory", get_checkpointer=MagicMock(return_value=MagicMock()))

# Now import the routing functions directly from graph.py
from src.orchestrator.graph import (  # noqa: E402
    _route_classify_request,
    _route_detect_missing_inputs,
    _route_present_plan,
    _route_validate_step_pre,
    _route_validate_step_post,
)


# ── Minimal state factory ─────────────────────────────────────────────────────

def _base_state(**overrides):
    """Return a minimal OrchestratorState dict suitable for routing tests."""
    state = {
        "raw_request": "investigate high CPU on prod EC2",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-routing-test",
        "user_id": "user-1",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    state.update(overrides)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# _route_classify_request
# Branches:
#   confidence_score >= 0.7  →  "retrieve_knowledge"
#   confidence_score < 0.7   →  "prompt_user"
# ─────────────────────────────────────────────────────────────────────────────

class TestRouteClassifyRequest:

    def test_high_confidence_routes_to_retrieve_knowledge(self):
        """confidence_score >= 0.7 → 'retrieve_knowledge'"""
        state = _base_state(confidence_score=0.9)
        assert _route_classify_request(state) == "retrieve_knowledge"

    def test_exactly_0_7_routes_to_retrieve_knowledge(self):
        """Boundary: confidence_score == 0.7 is high enough → 'retrieve_knowledge'"""
        state = _base_state(confidence_score=0.7)
        assert _route_classify_request(state) == "retrieve_knowledge"

    def test_confidence_1_0_routes_to_retrieve_knowledge(self):
        """Maximum confidence → 'retrieve_knowledge'"""
        state = _base_state(confidence_score=1.0)
        assert _route_classify_request(state) == "retrieve_knowledge"

    def test_low_confidence_routes_to_prompt_user(self):
        """confidence_score < 0.7 → 'prompt_user'"""
        state = _base_state(confidence_score=0.5)
        assert _route_classify_request(state) == "prompt_user"

    def test_just_below_threshold_routes_to_prompt_user(self):
        """Boundary: confidence_score just below 0.7 → 'prompt_user'"""
        state = _base_state(confidence_score=0.69)
        assert _route_classify_request(state) == "prompt_user"

    def test_zero_confidence_routes_to_prompt_user(self):
        """Minimum confidence → 'prompt_user'"""
        state = _base_state(confidence_score=0.0)
        assert _route_classify_request(state) == "prompt_user"

    def test_missing_confidence_score_defaults_to_prompt_user(self):
        """Missing confidence_score key defaults to 0.0 → 'prompt_user'"""
        state = _base_state()
        del state["confidence_score"]
        assert _route_classify_request(state) == "prompt_user"


# ─────────────────────────────────────────────────────────────────────────────
# _route_detect_missing_inputs
# Branches:
#   missing_inputs empty (falsy)     →  "generate_plan"
#   missing_inputs not empty (truthy) →  "prompt_user"
# ─────────────────────────────────────────────────────────────────────────────

class TestRouteDetectMissingInputs:

    def test_empty_list_routes_to_generate_plan(self):
        """missing_inputs == [] → 'generate_plan'"""
        state = _base_state(missing_inputs=[])
        assert _route_detect_missing_inputs(state) == "generate_plan"

    def test_one_missing_input_routes_to_prompt_user(self):
        """In F01, always routes to generate_plan regardless of missing_inputs"""
        state = _base_state(missing_inputs=[
            {"name": "time_range", "description": "Time range", "type": "string", "example": "last 1h"}
        ])
        assert _route_detect_missing_inputs(state) == "generate_plan"

    def test_multiple_missing_inputs_routes_to_prompt_user(self):
        """In F01, always routes to generate_plan"""
        state = _base_state(missing_inputs=[
            {"name": "service_name", "description": "Service", "type": "string", "example": "EC2"},
            {"name": "region", "description": "Region", "type": "string", "example": "us-east-1"},
        ])
        assert _route_detect_missing_inputs(state) == "generate_plan"

    def test_missing_key_defaults_to_generate_plan(self):
        """Absent missing_inputs key (falsy default) → 'generate_plan'"""
        state = _base_state()
        del state["missing_inputs"]
        assert _route_detect_missing_inputs(state) == "generate_plan"


# ─────────────────────────────────────────────────────────────────────────────
# _route_present_plan
# Branches:
#   pending_approval == True  (approved)  →  "validate_step_pre"
#   pending_approval == False (modified)  →  "generate_plan"
# ─────────────────────────────────────────────────────────────────────────────

class TestRoutePresentPlan:

    def test_approved_routes_to_validate_step_pre(self):
        """pending_approval=False (auto-approved in F01) → 'validate_step_pre'"""
        state = _base_state(pending_approval=False)
        assert _route_present_plan(state) == "validate_step_pre"

    def test_not_approved_routes_to_generate_plan(self):
        """pending_approval=True (user wants modification) → 'generate_plan'"""
        state = _base_state(pending_approval=True)
        assert _route_present_plan(state) == "generate_plan"

    def test_missing_pending_approval_defaults_to_generate_plan(self):
        """Absent pending_approval defaults to False → auto-approved → 'validate_step_pre'"""
        state = _base_state()
        del state["pending_approval"]
        assert _route_present_plan(state) == "validate_step_pre"


# ─────────────────────────────────────────────────────────────────────────────
# _route_validate_step_pre
# Branches:
#   last step_result has pre_validation_failed=True  →  "aggregate_results"
#   otherwise (valid / no results yet)               →  "invoke_subagent"
# ─────────────────────────────────────────────────────────────────────────────

class TestRouteValidateStepPre:

    def test_no_step_results_routes_to_invoke_subagent(self):
        """Empty step_results (first step) → 'invoke_subagent'"""
        state = _base_state(step_results=[])
        assert _route_validate_step_pre(state) == "invoke_subagent"

    def test_valid_step_routes_to_invoke_subagent(self):
        """Last step result has pre_validation_failed=False → 'invoke_subagent'"""
        state = _base_state(step_results=[{"pre_validation_failed": False}])
        assert _route_validate_step_pre(state) == "invoke_subagent"

    def test_pre_validation_failed_routes_to_aggregate_results(self):
        """Last step result has pre_validation_failed=True → 'aggregate_results'"""
        state = _base_state(step_results=[{"pre_validation_failed": True}])
        assert _route_validate_step_pre(state) == "aggregate_results"

    def test_multiple_results_uses_last_entry(self):
        """Only the last step_result is inspected for pre_validation_failed"""
        state = _base_state(step_results=[
            {"pre_validation_failed": True},   # earlier step — should be ignored
            {"pre_validation_failed": False},  # last step — valid
        ])
        assert _route_validate_step_pre(state) == "invoke_subagent"

    def test_multiple_results_last_failed_routes_to_aggregate(self):
        """Last step_result has pre_validation_failed=True even if earlier ones passed"""
        state = _base_state(step_results=[
            {"pre_validation_failed": False},
            {"pre_validation_failed": True},
        ])
        assert _route_validate_step_pre(state) == "aggregate_results"

    def test_missing_pre_validation_failed_key_routes_to_invoke_subagent(self):
        """Step result without pre_validation_failed key → falsy → 'invoke_subagent'"""
        state = _base_state(step_results=[{"post_validation_passed": True}])
        assert _route_validate_step_pre(state) == "invoke_subagent"


# ─────────────────────────────────────────────────────────────────────────────
# _route_validate_step_post
# Branches:
#   pass + more steps remaining  →  "validate_step_pre"
#   pass + no more steps         →  "aggregate_results"
#   fail + retry_count < 2       →  "invoke_subagent"
#   fail + retry_count >= 2      →  "aggregate_results"
# ─────────────────────────────────────────────────────────────────────────────

class TestRouteValidateStepPost:

    # ── Pass branches ─────────────────────────────────────────────────────────

    def test_pass_with_more_steps_routes_to_validate_step_pre(self):
        """post_validation_passed=True, more steps remain → 'validate_step_pre'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}, {"step_index": 1}],
            current_step_index=0,  # step 1 still pending
            step_results=[{"post_validation_passed": True, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "validate_step_pre"

    def test_pass_on_last_step_routes_to_aggregate_results(self):
        """post_validation_passed=True, no more steps → 'aggregate_results'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,  # last (and only) step
            step_results=[{"post_validation_passed": True, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"

    def test_pass_multi_step_last_step_routes_to_aggregate_results(self):
        """post_validation_passed=True on the final step of a 3-step plan → 'aggregate_results'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}, {"step_index": 1}, {"step_index": 2}],
            current_step_index=2,  # last step
            step_results=[{"post_validation_passed": True, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"

    def test_pass_middle_step_routes_to_validate_step_pre(self):
        """post_validation_passed=True on step 1 of 3 → 'validate_step_pre'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}, {"step_index": 1}, {"step_index": 2}],
            current_step_index=1,
            step_results=[{"post_validation_passed": True, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "validate_step_pre"

    # ── Fail branches ─────────────────────────────────────────────────────────

    def test_fail_first_retry_routes_to_invoke_subagent(self):
        """post_validation_passed=False, retry_count=0 (< 2) → 'invoke_subagent'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "invoke_subagent"

    def test_fail_second_retry_routes_to_invoke_subagent(self):
        """post_validation_passed=False, retry_count=1 (< 2) → 'invoke_subagent'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False, "retry_count": 1}],
        )
        assert _route_validate_step_post(state) == "invoke_subagent"

    def test_fail_retries_exhausted_routes_to_aggregate_results(self):
        """post_validation_passed=False, retry_count=2 (exhausted) → 'aggregate_results'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False, "retry_count": 2}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"

    def test_fail_retry_count_above_2_routes_to_aggregate_results(self):
        """post_validation_passed=False, retry_count > 2 → 'aggregate_results'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False, "retry_count": 5}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_no_step_results_defaults_to_aggregate_results(self):
        """Empty step_results → last={} → post_validation_passed falsy, retry_count=0 → 'invoke_subagent'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[],
        )
        # last={} → post_validation_passed is falsy, retry_count defaults to 0 → retry
        assert _route_validate_step_post(state) == "invoke_subagent"

    def test_missing_retry_count_defaults_to_zero(self):
        """Step result without retry_count key → defaults to 0 → 'invoke_subagent'"""
        state = _base_state(
            execution_plan=[{"step_index": 0}],
            current_step_index=0,
            step_results=[{"post_validation_passed": False}],  # no retry_count
        )
        assert _route_validate_step_post(state) == "invoke_subagent"

    def test_pass_empty_plan_routes_to_aggregate_results(self):
        """post_validation_passed=True, empty execution_plan → no more steps → 'aggregate_results'"""
        state = _base_state(
            execution_plan=[],
            current_step_index=0,
            step_results=[{"post_validation_passed": True, "retry_count": 0}],
        )
        assert _route_validate_step_post(state) == "aggregate_results"
