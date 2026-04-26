"""
Integration tests for full graph runs — task 14.4.
Feature: feature-01-core-orchestrator

Tests compile the graph with MemorySaver and mock all LLM / storage calls.
Scenarios:
  (a) happy path  — request → classify → plan → execute → aggregate → log
  (b) low-confidence — classify routes to prompt_user
  (c) missing-inputs — detect_missing_inputs blocks execution
  (d) hop-limit — graph halts at 10 hops
  (e) retry path — validate_step_post retries up to 2× then escalates
"""
from __future__ import annotations

import json
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ── Environment flags (must be set before any src import) ─────────────────────
os.environ["MOCK_STORAGE"] = "true"
os.environ["MOCK_PROMPTS"] = "true"

# ── Stub heavy dependencies that are not installed in the test venv ───────────
# Pattern mirrors tests/unit/nodes/test_nodes_task14_1.py

if "langchain_aws" not in sys.modules:
    _stub_lc_aws = ModuleType("langchain_aws")
    _stub_lc_aws.ChatBedrock = MagicMock()  # type: ignore[attr-defined]
    _stub_lc_aws.AmazonKnowledgeBasesRetriever = MagicMock()  # type: ignore[attr-defined]
    sys.modules["langchain_aws"] = _stub_lc_aws

# langgraph.checkpoint.memory is a real installed package — no stub needed.
# But langgraph_checkpoint_aws is not installed; stub it so memory.py import works.
if "langgraph_checkpoint_aws" not in sys.modules:
    _stub_lgcaws = ModuleType("langgraph_checkpoint_aws")
    _stub_lgcaws.AgentCoreMemorySaver = MagicMock()  # type: ignore[attr-defined]
    sys.modules["langgraph_checkpoint_aws"] = _stub_lgcaws

# Stub opentelemetry extensions used by otel.py (imported transitively via main.py)
for _mod in [
    "opentelemetry.sdk.extension.aws.trace",
    "opentelemetry.propagator.aws_xray",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
]:
    if _mod not in sys.modules:
        _s = ModuleType(_mod)
        _s.AwsXRayIdGenerator = MagicMock()  # type: ignore[attr-defined]
        _s.AwsXRayPropagator = MagicMock()  # type: ignore[attr-defined]
        _s.OTLPSpanExporter = MagicMock()  # type: ignore[attr-defined]
        sys.modules[_mod] = _s

# Stub langfuse so observability/langfuse.py doesn't fail
if "langfuse" not in sys.modules:
    _stub_lf = ModuleType("langfuse")
    sys.modules["langfuse"] = _stub_lf
if "langfuse.langchain" not in sys.modules:
    _stub_lf_lc = ModuleType("langfuse.langchain")
    _stub_lf_lc.CallbackHandler = MagicMock()  # type: ignore[attr-defined]
    sys.modules["langfuse.langchain"] = _stub_lf_lc

# Stub chainlit so ui imports don't fail if transitively pulled in
if "chainlit" not in sys.modules:
    _stub_cl = ModuleType("chainlit")
    sys.modules["chainlit"] = _stub_cl

# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_response(payload: dict) -> MagicMock:
    """Return a mock that looks like a ChatBedrock response."""
    mock = MagicMock()
    mock.content = json.dumps(payload)
    return mock


def _base_initial_state(**overrides) -> dict:
    """Minimal initial OrchestratorState for graph invocation."""
    state = {
        "raw_request": "investigate high CPU on prod EC2",
        "task_category": None,
        "entities": {},
        "confidence_score": 0.0,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 50_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "integ-test-session",
        "user_id": "test-user",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    state.update(overrides)
    return state


def _make_plan_step(
    step_index: int = 0,
    category: str = "monitoring_query",
    tool_name: str = "get_metric_statistics",
    confidence_score: float = 0.9,
) -> dict:
    return {
        "step_index": step_index,
        "description": f"Step {step_index}: query metrics",
        "expected_category": category,
        "required_capability": "query metrics",
        "agent_id": None,
        "tool_name": tool_name,
        "tool_inputs": {"namespace": "AWS/EC2"},
        "expected_output_schema": {},
        "confidence_score": confidence_score,
        "is_flagged": confidence_score < 0.75,
        "flag_rationale": None,
        "requires_approval": False,
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def compiled_graph():
    """
    Build and compile the graph with a fresh MemorySaver for each test.
    We patch get_checkpointer() to always return a new MemorySaver so tests
    are fully isolated.
    """
    from langgraph.checkpoint.memory import MemorySaver
    from src.orchestrator.graph import build_graph

    with patch("src.orchestrator.memory.get_checkpointer", return_value=MemorySaver()):
        graph = build_graph()
    return graph


@pytest.fixture()
def compiled_graph_interrupt_after_prompt():
    """
    Graph compiled with interrupt_after=["prompt_user"] so tests for the
    low-confidence and missing-inputs paths can assert on state without the
    graph looping back to classify_request indefinitely.
    """
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import StateGraph, END
    from src.orchestrator.graph import OrchestratorState
    from src.orchestrator.nodes.classify_request import classify_request
    from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
    from src.orchestrator.nodes.detect_missing_inputs import detect_missing_inputs
    from src.orchestrator.nodes.prompt_user import prompt_user
    from src.orchestrator.nodes.generate_plan import generate_plan
    from src.orchestrator.nodes.present_plan import present_plan
    from src.orchestrator.nodes.validate_step_pre import validate_step_pre
    from src.orchestrator.nodes.invoke_subagent import invoke_subagent
    from src.orchestrator.nodes.validate_step_post import validate_step_post
    from src.orchestrator.nodes.aggregate_results import aggregate_results
    from src.orchestrator.nodes.scan_output_guardrails import scan_output_guardrails
    from src.orchestrator.nodes.write_execution_log import write_execution_log
    from src.orchestrator.graph import (
        _route_classify_request,
        _route_detect_missing_inputs,
        _route_present_plan,
        _route_validate_step_pre,
        _route_validate_step_post,
    )

    graph = StateGraph(OrchestratorState)
    graph.add_node("classify_request", classify_request)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("detect_missing_inputs", detect_missing_inputs)
    graph.add_node("prompt_user", prompt_user)
    graph.add_node("generate_plan", generate_plan)
    graph.add_node("present_plan", present_plan)
    graph.add_node("validate_step_pre", validate_step_pre)
    graph.add_node("invoke_subagent", invoke_subagent)
    graph.add_node("validate_step_post", validate_step_post)
    graph.add_node("aggregate_results", aggregate_results)
    graph.add_node("scan_output_guardrails", scan_output_guardrails)
    graph.add_node("write_execution_log", write_execution_log)

    graph.set_entry_point("classify_request")
    graph.add_conditional_edges(
        "classify_request", _route_classify_request,
        {"retrieve_knowledge": "retrieve_knowledge", "prompt_user": "prompt_user"},
    )
    graph.add_conditional_edges(
        "prompt_user",
        lambda state: "classify_request",
        {"classify_request": "classify_request"},
    )
    graph.add_edge("retrieve_knowledge", "detect_missing_inputs")
    graph.add_conditional_edges(
        "detect_missing_inputs", _route_detect_missing_inputs,
        {"generate_plan": "generate_plan", "prompt_user": "prompt_user"},
    )
    graph.add_edge("generate_plan", "present_plan")
    graph.add_conditional_edges(
        "present_plan", _route_present_plan,
        {"validate_step_pre": "validate_step_pre", "generate_plan": "generate_plan"},
    )
    graph.add_conditional_edges(
        "validate_step_pre", _route_validate_step_pre,
        {"invoke_subagent": "invoke_subagent", "aggregate_results": "aggregate_results"},
    )
    graph.add_edge("invoke_subagent", "validate_step_post")
    graph.add_conditional_edges(
        "validate_step_post", _route_validate_step_post,
        {"validate_step_pre": "validate_step_pre", "aggregate_results": "aggregate_results",
         "invoke_subagent": "invoke_subagent"},
    )
    graph.add_edge("aggregate_results", "scan_output_guardrails")
    graph.add_edge("scan_output_guardrails", "write_execution_log")
    graph.add_edge("write_execution_log", END)

    return graph.compile(
        checkpointer=MemorySaver(),
        interrupt_after=["prompt_user"],
    )


@pytest.fixture()
def graph_config():
    """LangGraph config dict with a unique thread_id per test."""
    import uuid
    return {"configurable": {"thread_id": str(uuid.uuid4())}}


# ── (a) Happy path ────────────────────────────────────────────────────────────

class TestHappyPath:
    """
    (a) Happy path: high-confidence classification → no missing inputs →
        plan generated → step executed → results aggregated → log written.
    """

    def test_happy_path_final_response_not_none(self, compiled_graph, graph_config):
        """Final response must be set after a successful full run."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {"service": "EC2"},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state()
            result = compiled_graph.invoke(initial, config=graph_config)

        assert result["final_response"] is not None
        assert len(result["final_response"]) > 0

    def test_happy_path_citations_non_empty(self, compiled_graph, graph_config):
        """Citations must be populated when KB fixture documents are used."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {"service": "EC2"},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state()
            result = compiled_graph.invoke(initial, config=graph_config)

        # retrieve_knowledge adds fixture docs → aggregate_results builds citations
        assert isinstance(result["citations"], list)
        assert len(result["citations"]) > 0

    def test_happy_path_execution_log_written(self, compiled_graph, graph_config):
        """write_execution_log must call put_item at least once."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {"service": "EC2"},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan, \
             patch("src.orchestrator.nodes.write_execution_log.put_item") as mock_put:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state()
            compiled_graph.invoke(initial, config=graph_config)

        # put_item is called by write_execution_log for each completed step
        assert mock_put.called

    def test_happy_path_no_error_in_final_state(self, compiled_graph, graph_config):
        """Error field must be None on a successful run."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.95,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state()
            result = compiled_graph.invoke(initial, config=graph_config)

        assert result.get("error") is None


# ── (b) Low-confidence path ───────────────────────────────────────────────────

class TestLowConfidencePath:
    """
    (b) Low-confidence: classify_request returns confidence < 0.7 →
        graph routes to prompt_user → clarifying_question is set.

    Uses compiled_graph_interrupt_after_prompt so the graph halts after
    prompt_user runs once instead of looping back to classify_request.
    """

    def test_low_confidence_sets_clarifying_question(
        self, compiled_graph_interrupt_after_prompt, graph_config
    ):
        """When confidence < 0.7, clarifying_question must be set in final state."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.5,
            "clarifying_question": "Which service are you asking about?",
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify:
            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)

            initial = _base_initial_state()
            result = compiled_graph_interrupt_after_prompt.invoke(initial, config=graph_config)

        assert result["clarifying_question"] is not None
        assert len(result["clarifying_question"]) > 0

    def test_low_confidence_task_category_is_none(
        self, compiled_graph_interrupt_after_prompt, graph_config
    ):
        """Low confidence → task_category must be cleared to None."""
        classify_payload = {
            "task_category": "deployment",
            "entities": {},
            "confidence_score": 0.4,
            "clarifying_question": "What do you mean?",
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify:
            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)

            initial = _base_initial_state()
            result = compiled_graph_interrupt_after_prompt.invoke(initial, config=graph_config)

        # classify_request clears task_category when confidence < 0.7
        assert result["task_category"] is None

    def test_low_confidence_no_execution_plan_generated(
        self, compiled_graph_interrupt_after_prompt, graph_config
    ):
        """Low confidence → graph pauses at prompt_user; no plan should be generated."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.3,
            "clarifying_question": "Please clarify your request.",
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify:
            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)

            initial = _base_initial_state()
            result = compiled_graph_interrupt_after_prompt.invoke(initial, config=graph_config)

        # Graph paused at prompt_user — no plan steps should have been generated
        assert result["execution_plan"] == []

    def test_low_confidence_final_response_none(
        self, compiled_graph_interrupt_after_prompt, graph_config
    ):
        """Low confidence → graph pauses before aggregation; final_response stays None."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.6,
            "clarifying_question": "Which environment?",
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify:
            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)

            initial = _base_initial_state()
            result = compiled_graph_interrupt_after_prompt.invoke(initial, config=graph_config)

        assert result["final_response"] is None


# ── (c) Missing-inputs path ───────────────────────────────────────────────────

class TestMissingInputsPath:
    """
    (c) Missing inputs: detect_missing_inputs returns non-empty list →
        graph routes to prompt_user before executing any steps.

    Uses compiled_graph_interrupt_after_prompt so the graph halts after
    prompt_user runs once instead of looping back to classify_request.
    """

    def test_missing_inputs_routes_to_prompt_user(
        self, compiled_graph_interrupt_after_prompt, graph_config
    ):
        """When missing_inputs is non-empty, clarifying_question must be set."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {
            "missing_inputs": [
                {
                    "name": "time_range",
                    "description": "Time range for the query",
                    "type": "string",
                    "example": "last 1h",
                }
            ]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)

            initial = _base_initial_state()
            result = compiled_graph_interrupt_after_prompt.invoke(initial, config=graph_config)

        # prompt_user consolidates missing_inputs into clarifying_question
        assert result["clarifying_question"] is not None
        assert "time_range" in result["clarifying_question"]

    def test_missing_inputs_no_steps_executed(
        self, compiled_graph_interrupt_after_prompt, graph_config
    ):
        """When missing_inputs blocks execution, no step_results should be present."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {
            "missing_inputs": [
                {
                    "name": "service_name",
                    "description": "AWS service name",
                    "type": "string",
                    "example": "EC2",
                }
            ]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)

            initial = _base_initial_state()
            result = compiled_graph_interrupt_after_prompt.invoke(initial, config=graph_config)

        # No sub-agent steps should have been invoked
        assert result["step_results"] == []

    def test_missing_inputs_final_response_none(
        self, compiled_graph_interrupt_after_prompt, graph_config
    ):
        """Missing inputs block execution → final_response stays None."""
        classify_payload = {
            "task_category": "cost_analysis",
            "entities": {},
            "confidence_score": 0.85,
            "clarifying_question": None,
        }
        detect_payload = {
            "missing_inputs": [
                {
                    "name": "account_id",
                    "description": "AWS account ID",
                    "type": "string",
                    "example": "123456789012",
                }
            ]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)

            initial = _base_initial_state()
            result = compiled_graph_interrupt_after_prompt.invoke(initial, config=graph_config)

        assert result["final_response"] is None

    def test_missing_inputs_cleared_after_prompt_user(
        self, compiled_graph_interrupt_after_prompt, graph_config
    ):
        """prompt_user clears missing_inputs after consolidating them."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {
            "missing_inputs": [
                {
                    "name": "region",
                    "description": "AWS region",
                    "type": "string",
                    "example": "us-east-1",
                }
            ]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)

            initial = _base_initial_state()
            result = compiled_graph_interrupt_after_prompt.invoke(initial, config=graph_config)

        # prompt_user clears missing_inputs after building the consolidated prompt
        assert result["missing_inputs"] == []


# ── (d) Hop-limit path ────────────────────────────────────────────────────────

class TestHopLimitPath:
    """
    (d) Hop limit: initial state has hop_count=10 →
        invoke_subagent detects limit and sets error; graph routes to aggregate_results.
    """

    def test_hop_limit_sets_error(self, compiled_graph, graph_config):
        """When hop_count starts at 10, the error field must contain hop_limit_exceeded."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            # Start with hop_count already at the limit
            initial = _base_initial_state(hop_count=10)
            result = compiled_graph.invoke(initial, config=graph_config)

        assert result["error"] is not None
        error = result["error"]
        assert error.get("type") == "hop_limit_exceeded"

    def test_hop_limit_error_message_contains_hop_limit_exceeded(self, compiled_graph, graph_config):
        """Error message must mention hop_limit_exceeded."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state(hop_count=10)
            result = compiled_graph.invoke(initial, config=graph_config)

        error_msg = result["error"].get("message", "")
        assert "hop_limit_exceeded" in error_msg or "hop limit" in error_msg.lower()

    def test_hop_limit_still_produces_final_response(self, compiled_graph, graph_config):
        """Even when hop limit is hit, aggregate_results still runs and produces a response."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state(hop_count=10)
            result = compiled_graph.invoke(initial, config=graph_config)

        # aggregate_results runs even on error paths → final_response is set
        assert result["final_response"] is not None

    def test_hop_count_never_exceeds_10(self, compiled_graph, graph_config):
        """hop_count in final state must not exceed 10 (safety invariant)."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan:

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state(hop_count=9)
            result = compiled_graph.invoke(initial, config=graph_config)

        assert result.get("hop_count", 0) <= 10


# ── (e) Retry path ────────────────────────────────────────────────────────────

class TestRetryPath:
    """
    (e) Retry path: validate_step_post fails twice then succeeds (or exhausts retries) →
        retry_count reaches 2 before escalating to aggregate_results.
    """

    def test_retry_exhausted_routes_to_aggregate(self, compiled_graph, graph_config):
        """
        When validate_step_post always fails, retry_count reaches 2 and the graph
        escalates to aggregate_results (final_response is set).
        """
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        # MockSubAgent returns a result with confidence_score below the 0.7 threshold
        # so validate_step_post will always fail → retry_count increments each time
        low_confidence_result = {
            "result": "some output",
            "confidence_score": 0.3,  # below CONFIDENCE_THRESHOLD=0.7
            "sources": [],
            "error": None,
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan, \
             patch("src.agents.mock.agent.MockSubAgent.invoke", return_value=low_confidence_result):

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state()
            result = compiled_graph.invoke(initial, config=graph_config)

        # Graph must have escalated to aggregate_results → final_response is set
        assert result["final_response"] is not None

    def test_retry_count_reaches_2_before_escalation(self, compiled_graph, graph_config):
        """retry_count in the last step_result must be exactly 2 after exhausting retries."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        low_confidence_result = {
            "result": "output",
            "confidence_score": 0.2,
            "sources": [],
            "error": None,
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan, \
             patch("src.agents.mock.agent.MockSubAgent.invoke", return_value=low_confidence_result):

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state()
            result = compiled_graph.invoke(initial, config=graph_config)

        step_results = result.get("step_results", [])
        assert len(step_results) > 0
        last_result = step_results[-1]
        # After 2 retries the routing function escalates; retry_count must be 2
        assert last_result.get("retry_count") == 2

    def test_retry_post_validation_passed_false_on_exhaustion(self, compiled_graph, graph_config):
        """After retries are exhausted, post_validation_passed must be False."""
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        low_confidence_result = {
            "result": "output",
            "confidence_score": 0.1,
            "sources": [],
            "error": None,
        }

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan, \
             patch("src.agents.mock.agent.MockSubAgent.invoke", return_value=low_confidence_result):

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state()
            result = compiled_graph.invoke(initial, config=graph_config)

        step_results = result.get("step_results", [])
        assert len(step_results) > 0
        last_result = step_results[-1]
        assert last_result.get("post_validation_passed") is False

    def test_retry_succeeds_on_second_attempt(self, compiled_graph, graph_config):
        """
        When the mock agent returns low confidence on the first call then
        high confidence on the 2nd (first retry), the step should ultimately pass.

        The routing logic retries when retry_count < 2, so:
          - 1st invoke: fails → retry_count=1
          - 2nd invoke (retry): succeeds → post_validation_passed=True
        """
        classify_payload = {
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        }
        detect_payload = {"missing_inputs": []}
        plan_payload = {
            "execution_plan": [_make_plan_step(
                category="monitoring_query",
                tool_name="get_metric_statistics",
            )]
        }

        # Use a mutable counter so the closure works correctly across threads
        call_count = {"n": 0}

        def _side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: low confidence → triggers retry
                return {"result": "output", "confidence_score": 0.2, "sources": [], "error": None}
            # Second call (retry): high confidence → passes
            return {"result": "final output", "confidence_score": 0.9, "sources": [], "error": None}

        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan, \
             patch("src.agents.mock.agent.MockSubAgent.invoke", side_effect=_side_effect):

            MockClassify.return_value.invoke.return_value = _llm_response(classify_payload)
            MockDetect.return_value.invoke.return_value = _llm_response(detect_payload)
            MockPlan.return_value.invoke.return_value = _llm_response(plan_payload)

            initial = _base_initial_state()
            result = compiled_graph.invoke(initial, config=graph_config)

        # Graph should complete successfully with a final response
        assert result["final_response"] is not None
        step_results = result.get("step_results", [])
        assert len(step_results) > 0
        last_result = step_results[-1]
        assert last_result.get("post_validation_passed") is True
        # The mock was called twice: 1 failure + 1 success
        assert call_count["n"] == 2
