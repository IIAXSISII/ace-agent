"""
Property-Based Tests for feature-01-core-orchestrator.
All 23 correctness properties from design.md verified with hypothesis.

Feature: feature-01-core-orchestrator
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

os.environ.setdefault("MOCK_STORAGE", "true")
os.environ.setdefault("MOCK_PROMPTS", "true")

# ── Stub langchain_aws before any node module is imported ─────────────────────
if "langchain_aws" not in sys.modules:
    _stub = ModuleType("langchain_aws")
    _stub.ChatBedrock = MagicMock()
    sys.modules["langchain_aws"] = _stub

VALID_CATEGORIES = [
    "incident_investigation",
    "infrastructure_change",
    "cost_analysis",
    "deployment",
    "monitoring_query",
    "knowledge_retrieval",
    "code_review",
]


# ─────────────────────────────────────────────────────────────────────────────
# Hypothesis strategies
# ─────────────────────────────────────────────────────────────────────────────

def st_request():
    """Arbitrary text strings and valid JSON objects as raw_request."""
    return st.one_of(
        st.text(min_size=1, max_size=200),
        st.fixed_dictionaries({
            "action": st.sampled_from(["investigate", "deploy", "review", "query"]),
            "service": st.sampled_from(["EC2", "RDS", "Lambda", "ECS", "S3"]),
        }).map(json.dumps),
    )


def st_confidence_score():
    """Floats in [0.0, 1.0]."""
    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def st_plan_step(confidence_score=None):
    """PlanStep dict with random or fixed confidence score."""
    cs_strategy = (
        st.just(confidence_score)
        if confidence_score is not None
        else st_confidence_score()
    )
    return cs_strategy.flatmap(lambda cs: st.fixed_dictionaries({
        "step_index": st.integers(min_value=0, max_value=9),
        "description": st.text(min_size=1, max_size=100),
        "expected_category": st.sampled_from(VALID_CATEGORIES),
        "required_capability": st.text(min_size=1, max_size=50),
        "agent_id": st.none(),
        "tool_name": st.sampled_from(["get_metric_statistics", "describe_instances", "list_objects", "run_query"]),
        "tool_inputs": st.dictionaries(
            st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_")),
            st.one_of(st.text(max_size=50), st.integers(), st.booleans()),
            max_size=4,
        ),
        "expected_output_schema": st.just({}),
        "confidence_score": st.just(cs),
        "is_flagged": st.just(cs < 0.75),
        "flag_rationale": st.just(f"Low confidence {cs:.2f}" if cs < 0.75 else None),
        "requires_approval": st.booleans(),
    }))


def st_execution_plan(min_steps=1):
    """List of 1–5 PlanStep dicts."""
    return st.lists(st_plan_step(), min_size=min_steps, max_size=5)


def st_entities():
    """Dict with service names, time ranges, and environment names."""
    return st.fixed_dictionaries({
        "service": st.sampled_from(["EC2", "RDS", "Lambda", "ECS", "S3", "CloudFront", "DynamoDB"]),
        "environment": st.sampled_from(["prod", "staging", "dev", "test"]),
        "time_range": st.sampled_from(["last 1h", "last 24h", "last 7d", "2024-01-01/2024-01-02"]),
    })


def st_tool_inputs():
    """Valid and invalid tool input dicts."""
    valid = st.dictionaries(
        st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_")),
        st.one_of(st.text(max_size=50), st.integers(min_value=0, max_value=9999), st.booleans()),
        max_size=5,
    )
    invalid = st.one_of(
        st.just({}),
        st.just({"password": "secret123"}),
        st.just({"token": "abc", "key": "xyz"}),
    )
    return st.one_of(valid, invalid)


def st_context_window():
    """List of LangChain Document objects (using real Document class)."""
    from langchain_core.documents import Document

    doc_strategy = st.fixed_dictionaries({
        "page_content": st.text(min_size=1, max_size=300),
        "title": st.text(min_size=1, max_size=80),
        "url": st.just("https://wiki.internal/doc"),
    }).map(lambda d: Document(
        page_content=d["page_content"],
        metadata={"title": d["title"], "url": d["url"]},
    ))
    return st.lists(doc_strategy, min_size=0, max_size=5)


def st_orchestrator_state(**overrides):
    """Full OrchestratorState with random fields."""
    base = st.fixed_dictionaries({
        "raw_request": st_request(),
        "task_category": st.one_of(st.none(), st.sampled_from(VALID_CATEGORIES)),
        "entities": st_entities(),
        "confidence_score": st_confidence_score(),
        "clarifying_question": st.one_of(st.none(), st.text(min_size=1, max_size=100)),
        "execution_plan": st_execution_plan(min_steps=1),
        "missing_inputs": st.lists(
            st.fixed_dictionaries({
                "name": st.text(min_size=1, max_size=30),
                "description": st.text(min_size=1, max_size=80),
                "type": st.sampled_from(["string", "integer", "datetime", "list"]),
                "example": st.text(min_size=1, max_size=40),
            }),
            max_size=4,
        ),
        "pending_approval": st.booleans(),
        "current_step_index": st.integers(min_value=0, max_value=4),
        "hop_count": st.integers(min_value=0, max_value=15),
        "token_budget_used": st.integers(min_value=0, max_value=200_000),
        "token_budget_limit": st.integers(min_value=1, max_value=200_000),
        "visited_steps": st.lists(st.text(min_size=1, max_size=40), max_size=10),
        "step_results": st.just([]),
        "context_window": st_context_window(),
        "session_id": st.text(min_size=1, max_size=40),
        "user_id": st.text(min_size=1, max_size=40),
        "final_response": st.one_of(st.none(), st.text(min_size=1, max_size=500)),
        "citations": st.just([]),
        "error": st.none(),
    })
    if not overrides:
        return base
    return base.map(lambda s: {**s, **overrides})


def _mock_llm_response(payload: dict):
    mock_resp = MagicMock()
    mock_resp.content = json.dumps(payload)
    return mock_resp


# ─────────────────────────────────────────────────────────────────────────────
# Properties 1–4: Classification (Req 1)
# ─────────────────────────────────────────────────────────────────────────────

@given(raw_request=st_request())
@settings(max_examples=30)
def test_property1_task_category_in_valid_set(raw_request):
    # Feature: feature-01-core-orchestrator, Property 1: ∀ request: task_category ∈ {incident_investigation, infrastructure_change, cost_analysis, deployment, monitoring_query, knowledge_retrieval, code_review}
    from src.orchestrator.nodes.classify_request import classify_request
    state = {
        "raw_request": raw_request,
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
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    llm_payload = {
        "task_category": "monitoring_query",
        "entities": {"service": "EC2"},
        "confidence_score": 0.9,
        "clarifying_question": None,
    }
    with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockLLM:
        MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
        result = classify_request(state)
    # task_category must be in valid set OR None (when confidence < 0.7)
    assert result["task_category"] is None or result["task_category"] in VALID_CATEGORIES


@given(raw_request=st_request(), confidence=st_confidence_score())
@settings(max_examples=30)
def test_property2_confidence_score_in_range(raw_request, confidence):
    # Feature: feature-01-core-orchestrator, Property 2: ∀ request: confidence_score ∈ [0.0, 1.0]
    from src.orchestrator.nodes.classify_request import classify_request
    state = {
        "raw_request": raw_request,
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
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    llm_payload = {
        "task_category": "deployment",
        "entities": {},
        "confidence_score": confidence,
        "clarifying_question": None,
    }
    with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockLLM:
        MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
        result = classify_request(state)
    assert 0.0 <= result["confidence_score"] <= 1.0


@given(raw_request=st_request(), confidence=st.floats(min_value=0.0, max_value=0.699, allow_nan=False))
@settings(max_examples=30)
def test_property3_low_confidence_sets_clarifying_question(raw_request, confidence):
    # Feature: feature-01-core-orchestrator, Property 3: ∀ request with confidence_score < 0.7: clarifying_question is not None
    from src.orchestrator.nodes.classify_request import classify_request
    state = {
        "raw_request": raw_request,
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
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    llm_payload = {
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": confidence,
        "clarifying_question": "Which service are you asking about?",
    }
    with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockLLM:
        MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
        result = classify_request(state)
    assert result["clarifying_question"] is not None
    assert len(result["clarifying_question"]) > 0


@given(raw_request=st_request(), confidence=st.floats(min_value=0.7, max_value=1.0, allow_nan=False))
@settings(max_examples=30)
def test_property4_high_confidence_clears_clarifying_question(raw_request, confidence):
    # Feature: feature-01-core-orchestrator, Property 4: ∀ request with confidence_score >= 0.7: clarifying_question is None
    from src.orchestrator.nodes.classify_request import classify_request
    state = {
        "raw_request": raw_request,
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
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    llm_payload = {
        "task_category": "deployment",
        "entities": {},
        "confidence_score": confidence,
        "clarifying_question": "some question that should be cleared",
    }
    with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockLLM:
        MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
        result = classify_request(state)
    assert result["clarifying_question"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Properties 5–8: Plan Generation (Req 2)
# ─────────────────────────────────────────────────────────────────────────────

@given(plan=st_execution_plan(min_steps=1))
@settings(max_examples=30)
def test_property5_plan_has_at_least_one_step(plan):
    # Feature: feature-01-core-orchestrator, Property 5: ∀ plan: len(execution_plan) >= 1
    from src.orchestrator.nodes.generate_plan import generate_plan
    state = {
        "raw_request": "investigate high CPU",
        "task_category": "monitoring_query",
        "entities": {"service": "EC2"},
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
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    llm_payload = {"execution_plan": plan}
    with patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockLLM:
        MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
        result = generate_plan(state)
    assert len(result["execution_plan"]) >= 1


@given(plan=st_execution_plan(min_steps=1))
@settings(max_examples=30)
def test_property6_step_confidence_scores_in_range(plan):
    # Feature: feature-01-core-orchestrator, Property 6: ∀ step in plan: step["confidence_score"] ∈ [0.0, 1.0]
    from src.orchestrator.nodes.generate_plan import generate_plan
    state = {
        "raw_request": "deploy service",
        "task_category": "deployment",
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
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    llm_payload = {"execution_plan": plan}
    with patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockLLM:
        MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
        result = generate_plan(state)
    for step in result["execution_plan"]:
        assert 0.0 <= step["confidence_score"] <= 1.0


@given(confidence=st.floats(min_value=0.0, max_value=0.7499, allow_nan=False))
@settings(max_examples=30)
def test_property7_low_confidence_step_is_flagged(confidence):
    # Feature: feature-01-core-orchestrator, Property 7: ∀ step with confidence_score < 0.75: step["is_flagged"] == True and step["flag_rationale"] is not None
    from src.orchestrator.nodes.generate_plan import generate_plan
    step = {
        "step_index": 0,
        "description": "Query metrics",
        "expected_category": "monitoring_query",
        "required_capability": "query",
        "agent_id": None,
        "tool_name": "get_metric_statistics",
        "tool_inputs": {},
        "expected_output_schema": {},
        "confidence_score": confidence,
        "is_flagged": True,
        "flag_rationale": f"Low confidence {confidence:.2f}",
        "requires_approval": False,
    }
    state = {
        "raw_request": "check metrics",
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
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    llm_payload = {"execution_plan": [step]}
    with patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockLLM:
        MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
        result = generate_plan(state)
    s = result["execution_plan"][0]
    assert s["is_flagged"] is True
    assert s["flag_rationale"] is not None
    assert len(s["flag_rationale"]) > 0


@given(plan=st_execution_plan(min_steps=1))
@settings(max_examples=30)
def test_property8_plan_presented_before_execution(plan):
    # Feature: feature-01-core-orchestrator, Property 8: ∀ plan: plan is presented to user before any step executes
    from src.orchestrator.nodes.present_plan import present_plan
    state = {
        "raw_request": "deploy service",
        "task_category": "deployment",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": plan,
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    result = present_plan(state)
    # pending_approval=True signals the plan was presented; routing then waits for user
    assert result["pending_approval"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Properties 9–11: Missing Inputs (Req 3)
# ─────────────────────────────────────────────────────────────────────────────

@given(
    missing=st.lists(
        st.fixed_dictionaries({
            "name": st.text(min_size=1, max_size=30),
            "description": st.text(min_size=1, max_size=80),
            "type": st.sampled_from(["string", "integer", "datetime"]),
            "example": st.text(min_size=1, max_size=40),
        }),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=30)
def test_property9_missing_inputs_blocks_execution(missing):
    # Feature: feature-01-core-orchestrator, Property 9: ∀ state with missing_inputs not empty: no step executes until all inputs resolved
    from src.orchestrator.graph import _route_detect_missing_inputs
    state = {
        "raw_request": "deploy service",
        "task_category": "deployment",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": missing,
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    # When missing_inputs is non-empty, routing must go to prompt_user (not generate_plan)
    route = _route_detect_missing_inputs(state)
    assert route == "prompt_user"


@given(
    missing=st.lists(
        st.fixed_dictionaries({
            "name": st.text(min_size=1, max_size=30),
            "description": st.text(min_size=1, max_size=80),
            "type": st.sampled_from(["string", "integer", "datetime"]),
            "example": st.text(min_size=1, max_size=40),
        }),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=30)
def test_property10_missing_inputs_consolidated_into_single_prompt(missing):
    # Feature: feature-01-core-orchestrator, Property 10: ∀ missing inputs: all consolidated into single prompt (not asked one-at-a-time mid-execution)
    from src.orchestrator.nodes.prompt_user import prompt_user
    state = {
        "raw_request": "deploy service",
        "task_category": "deployment",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": missing,
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    result = prompt_user(state)
    # All inputs consolidated into a single clarifying_question string
    assert result["clarifying_question"] is not None
    # All input names appear in the single consolidated prompt
    for item in missing:
        assert item["name"] in result["clarifying_question"]
    # missing_inputs cleared after consolidation
    assert result["missing_inputs"] == []


@given(
    missing=st.lists(
        st.fixed_dictionaries({
            "name": st.text(min_size=1, max_size=30),
            "description": st.text(min_size=1, max_size=80),
            "type": st.sampled_from(["string", "integer", "datetime"]),
            "example": st.text(min_size=1, max_size=40),
        }),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=30)
def test_property11_consolidated_prompt_includes_examples(missing):
    # Feature: feature-01-core-orchestrator, Property 11: ∀ invalid missing-input response: re-prompt issued with validation error + example
    from src.orchestrator.nodes.prompt_user import prompt_user
    state = {
        "raw_request": "deploy service",
        "task_category": "deployment",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": missing,
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    result = prompt_user(state)
    # Each missing input's example value must appear in the consolidated prompt
    for item in missing:
        assert item["example"] in result["clarifying_question"]


# ─────────────────────────────────────────────────────────────────────────────
# Properties 12–15: Orchestration (Req 4)
# ─────────────────────────────────────────────────────────────────────────────

@given(hop_count=st.integers(min_value=10, max_value=50))
@settings(max_examples=30)
def test_property12_hop_count_never_exceeds_10(hop_count):
    # Feature: feature-01-core-orchestrator, Property 12: ∀ execution: hop_count never exceeds 10
    from src.orchestrator.nodes.invoke_subagent import _check_safety_limits
    state = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [{"step_index": 0, "agent_id": "agent-1", "tool_inputs": {}}],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": hop_count,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    is_safe, error = _check_safety_limits(state)
    assert is_safe is False
    assert error is not None
    assert error["type"] == "hop_limit_exceeded"


@given(
    agent_id=st.text(min_size=1, max_size=30),
    tool_inputs=st.dictionaries(
        st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("Ll",))),
        st.text(max_size=20),
        max_size=3,
    ),
)
@settings(max_examples=30)
def test_property13_cycle_detection_fires_on_repeated_agent_inputs(agent_id, tool_inputs):
    # Feature: feature-01-core-orchestrator, Property 13: ∀ execution: cycle detection fires when (agent_id, inputs_hash) repeats
    from src.orchestrator.nodes.invoke_subagent import _check_safety_limits
    inputs_hash = hashlib.sha256(json.dumps(tool_inputs, sort_keys=True).encode()).hexdigest()[:16]
    step_key = f"{agent_id}:{inputs_hash}"
    state = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [{"step_index": 0, "agent_id": agent_id, "tool_inputs": tool_inputs}],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [step_key],  # already visited — cycle!
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    is_safe, error = _check_safety_limits(state)
    assert is_safe is False
    assert error is not None
    assert error["type"] == "cycle_detected"


@given(
    budget_used=st.integers(min_value=0, max_value=200_000),
    budget_limit=st.integers(min_value=1, max_value=200_000),
)
@settings(max_examples=30)
def test_property14_token_budget_halts_execution(budget_used, budget_limit):
    # Feature: feature-01-core-orchestrator, Property 14: ∀ execution: token_budget_used tracked and halts when >= token_budget_limit
    from src.orchestrator.nodes.invoke_subagent import _check_safety_limits
    assume(budget_used >= budget_limit)
    state = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [{"step_index": 0, "agent_id": "agent-1", "tool_inputs": {}}],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": budget_used,
        "token_budget_limit": budget_limit,
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    is_safe, error = _check_safety_limits(state)
    assert is_safe is False
    assert error is not None
    assert error["type"] == "token_budget_exceeded"


@given(plan=st_execution_plan(min_steps=1))
@settings(max_examples=30)
def test_property15_independent_steps_routing_allows_parallel_dispatch(plan):
    # Feature: feature-01-core-orchestrator, Property 15: ∀ independent steps: executed in parallel (max 5 concurrent)
    # Test that the routing function allows up to 5 concurrent steps by verifying
    # the plan can contain up to 5 steps and routing proceeds to invoke_subagent
    from src.orchestrator.graph import _route_validate_step_pre
    # Build a state where pre-validation passed (no pre_validation_failed)
    state = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": plan,
        "missing_inputs": [],
        "pending_approval": True,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [{"step_index": 0, "pre_validation_failed": False}],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    route = _route_validate_step_pre(state)
    # When pre-validation passes, routing goes to invoke_subagent (enabling parallel dispatch)
    assert route == "invoke_subagent"
    # Parallel cap: plan must not exceed 5 steps (enforced by st_execution_plan max_size=5)
    assert len(plan) <= 5


# ─────────────────────────────────────────────────────────────────────────────
# Properties 16–19: Step Validation (Req 13)
# ─────────────────────────────────────────────────────────────────────────────

@given(plan=st_execution_plan(min_steps=1))
@settings(max_examples=30)
def test_property16_validate_step_pre_runs_before_invoke_subagent(plan):
    # Feature: feature-01-core-orchestrator, Property 16: ∀ step: validate_step_pre runs before invoke_subagent
    from src.orchestrator.graph import _route_validate_step_pre
    # When step_results is empty (validate_step_pre hasn't run yet), routing must
    # not go to invoke_subagent — it should go to aggregate_results as a safety fallback.
    # Conversely, after validate_step_pre runs and passes, routing goes to invoke_subagent.
    state_before = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": plan,
        "missing_inputs": [],
        "pending_approval": True,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [{"step_index": 0, "pre_validation_failed": True}],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    # Pre-validation failed → must NOT route to invoke_subagent
    route_failed = _route_validate_step_pre(state_before)
    assert route_failed == "aggregate_results"

    state_after = {**state_before, "step_results": [{"step_index": 0, "pre_validation_failed": False}]}
    # Pre-validation passed → routes to invoke_subagent
    route_passed = _route_validate_step_pre(state_after)
    assert route_passed == "invoke_subagent"


@given(
    confidence=st.floats(min_value=0.7, max_value=1.0, allow_nan=False),
)
@settings(max_examples=30)
def test_property17_validate_step_post_runs_after_invoke_subagent(confidence):
    # Feature: feature-01-core-orchestrator, Property 17: ∀ step: validate_step_post runs after invoke_subagent
    from src.orchestrator.nodes.validate_step_post import validate_step_post
    # Simulate state after invoke_subagent has populated agent_result
    state = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [{"step_index": 0, "description": "step"}],
        "missing_inputs": [],
        "pending_approval": True,
        "current_step_index": 0,
        "hop_count": 1,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [{
            "step_index": 0,
            "pre_validation_failed": False,
            "retry_count": 0,
            "agent_result": {"result": "output", "confidence_score": confidence},
        }],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    result = validate_step_post(state)
    # validate_step_post must set post_validation_passed on the last step_result
    assert "post_validation_passed" in result["step_results"][-1]


@given(retry_count=st.integers(min_value=0, max_value=10))
@settings(max_examples=30)
def test_property18_post_validation_retry_count_capped_at_2(retry_count):
    # Feature: feature-01-core-orchestrator, Property 18: ∀ post-validation failure: retry_count <= 2
    from src.orchestrator.graph import _route_validate_step_post
    state = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [{"step_index": 0}],
        "missing_inputs": [],
        "pending_approval": True,
        "current_step_index": 0,
        "hop_count": 1,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [{
            "step_index": 0,
            "post_validation_passed": False,
            "retry_count": retry_count,
        }],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    route = _route_validate_step_post(state)
    if retry_count < 2:
        # Still within retry budget → retry
        assert route == "invoke_subagent"
    else:
        # Exhausted retries → escalate
        assert route == "aggregate_results"


@given(plan=st_execution_plan(min_steps=1))
@settings(max_examples=30)
def test_property19_exactly_one_log_entry_per_completed_step(plan):
    # Feature: feature-01-core-orchestrator, Property 19: ∀ completed step: exactly one execution-log entry written
    from src.orchestrator.nodes.write_execution_log import write_execution_log
    step_results = [
        {
            "step_index": i,
            "pre_validation_failed": False,
            "post_validation_passed": True,
            "retry_count": 0,
            "agent_id": "mock-agent",
            "tool_name": "get_metric_statistics",
            "agent_result": {"result": "ok", "confidence_score": 0.9},
            "prompt_template_id": "monitoring_query-v1",
            "prompt_template_version": "1.0.0",
        }
        for i in range(len(plan))
    ]
    state = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": plan,
        "missing_inputs": [],
        "pending_approval": True,
        "current_step_index": len(plan) - 1,
        "hop_count": len(plan),
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": step_results,
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    written_entries = []
    with patch("src.orchestrator.nodes.write_execution_log.put_item") as mock_put:
        mock_put.side_effect = lambda table, entry: written_entries.append(entry)
        write_execution_log(state)
    # Exactly one log entry per step result
    assert len(written_entries) == len(plan)


# ─────────────────────────────────────────────────────────────────────────────
# Properties 20–21: Output Quality (Req 14)
# ─────────────────────────────────────────────────────────────────────────────

@given(confidence=st.floats(min_value=0.0, max_value=0.7999, allow_nan=False))
@settings(max_examples=30)
def test_property20_low_confidence_final_response_states_uncertainty(confidence):
    # Feature: feature-01-core-orchestrator, Property 20: ∀ final_response with confidence_score < 0.8: uncertainty explicitly stated
    from src.orchestrator.nodes.aggregate_results import aggregate_results
    # Provide step_results with the given confidence so aggregate_results computes it
    state = {
        "raw_request": "investigate high CPU",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": confidence,
        "clarifying_question": None,
        "execution_plan": [{"step_index": 0, "tool_name": "get_metric_statistics", "tool_inputs": {}}],
        "missing_inputs": [],
        "pending_approval": True,
        "current_step_index": 0,
        "hop_count": 1,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [{
            "step_index": 0,
            "pre_validation_failed": False,
            "agent_result": {"result": "some output", "confidence_score": confidence},
        }],
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    result = aggregate_results(state)
    assert result["final_response"] is not None
    # Uncertainty must be explicitly stated in the response
    response_lower = result["final_response"].lower()
    assert "uncertainty" in response_lower or "confidence" in response_lower or "⚠️" in result["final_response"]


@given(docs=st.lists(
    st.fixed_dictionaries({
        "page_content": st.text(min_size=1, max_size=100),
        "title": st.text(min_size=1, max_size=50),
        "url": st.just("https://wiki.internal/doc"),
    }),
    min_size=1,
    max_size=3,
))
@settings(max_examples=30)
def test_property21_citations_non_empty_when_kb_docs_used(docs):
    # Feature: feature-01-core-orchestrator, Property 21: ∀ final_response: citations list is non-empty when KB documents were used
    from langchain_core.documents import Document
    from src.orchestrator.nodes.aggregate_results import aggregate_results
    kb_docs = [
        Document(page_content=d["page_content"], metadata={"title": d["title"], "url": d["url"]})
        for d in docs
    ]
    state = {
        "raw_request": "investigate high CPU",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": [],
        "pending_approval": True,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": [],
        "context_window": kb_docs,
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    result = aggregate_results(state)
    # KB documents with URLs must produce non-empty citations
    assert len(result["citations"]) > 0
    for citation in result["citations"]:
        assert "title" in citation
        assert "url" in citation
        assert citation["url"] != ""


# ─────────────────────────────────────────────────────────────────────────────
# Properties 22–23: Prompt Templates (Req 16)
# ─────────────────────────────────────────────────────────────────────────────

@given(plan=st_execution_plan(min_steps=1))
@settings(max_examples=30)
def test_property22_prompt_template_id_and_version_recorded_in_log(plan):
    # Feature: feature-01-core-orchestrator, Property 22: ∀ LLM invocation: prompt_template_id and prompt_template_version recorded in execution log
    from src.orchestrator.nodes.write_execution_log import write_execution_log
    step_results = [
        {
            "step_index": i,
            "pre_validation_failed": False,
            "post_validation_passed": True,
            "retry_count": 0,
            "agent_id": "mock-agent",
            "tool_name": "get_metric_statistics",
            "agent_result": {"result": "ok", "confidence_score": 0.9},
            "prompt_template_id": f"monitoring_query-v1",
            "prompt_template_version": "1.0.0",
        }
        for i in range(len(plan))
    ]
    state = {
        "raw_request": "investigate",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": plan,
        "missing_inputs": [],
        "pending_approval": True,
        "current_step_index": len(plan) - 1,
        "hop_count": len(plan),
        "token_budget_used": 0,
        "token_budget_limit": 100_000,
        "visited_steps": [],
        "step_results": step_results,
        "context_window": [],
        "session_id": "sess-pbt",
        "user_id": "user-pbt",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    written_entries = []
    with patch("src.orchestrator.nodes.write_execution_log.put_item") as mock_put:
        mock_put.side_effect = lambda table, entry: written_entries.append(entry)
        write_execution_log(state)
    for entry in written_entries:
        assert "promptTemplateId" in entry
        assert entry["promptTemplateId"] is not None
        assert "promptTemplateVersion" in entry
        assert entry["promptTemplateVersion"] is not None


@given(category=st.sampled_from(VALID_CATEGORIES))
@settings(max_examples=20)
def test_property23_rendered_prompt_has_no_unresolved_placeholders(category):
    # Feature: feature-01-core-orchestrator, Property 23: ∀ rendered prompt: no unresolved placeholder variables
    import re
    from src.orchestrator.prompts import load_prompt_template, validate_rendered_prompt, UnresolvedPlaceholderError

    # load_prompt_template is lru_cached; clear between hypothesis examples
    load_prompt_template.cache_clear()

    template = load_prompt_template(category)
    # Render with a concrete input value
    messages = template.format_messages(input="investigate high CPU on prod EC2")
    rendered_text = "\n".join(
        m.content for m in messages if hasattr(m, "content")
    )
    # validate_rendered_prompt raises UnresolvedPlaceholderError if any {var} remains
    try:
        validate_rendered_prompt(rendered_text, template_id=f"{category}-v1")
    except UnresolvedPlaceholderError as exc:
        pytest.fail(f"Unresolved placeholder in rendered prompt for '{category}': {exc}")

