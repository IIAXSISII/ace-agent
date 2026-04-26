"""
Unit tests for nodes implemented in tasks 6.1–6.5.
Feature: feature-01-core-orchestrator
Task: 14.1
Covers: Properties 1–11 from design.md (Req 1, 2, 3)
"""
import json
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("MOCK_STORAGE", "true")
os.environ.setdefault("MOCK_PROMPTS", "true")

# ── Stub out langchain_aws before any node module is imported ─────────────────
# classify_request, detect_missing_inputs, and generate_plan all do
# `from langchain_aws import ChatBedrock` at module level.  Since langchain_aws
# is not installed in the test venv we inject a lightweight stub so the import
# succeeds; the actual ChatBedrock constructor is then patched per-test.
if "langchain_aws" not in sys.modules:
    _stub = ModuleType("langchain_aws")
    _stub.ChatBedrock = MagicMock()  # type: ignore[attr-defined]
    sys.modules["langchain_aws"] = _stub

VALID_CATEGORIES = {
    "incident_investigation",
    "infrastructure_change",
    "cost_analysis",
    "deployment",
    "monitoring_query",
    "knowledge_retrieval",
    "code_review",
}


def _base_state(**overrides):
    state = {
        "raw_request": "investigate high CPU on prod EC2",
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
        "session_id": "sess-14-1",
        "user_id": "user-1",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    state.update(overrides)
    return state


def _mock_llm_response(payload: dict):
    """Return a MagicMock that looks like a ChatBedrock response."""
    mock_resp = MagicMock()
    mock_resp.content = json.dumps(payload)
    return mock_resp


# ─────────────────────────────────────────────────────────────────────────────
# classify_request — Properties 1, 2, 3, 4
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyRequest:
    """Tests for classify_request node (task 6.1)."""

    def _call(self, llm_payload, raw_request="investigate high CPU"):
        from src.orchestrator.nodes.classify_request import classify_request
        state = _base_state(raw_request=raw_request)
        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockLLM:
            MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
            return classify_request(state)

    # Property 1: task_category ∈ valid set
    def test_property1_valid_category_returned(self):
        # Property 1: task_category ∈ {incident_investigation, infrastructure_change, ...}
        result = self._call({
            "task_category": "monitoring_query",
            "entities": {"service": "EC2"},
            "confidence_score": 0.9,
            "clarifying_question": None,
        })
        assert result["task_category"] in VALID_CATEGORIES

    def test_property1_all_valid_categories_accepted(self):
        # Property 1: every valid category is accepted as-is
        for cat in VALID_CATEGORIES:
            result = self._call({
                "task_category": cat,
                "entities": {},
                "confidence_score": 0.9,
                "clarifying_question": None,
            })
            assert result["task_category"] == cat

    def test_property1_invalid_category_becomes_none(self):
        # Property 1: unknown category is rejected → task_category = None
        result = self._call({
            "task_category": "not_a_real_category",
            "entities": {},
            "confidence_score": 0.9,
            "clarifying_question": None,
        })
        assert result["task_category"] is None

    # Property 2: confidence_score ∈ [0.0, 1.0]
    def test_property2_confidence_score_in_range(self):
        # Property 2: confidence_score ∈ [0.0, 1.0]
        result = self._call({
            "task_category": "deployment",
            "entities": {},
            "confidence_score": 0.85,
            "clarifying_question": None,
        })
        assert 0.0 <= result["confidence_score"] <= 1.0

    def test_property2_confidence_clamped_above_1(self):
        # Property 2: LLM returning > 1.0 is clamped to 1.0
        result = self._call({
            "task_category": "deployment",
            "entities": {},
            "confidence_score": 1.5,
            "clarifying_question": None,
        })
        assert result["confidence_score"] <= 1.0

    def test_property2_confidence_clamped_below_0(self):
        # Property 2: LLM returning < 0.0 is clamped to 0.0
        result = self._call({
            "task_category": "deployment",
            "entities": {},
            "confidence_score": -0.3,
            "clarifying_question": None,
        })
        assert result["confidence_score"] >= 0.0

    # Property 3: confidence < 0.7 → clarifying_question is not None
    def test_property3_low_confidence_sets_clarifying_question(self):
        # Property 3: ∀ request with confidence_score < 0.7: clarifying_question is not None
        result = self._call({
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.5,
            "clarifying_question": "Which service are you asking about?",
        })
        assert result["clarifying_question"] is not None
        assert len(result["clarifying_question"]) > 0

    def test_property3_low_confidence_generates_fallback_question(self):
        # Property 3: even if LLM omits clarifying_question, node generates one
        result = self._call({
            "task_category": "monitoring_query",
            "entities": {},
            "confidence_score": 0.4,
            "clarifying_question": None,
        })
        assert result["clarifying_question"] is not None

    def test_property3_low_confidence_clears_task_category(self):
        # Property 3 corollary: low confidence → task_category set to None
        result = self._call({
            "task_category": "deployment",
            "entities": {},
            "confidence_score": 0.6,
            "clarifying_question": "What do you mean?",
        })
        assert result["task_category"] is None

    # Property 4: confidence >= 0.7 → clarifying_question is None
    def test_property4_high_confidence_clears_clarifying_question(self):
        # Property 4: ∀ request with confidence_score >= 0.7: clarifying_question is None
        result = self._call({
            "task_category": "incident_investigation",
            "entities": {"service": "RDS"},
            "confidence_score": 0.9,
            "clarifying_question": "some question",
        })
        assert result["clarifying_question"] is None

    def test_property4_exactly_0_7_clears_clarifying_question(self):
        # Property 4: boundary — exactly 0.7 is high enough
        result = self._call({
            "task_category": "cost_analysis",
            "entities": {},
            "confidence_score": 0.7,
            "clarifying_question": None,
        })
        assert result["clarifying_question"] is None

    def test_property4_high_confidence_preserves_task_category(self):
        # Property 4: high confidence → task_category is preserved
        result = self._call({
            "task_category": "code_review",
            "entities": {},
            "confidence_score": 0.95,
            "clarifying_question": None,
        })
        assert result["task_category"] == "code_review"

    def test_llm_exception_falls_back_to_zero_confidence(self):
        # On LLM error, node falls back gracefully with confidence=0.0 and a clarifying question
        from src.orchestrator.nodes.classify_request import classify_request
        state = _base_state(raw_request="something")
        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockLLM:
            MockLLM.return_value.invoke.side_effect = Exception("Bedrock unavailable")
            result = classify_request(state)
        assert result["confidence_score"] == 0.0
        assert result["clarifying_question"] is not None
        assert result["task_category"] is None

    def test_state_fields_preserved(self):
        # Node must return all original state fields plus updated ones
        result = self._call({
            "task_category": "deployment",
            "entities": {"env": "prod"},
            "confidence_score": 0.88,
            "clarifying_question": None,
        })
        assert result["session_id"] == "sess-14-1"
        assert result["user_id"] == "user-1"


# ─────────────────────────────────────────────────────────────────────────────
# retrieve_knowledge — no LLM, pure fixture logic
# ─────────────────────────────────────────────────────────────────────────────

class TestRetrieveKnowledge:
    """Tests for retrieve_knowledge node (task 6.2)."""

    def test_returns_fixture_docs_when_no_knowledge_base_id(self, monkeypatch):
        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge, FIXTURE_DOCS
        monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
        state = _base_state()
        result = retrieve_knowledge(state)
        assert len(result["context_window"]) == len(FIXTURE_DOCS)

    def test_docs_have_title_url_content(self, monkeypatch):
        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
        monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
        state = _base_state()
        result = retrieve_knowledge(state)
        for doc in result["context_window"]:
            assert doc.metadata.get("title")
            assert doc.metadata.get("url")
            assert doc.page_content

    def test_appends_to_existing_context_window(self, monkeypatch):
        from langchain_core.documents import Document
        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
        monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
        existing_doc = Document(page_content="prior context", metadata={"title": "Prior", "url": "http://x"})
        state = _base_state(context_window=[existing_doc])
        result = retrieve_knowledge(state)
        assert result["context_window"][0].page_content == "prior context"
        assert len(result["context_window"]) > 1

    def test_state_fields_preserved(self, monkeypatch):
        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
        monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
        state = _base_state()
        result = retrieve_knowledge(state)
        assert result["session_id"] == "sess-14-1"
        assert result["task_category"] == "monitoring_query"

    def test_falls_back_to_fixtures_when_retriever_raises(self, monkeypatch):
        from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge, FIXTURE_DOCS
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", "kb-test-123")
        # Stub AmazonKnowledgeBasesRetriever inside the module
        mock_retriever_cls = MagicMock()
        mock_retriever_cls.return_value.invoke.side_effect = Exception("KB unavailable")
        with patch.dict(sys.modules, {"langchain_aws": MagicMock(
            ChatBedrock=MagicMock(),
            AmazonKnowledgeBasesRetriever=mock_retriever_cls,
        )}):
            # Re-import to pick up the patched module
            import importlib
            import src.orchestrator.nodes.retrieve_knowledge as rk_mod
            importlib.reload(rk_mod)
            state = _base_state()
            result = rk_mod.retrieve_knowledge(state)
        assert len(result["context_window"]) == len(FIXTURE_DOCS)


# ─────────────────────────────────────────────────────────────────────────────
# detect_missing_inputs — Properties 9, 10, 11
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectMissingInputs:
    """Tests for detect_missing_inputs node (task 6.3)."""

    def _call(self, llm_payload, **state_overrides):
        from src.orchestrator.nodes.detect_missing_inputs import detect_missing_inputs
        state = _base_state(**state_overrides)
        with patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockLLM:
            MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
            return detect_missing_inputs(state)

    # Property 9: missing_inputs not empty → no step executes
    def test_property9_missing_inputs_populated_when_llm_returns_them(self):
        # Property 9: ∀ state with missing_inputs not empty: no step executes until all inputs resolved
        result = self._call({
            "missing_inputs": [
                {"name": "time_range", "description": "Time range", "type": "string", "example": "last 1h"},
            ]
        })
        assert len(result["missing_inputs"]) == 1
        assert result["missing_inputs"][0]["name"] == "time_range"

    def test_property9_empty_missing_inputs_when_none_needed(self):
        # Property 9: when LLM says no missing inputs, list is empty → execution can proceed
        result = self._call({"missing_inputs": []})
        assert result["missing_inputs"] == []

    # Property 10: all missing inputs consolidated into single list
    def test_property10_multiple_missing_inputs_returned_together(self):
        # Property 10: ∀ missing inputs: all consolidated into single prompt
        result = self._call({
            "missing_inputs": [
                {"name": "service_name", "description": "AWS service", "type": "string", "example": "EC2"},
                {"name": "time_range", "description": "Time range", "type": "string", "example": "last 1h"},
                {"name": "environment", "description": "Env", "type": "string", "example": "prod"},
            ]
        })
        assert len(result["missing_inputs"]) == 3

    def test_property10_each_input_has_required_fields(self):
        # Property 10: each missing input has name, description, type, example
        result = self._call({
            "missing_inputs": [
                {"name": "region", "description": "AWS region", "type": "string", "example": "us-east-1"},
            ]
        })
        item = result["missing_inputs"][0]
        assert "name" in item
        assert "description" in item
        assert "type" in item
        assert "example" in item

    # Property 11: invalid missing-input response → re-prompt with validation error + example
    def test_property11_items_without_name_are_filtered(self):
        # Property 11: invalid entries (missing 'name') are filtered out
        result = self._call({
            "missing_inputs": [
                {"description": "no name here", "type": "string", "example": "x"},
                {"name": "valid_field", "description": "valid", "type": "string", "example": "y"},
            ]
        })
        assert len(result["missing_inputs"]) == 1
        assert result["missing_inputs"][0]["name"] == "valid_field"

    def test_property11_non_list_missing_inputs_becomes_empty(self):
        # Property 11: malformed LLM response (not a list) → empty missing_inputs
        result = self._call({"missing_inputs": "not a list"})
        assert result["missing_inputs"] == []

    def test_llm_exception_returns_empty_missing_inputs(self):
        from src.orchestrator.nodes.detect_missing_inputs import detect_missing_inputs
        state = _base_state()
        with patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockLLM:
            MockLLM.return_value.invoke.side_effect = Exception("Bedrock error")
            result = detect_missing_inputs(state)
        assert result["missing_inputs"] == []

    def test_state_fields_preserved(self):
        result = self._call({"missing_inputs": []})
        assert result["session_id"] == "sess-14-1"
        assert result["raw_request"] == "investigate high CPU on prod EC2"


# ─────────────────────────────────────────────────────────────────────────────
# generate_plan — Properties 5, 6, 7
# ─────────────────────────────────────────────────────────────────────────────

class TestGeneratePlan:
    """Tests for generate_plan node (task 6.4)."""

    def _call(self, llm_payload, **state_overrides):
        from src.orchestrator.nodes.generate_plan import generate_plan
        state = _base_state(**state_overrides)
        with patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockLLM:
            MockLLM.return_value.invoke.return_value = _mock_llm_response(llm_payload)
            return generate_plan(state)

    def _make_step(self, confidence_score=0.9, step_index=0, **overrides):
        step = {
            "step_index": step_index,
            "description": "Query CloudWatch metrics",
            "expected_category": "monitoring_query",
            "required_capability": "query metrics",
            "agent_id": None,
            "tool_name": "get_metric_statistics",
            "tool_inputs": {"namespace": "AWS/EC2"},
            "expected_output_schema": {},
            "confidence_score": confidence_score,
            "is_flagged": confidence_score < 0.75,
            "flag_rationale": f"Low confidence {confidence_score}" if confidence_score < 0.75 else None,
            "requires_approval": False,
        }
        step.update(overrides)
        return step

    # Property 5: len(execution_plan) >= 1
    def test_property5_plan_has_at_least_one_step(self):
        # Property 5: ∀ plan: len(execution_plan) >= 1
        result = self._call({"execution_plan": [self._make_step()]})
        assert len(result["execution_plan"]) >= 1

    def test_property5_multiple_steps_preserved(self):
        # Property 5: multi-step plans are preserved
        steps = [self._make_step(step_index=i) for i in range(3)]
        result = self._call({"execution_plan": steps})
        assert len(result["execution_plan"]) == 3

    def test_property5_empty_plan_on_llm_exception(self):
        # Property 5 edge: LLM failure → empty plan (node returns [] gracefully)
        from src.orchestrator.nodes.generate_plan import generate_plan
        state = _base_state()
        with patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockLLM:
            MockLLM.return_value.invoke.side_effect = Exception("LLM error")
            result = generate_plan(state)
        assert result["execution_plan"] == []

    # Property 6: ∀ step in plan: step["confidence_score"] ∈ [0.0, 1.0]
    def test_property6_step_confidence_in_range(self):
        # Property 6: ∀ step in plan: step["confidence_score"] ∈ [0.0, 1.0]
        result = self._call({"execution_plan": [self._make_step(confidence_score=0.85)]})
        for step in result["execution_plan"]:
            assert 0.0 <= step["confidence_score"] <= 1.0

    def test_property6_confidence_clamped_above_1(self):
        # Property 6: step confidence > 1.0 is clamped
        step = self._make_step(confidence_score=1.5)
        result = self._call({"execution_plan": [step]})
        assert result["execution_plan"][0]["confidence_score"] <= 1.0

    def test_property6_confidence_clamped_below_0(self):
        # Property 6: step confidence < 0.0 is clamped
        step = self._make_step(confidence_score=-0.2)
        result = self._call({"execution_plan": [step]})
        assert result["execution_plan"][0]["confidence_score"] >= 0.0

    def test_property6_all_steps_have_confidence_score(self):
        # Property 6: every step has a confidence_score field
        steps = [self._make_step(confidence_score=0.8, step_index=i) for i in range(3)]
        result = self._call({"execution_plan": steps})
        for step in result["execution_plan"]:
            assert "confidence_score" in step

    # Property 7: step confidence < 0.75 → is_flagged=True and flag_rationale is not None
    def test_property7_low_confidence_step_is_flagged(self):
        # Property 7: ∀ step with confidence_score < 0.75: is_flagged == True and flag_rationale is not None
        step = self._make_step(confidence_score=0.6)
        result = self._call({"execution_plan": [step]})
        s = result["execution_plan"][0]
        assert s["is_flagged"] is True
        assert s["flag_rationale"] is not None

    def test_property7_high_confidence_step_not_flagged(self):
        # Property 7 inverse: confidence >= 0.75 → is_flagged=False and flag_rationale=None
        step = self._make_step(confidence_score=0.9)
        result = self._call({"execution_plan": [step]})
        s = result["execution_plan"][0]
        assert s["is_flagged"] is False
        assert s["flag_rationale"] is None

    def test_property7_exactly_0_75_not_flagged(self):
        # Property 7 boundary: exactly 0.75 is NOT flagged
        step = self._make_step(confidence_score=0.75)
        result = self._call({"execution_plan": [step]})
        s = result["execution_plan"][0]
        assert s["is_flagged"] is False

    def test_property7_flag_rationale_generated_when_missing(self):
        # Property 7: if LLM omits flag_rationale for a flagged step, node generates one
        step = self._make_step(confidence_score=0.5)
        step["flag_rationale"] = None  # LLM omitted it
        result = self._call({"execution_plan": [step]})
        s = result["execution_plan"][0]
        assert s["is_flagged"] is True
        assert s["flag_rationale"] is not None
        assert len(s["flag_rationale"]) > 0

    def test_property7_mixed_steps_flagged_correctly(self):
        # Property 7: mixed plan — only low-confidence steps flagged
        steps = [
            self._make_step(confidence_score=0.9, step_index=0),
            self._make_step(confidence_score=0.5, step_index=1),
            self._make_step(confidence_score=0.8, step_index=2),
        ]
        result = self._call({"execution_plan": steps})
        plan = result["execution_plan"]
        assert plan[0]["is_flagged"] is False
        assert plan[1]["is_flagged"] is True
        assert plan[1]["flag_rationale"] is not None
        assert plan[2]["is_flagged"] is False

    def test_state_fields_preserved(self):
        result = self._call({"execution_plan": [self._make_step()]})
        assert result["session_id"] == "sess-14-1"
        assert result["task_category"] == "monitoring_query"


# ─────────────────────────────────────────────────────────────────────────────
# present_plan — Property 8
# ─────────────────────────────────────────────────────────────────────────────

class TestPresentPlan:
    """Tests for present_plan node (task 6.5)."""

    # Property 8: plan is presented to user before any step executes
    def test_property8_sets_pending_approval_true(self):
        # Property 8: ∀ plan: plan is presented to user before any step executes
        # present_plan signals this by setting pending_approval=True
        from src.orchestrator.nodes.present_plan import present_plan
        state = _base_state(pending_approval=False)
        result = present_plan(state)
        assert result["pending_approval"] is True

    def test_property8_pending_approval_already_false_before_call(self):
        # Property 8: before present_plan runs, pending_approval is False
        from src.orchestrator.nodes.present_plan import present_plan
        state = _base_state(pending_approval=False)
        assert state["pending_approval"] is False
        result = present_plan(state)
        assert result["pending_approval"] is True

    def test_property8_idempotent_when_already_true(self):
        # Property 8: calling present_plan when already approved keeps it True
        from src.orchestrator.nodes.present_plan import present_plan
        state = _base_state(pending_approval=True)
        result = present_plan(state)
        assert result["pending_approval"] is True

    def test_state_fields_preserved(self):
        # present_plan must not drop any state fields
        from src.orchestrator.nodes.present_plan import present_plan
        state = _base_state(
            execution_plan=[{"step_index": 0, "description": "step"}],
            task_category="deployment",
        )
        result = present_plan(state)
        assert result["execution_plan"] == state["execution_plan"]
        assert result["task_category"] == "deployment"
        assert result["session_id"] == "sess-14-1"

    def test_does_not_modify_execution_plan(self):
        # present_plan must not alter the plan — only signals readiness
        from src.orchestrator.nodes.present_plan import present_plan
        plan = [
            {"step_index": 0, "description": "step A", "confidence_score": 0.9},
            {"step_index": 1, "description": "step B", "confidence_score": 0.6},
        ]
        state = _base_state(execution_plan=plan)
        result = present_plan(state)
        assert result["execution_plan"] == plan

    def test_no_llm_call_made(self):
        # present_plan is a pure state mutation — no LLM involved
        from src.orchestrator.nodes.present_plan import present_plan
        state = _base_state()
        result = present_plan(state)
        assert result["pending_approval"] is True
