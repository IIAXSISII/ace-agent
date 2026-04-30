"""
Unit tests for graph nodes implemented in task 7.
Feature: feature-01-core-orchestrator
Covers: Req 4, 13, 14
"""
import os
import time

import pytest

# Set mock env before importing modules
os.environ.setdefault("MOCK_STORAGE", "true")
os.environ.setdefault("MOCK_PROMPTS", "true")


def _base_state(**overrides):
    state = {
        "raw_request": "investigate high CPU on prod",
        "task_category": "monitoring_query",
        "entities": {},
        "confidence_score": 0.9,
        "clarifying_question": None,
        "execution_plan": [
            {
                "step_index": 0,
                "description": "Query CloudWatch metrics",
                "expected_category": "monitoring_query",
                "required_capability": "query CloudWatch metrics",
                "agent_id": "mock-cloudwatch-agent",
                "tool_name": "get_metric_statistics",
                "tool_inputs": {"namespace": "AWS/EC2", "metric": "CPUUtilization"},
                "expected_output_schema": {},
                "confidence_score": 0.9,
                "is_flagged": False,
                "flag_rationale": None,
                "requires_approval": False,
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
        "session_id": "sess-test-1",
        "user_id": "user-1",
        "final_response": None,
        "citations": [],
        "error": None,
    }
    state.update(overrides)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.1 — validate_step_pre
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateStepPre:
    def test_passes_when_agent_available_and_action_allowed(self):
        from src.orchestrator.nodes.validate_step_pre import validate_step_pre
        state = _base_state()
        result = validate_step_pre(state)
        step_results = result["step_results"]
        assert len(step_results) == 1
        assert step_results[0]["pre_validation_failed"] is False
        assert step_results[0]["pre_validation_error"] is None

    def test_fails_when_no_agent_for_category(self):
        from src.orchestrator.nodes.validate_step_pre import validate_step_pre
        state = _base_state()
        state["execution_plan"][0]["expected_category"] = "nonexistent_category"
        result = validate_step_pre(state)
        step_results = result["step_results"]
        assert step_results[0]["pre_validation_failed"] is True
        assert "nonexistent_category" in step_results[0]["pre_validation_error"]

    def test_fails_when_action_not_in_allowed_actions(self):
        from src.orchestrator.nodes.validate_step_pre import validate_step_pre
        state = _base_state()
        state["execution_plan"][0]["tool_name"] = "delete_everything"
        result = validate_step_pre(state)
        step_results = result["step_results"]
        assert step_results[0]["pre_validation_failed"] is True
        assert "delete_everything" in step_results[0]["pre_validation_error"]

    def test_fails_when_required_inputs_missing(self):
        from src.orchestrator.nodes.validate_step_pre import validate_step_pre
        state = _base_state()
        state["execution_plan"][0]["tool_inputs"] = {}
        state["execution_plan"][0]["expected_output_schema"] = {
            "required": ["namespace", "metric"]
        }
        result = validate_step_pre(state)
        step_results = result["step_results"]
        assert step_results[0]["pre_validation_failed"] is True
        assert "namespace" in step_results[0]["pre_validation_error"]

    def test_appends_to_existing_step_results(self):
        from src.orchestrator.nodes.validate_step_pre import validate_step_pre
        existing = [{"step_index": -1, "pre_validation_failed": False}]
        state = _base_state(step_results=existing)
        result = validate_step_pre(state)
        assert len(result["step_results"]) == 2

    def test_retry_count_initialized_to_zero(self):
        from src.orchestrator.nodes.validate_step_pre import validate_step_pre
        state = _base_state()
        result = validate_step_pre(state)
        assert result["step_results"][0]["retry_count"] == 0

    def test_empty_tool_name_passes_action_check(self):
        """Empty tool_name should not fail the allowedActions check."""
        from src.orchestrator.nodes.validate_step_pre import validate_step_pre
        state = _base_state()
        state["execution_plan"][0]["tool_name"] = ""
        result = validate_step_pre(state)
        # Should pass since empty tool_name skips the action check
        assert result["step_results"][0]["pre_validation_failed"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.2 — invoke_subagent
# ─────────────────────────────────────────────────────────────────────────────

class TestInvokeSubagent:
    def test_invokes_mock_agent_and_returns_result(self):
        from src.orchestrator.nodes.invoke_subagent import invoke_subagent
        state = _base_state(
            step_results=[{
                "step_index": 0,
                "pre_validation_failed": False,
                "pre_validation_error": None,
                "retry_count": 0,
                "post_validation_passed": False,
            }]
        )
        result = invoke_subagent(state)
        assert result["error"] is None
        step_results = result["step_results"]
        assert len(step_results) == 1
        agent_result = step_results[0].get("agent_result", {})
        assert "result" in agent_result
        assert agent_result["confidence_score"] == 0.85

    def test_increments_hop_count(self):
        from src.orchestrator.nodes.invoke_subagent import invoke_subagent
        state = _base_state(
            hop_count=3,
            step_results=[{
                "step_index": 0,
                "pre_validation_failed": False,
                "pre_validation_error": None,
                "retry_count": 0,
                "post_validation_passed": False,
            }]
        )
        result = invoke_subagent(state)
        assert result["hop_count"] == 4

    def test_appends_step_key_to_visited_steps(self):
        from src.orchestrator.nodes.invoke_subagent import invoke_subagent
        state = _base_state(
            step_results=[{
                "step_index": 0,
                "pre_validation_failed": False,
                "pre_validation_error": None,
                "retry_count": 0,
                "post_validation_passed": False,
            }]
        )
        result = invoke_subagent(state)
        assert len(result["visited_steps"]) == 1

    def test_updates_context_window_with_agent_output(self):
        from src.orchestrator.nodes.invoke_subagent import invoke_subagent
        state = _base_state(
            step_results=[{
                "step_index": 0,
                "pre_validation_failed": False,
                "pre_validation_error": None,
                "retry_count": 0,
                "post_validation_passed": False,
            }]
        )
        result = invoke_subagent(state)
        assert len(result["context_window"]) == 1
        assert result["context_window"][0]["type"] == "agent_output"

    def test_capability_match_selects_best_agent(self):
        from src.orchestrator.nodes.invoke_subagent import _match_agent
        agents = [
            {"agentId": "a1", "capabilityDescriptor": "query metrics and logs"},
            {"agentId": "a2", "capabilityDescriptor": "search code repositories"},
        ]
        best = _match_agent(agents, "query CloudWatch metrics")
        assert best["agentId"] == "a1"

    def test_capability_match_returns_none_for_empty_list(self):
        from src.orchestrator.nodes.invoke_subagent import _match_agent
        assert _match_agent([], "anything") is None

    def test_halts_on_hop_limit(self):
        from src.orchestrator.nodes.invoke_subagent import invoke_subagent
        state = _base_state(hop_count=10)
        result = invoke_subagent(state)
        assert result["error"]["type"] == "hop_limit_exceeded"


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.3 — validate_step_post
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateStepPost:
    def _state_with_result(self, agent_result, **overrides):
        step_results = [{
            "step_index": 0,
            "pre_validation_failed": False,
            "pre_validation_error": None,
            "retry_count": 0,
            "post_validation_passed": False,
            "agent_result": agent_result,
        }]
        return _base_state(step_results=step_results, **overrides)

    def test_passes_when_result_and_confidence_above_threshold(self):
        from src.orchestrator.nodes.validate_step_post import validate_step_post
        state = self._state_with_result({"result": "ok", "confidence_score": 0.85})
        result = validate_step_post(state)
        assert result["step_results"][0]["post_validation_passed"] is True

    def test_fails_when_confidence_below_threshold(self):
        from src.orchestrator.nodes.validate_step_post import validate_step_post
        state = self._state_with_result({"result": "ok", "confidence_score": 0.5})
        result = validate_step_post(state)
        assert result["step_results"][0]["post_validation_passed"] is False
        assert result["step_results"][0]["retry_count"] == 1

    def test_fails_when_result_field_missing(self):
        from src.orchestrator.nodes.validate_step_post import validate_step_post
        state = self._state_with_result({"confidence_score": 0.9})
        result = validate_step_post(state)
        assert result["step_results"][0]["post_validation_passed"] is False
        assert result["step_results"][0]["retry_count"] == 1

    def test_fails_when_confidence_score_field_missing(self):
        from src.orchestrator.nodes.validate_step_post import validate_step_post
        state = self._state_with_result({"result": "ok"})
        result = validate_step_post(state)
        assert result["step_results"][0]["post_validation_passed"] is False

    def test_advances_step_index_when_more_steps_remain(self):
        from src.orchestrator.nodes.validate_step_post import validate_step_post
        plan = [
            {"step_index": 0, "tool_name": "tool_a", "tool_inputs": {}, "expected_output_schema": {}},
            {"step_index": 1, "tool_name": "tool_b", "tool_inputs": {}, "expected_output_schema": {}},
        ]
        state = self._state_with_result(
            {"result": "ok", "confidence_score": 0.9},
            execution_plan=plan,
            current_step_index=0,
        )
        result = validate_step_post(state)
        assert result["current_step_index"] == 1

    def test_does_not_advance_step_index_on_last_step(self):
        from src.orchestrator.nodes.validate_step_post import validate_step_post
        state = self._state_with_result(
            {"result": "ok", "confidence_score": 0.9},
            current_step_index=0,
        )
        result = validate_step_post(state)
        assert result["current_step_index"] == 0

    def test_increments_retry_count_on_failure(self):
        from src.orchestrator.nodes.validate_step_post import validate_step_post
        step_results = [{
            "step_index": 0,
            "pre_validation_failed": False,
            "pre_validation_error": None,
            "retry_count": 1,
            "post_validation_passed": False,
            "agent_result": {"result": "ok", "confidence_score": 0.3},
        }]
        state = _base_state(step_results=step_results)
        result = validate_step_post(state)
        assert result["step_results"][0]["retry_count"] == 2

    def test_returns_state_unchanged_when_no_step_results(self):
        from src.orchestrator.nodes.validate_step_post import validate_step_post
        state = _base_state(step_results=[])
        result = validate_step_post(state)
        assert result == state


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.4 — aggregate_results
# ─────────────────────────────────────────────────────────────────────────────

class TestAggregateResults:
    def test_returns_final_response(self):
        from src.orchestrator.nodes.aggregate_results import aggregate_results
        state = _base_state()
        result = aggregate_results(state)
        assert result["final_response"] is not None
        assert len(result["final_response"]) > 0

    def test_prepends_unverified_notice_when_no_live_data(self):
        from src.orchestrator.nodes.aggregate_results import aggregate_results, UNVERIFIED_NOTICE
        state = _base_state(step_results=[])
        result = aggregate_results(state)
        assert UNVERIFIED_NOTICE in result["final_response"]

    def test_no_unverified_notice_when_live_data_present(self):
        from src.orchestrator.nodes.aggregate_results import aggregate_results, UNVERIFIED_NOTICE
        step_results = [{
            "step_index": 0,
            "pre_validation_failed": False,
            "agent_result": {"result": "live data", "confidence_score": 0.9},
        }]
        state = _base_state(step_results=step_results)
        result = aggregate_results(state)
        assert UNVERIFIED_NOTICE not in result["final_response"]

    def test_prepends_uncertainty_notice_when_confidence_below_0_8(self):
        from src.orchestrator.nodes.aggregate_results import aggregate_results
        step_results = [{
            "step_index": 0,
            "pre_validation_failed": False,
            "agent_result": {"result": "data", "confidence_score": 0.5},
        }]
        state = _base_state(step_results=step_results)
        result = aggregate_results(state)
        assert "Uncertainty Notice" in result["final_response"]
        assert result["confidence_score"] == pytest.approx(0.5)

    def test_no_uncertainty_notice_when_confidence_above_0_8(self):
        from src.orchestrator.nodes.aggregate_results import aggregate_results
        step_results = [{
            "step_index": 0,
            "pre_validation_failed": False,
            "agent_result": {"result": "data", "confidence_score": 0.9},
        }]
        state = _base_state(step_results=step_results)
        result = aggregate_results(state)
        assert "Uncertainty Notice" not in result["final_response"]

    def test_default_confidence_is_0_5_when_no_steps(self):
        from src.orchestrator.nodes.aggregate_results import aggregate_results
        state = _base_state(step_results=[])
        result = aggregate_results(state)
        assert result["confidence_score"] == pytest.approx(0.5)

    def test_builds_citations_from_kb_documents(self):
        # Req 8.5: aggregate_results reads citations from state["citations"] (populated by retrieve_knowledge)
        from src.orchestrator.nodes.aggregate_results import aggregate_results
        from langchain_core.documents import Document

        doc = Document(
            page_content="some content",
            metadata={"title": "Runbook A", "url": "https://wiki.example.com/runbook-a"},
        )
        pre_built_citations = [{"title": "Runbook A", "url": "https://wiki.example.com/runbook-a", "timestamp": "2024-01-01T00:00:00+00:00"}]
        state = _base_state(context_window=[doc], citations=pre_built_citations)
        result = aggregate_results(state)
        assert len(result["citations"]) == 1
        assert result["citations"][0]["title"] == "Runbook A"
        assert result["citations"][0]["url"] == "https://wiki.example.com/runbook-a"

    def test_citations_empty_when_no_kb_docs(self):
        from src.orchestrator.nodes.aggregate_results import aggregate_results
        state = _base_state(context_window=[], citations=[])
        result = aggregate_results(state)
        assert result["citations"] == []


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.5 — scan_output_guardrails
# ─────────────────────────────────────────────────────────────────────────────

class TestScanOutputGuardrails:
    def test_passthrough_when_no_guardrail_id(self, monkeypatch):
        from src.orchestrator.nodes.scan_output_guardrails import scan_output_guardrails
        monkeypatch.delenv("GUARDRAIL_ID", raising=False)
        state = _base_state(final_response="some response")
        result = scan_output_guardrails(state)
        assert result is state  # exact same object — no copy

    def test_passthrough_when_guardrail_id_empty(self, monkeypatch):
        from src.orchestrator.nodes.scan_output_guardrails import scan_output_guardrails
        monkeypatch.setenv("GUARDRAIL_ID", "")
        state = _base_state(final_response="some response")
        result = scan_output_guardrails(state)
        assert result["final_response"] == "some response"

    def test_passthrough_when_final_response_empty(self, monkeypatch):
        from src.orchestrator.nodes.scan_output_guardrails import scan_output_guardrails
        monkeypatch.setenv("GUARDRAIL_ID", "gr-12345")
        state = _base_state(final_response="")
        result = scan_output_guardrails(state)
        assert result is state


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.6 — write_execution_log
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteExecutionLog:
    def test_writes_one_entry_per_step(self):
        from src.orchestrator.nodes.write_execution_log import write_execution_log
        from src.storage.dynamodb import _MOCK_STORE

        # Clear execution-logs before test
        _MOCK_STORE["execution-logs"].clear()

        step_results = [
            {
                "step_index": 0,
                "pre_validation_failed": False,
                "post_validation_passed": True,
                "retry_count": 0,
                "agent_id": "mock-cloudwatch-agent",
                "tool_name": "get_metric_statistics",
                "agent_result": {"result": "data", "confidence_score": 0.85},
            }
        ]
        state = _base_state(step_results=step_results, session_id="sess-log-test")
        write_execution_log(state)

        entries = list(_MOCK_STORE["execution-logs"].values())
        assert len(entries) == 1
        entry = entries[0]
        assert entry["requestId"] == "sess-log-test"
        assert entry["stepIndex"] == 0
        assert entry["validationResult"] == "PASS"

    def test_sets_90_day_ttl(self):
        from src.orchestrator.nodes.write_execution_log import write_execution_log, _TTL_90_DAYS
        from src.storage.dynamodb import _MOCK_STORE

        _MOCK_STORE["execution-logs"].clear()

        step_results = [{
            "step_index": 0,
            "pre_validation_failed": False,
            "post_validation_passed": True,
            "retry_count": 0,
            "agent_result": {"result": "ok", "confidence_score": 0.9},
        }]
        state = _base_state(step_results=step_results)
        before = int(time.time())
        write_execution_log(state)
        after = int(time.time())

        entry = list(_MOCK_STORE["execution-logs"].values())[0]
        assert before + _TTL_90_DAYS <= entry["ttl"] <= after + _TTL_90_DAYS

    def test_redacts_sensitive_tool_inputs(self):
        from src.orchestrator.nodes.write_execution_log import write_execution_log
        from src.storage.dynamodb import _MOCK_STORE

        _MOCK_STORE["execution-logs"].clear()

        state = _base_state(
            execution_plan=[{
                "step_index": 0,
                "description": "test",
                "expected_category": "monitoring_query",
                "required_capability": "metrics",
                "agent_id": "mock-cloudwatch-agent",
                "tool_name": "get_metric_statistics",
                "tool_inputs": {
                    "namespace": "AWS/EC2",
                    "api_key": "super-secret-key",
                    "password": "hunter2",
                    "token": "abc123",
                },
                "expected_output_schema": {},
                "confidence_score": 0.9,
                "is_flagged": False,
                "flag_rationale": None,
                "requires_approval": False,
            }],
            step_results=[{
                "step_index": 0,
                "pre_validation_failed": False,
                "post_validation_passed": True,
                "retry_count": 0,
                "agent_result": {"result": "ok", "confidence_score": 0.9},
            }],
        )
        write_execution_log(state)

        entry = list(_MOCK_STORE["execution-logs"].values())[0]
        inputs = entry["toolInputs"]
        assert inputs["namespace"] == "AWS/EC2"
        assert inputs["api_key"] == "[REDACTED]"
        assert inputs["password"] == "[REDACTED]"
        assert inputs["token"] == "[REDACTED]"

    def test_validation_result_fail_on_pre_validation_failure(self):
        from src.orchestrator.nodes.write_execution_log import write_execution_log
        from src.storage.dynamodb import _MOCK_STORE

        _MOCK_STORE["execution-logs"].clear()

        step_results = [{
            "step_index": 0,
            "pre_validation_failed": True,
            "pre_validation_error": "No agent found",
            "post_validation_passed": False,
            "retry_count": 0,
            "agent_result": {},
        }]
        state = _base_state(step_results=step_results)
        write_execution_log(state)

        entry = list(_MOCK_STORE["execution-logs"].values())[0]
        assert entry["validationResult"] == "FAIL"

    def test_validation_result_retry_on_retry_count(self):
        from src.orchestrator.nodes.write_execution_log import write_execution_log
        from src.storage.dynamodb import _MOCK_STORE

        _MOCK_STORE["execution-logs"].clear()

        step_results = [{
            "step_index": 0,
            "pre_validation_failed": False,
            "post_validation_passed": False,
            "retry_count": 1,
            "agent_result": {"result": "ok", "confidence_score": 0.5},
        }]
        state = _base_state(step_results=step_results)
        write_execution_log(state)

        entry = list(_MOCK_STORE["execution-logs"].values())[0]
        assert entry["validationResult"] == "RETRY"

    def test_returns_state_unchanged(self):
        from src.orchestrator.nodes.write_execution_log import write_execution_log
        state = _base_state(step_results=[])
        result = write_execution_log(state)
        assert result is state


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.7 — prompt_user
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptUser:
    def test_consolidates_missing_inputs_into_single_prompt(self):
        from src.orchestrator.nodes.prompt_user import prompt_user
        missing = [
            {"name": "service_name", "description": "The AWS service name", "example": "ec2"},
            {"name": "time_range", "description": "Time range for the query"},
        ]
        state = _base_state(missing_inputs=missing)
        result = prompt_user(state)
        prompt = result["clarifying_question"]
        assert "service_name" in prompt
        assert "time_range" in prompt
        assert "ec2" in prompt

    def test_clears_missing_inputs_after_consolidation(self):
        from src.orchestrator.nodes.prompt_user import prompt_user
        missing = [{"name": "env", "description": "Environment"}]
        state = _base_state(missing_inputs=missing)
        result = prompt_user(state)
        assert result["missing_inputs"] == []

    def test_surfaces_clarifying_question_when_set(self):
        from src.orchestrator.nodes.prompt_user import prompt_user
        state = _base_state(clarifying_question="Which environment are you asking about?")
        result = prompt_user(state)
        assert result["clarifying_question"] == "Which environment are you asking about?"

    def test_missing_inputs_takes_priority_over_clarifying_question(self):
        from src.orchestrator.nodes.prompt_user import prompt_user
        missing = [{"name": "region", "description": "AWS region"}]
        state = _base_state(
            missing_inputs=missing,
            clarifying_question="What do you mean?",
        )
        result = prompt_user(state)
        # Should consolidate missing inputs
        assert "region" in result["clarifying_question"]
        assert result["missing_inputs"] == []

    def test_returns_state_unchanged_when_nothing_to_prompt(self):
        from src.orchestrator.nodes.prompt_user import prompt_user
        state = _base_state(missing_inputs=[], clarifying_question=None)
        result = prompt_user(state)
        assert result is state

    def test_handles_string_missing_inputs(self):
        from src.orchestrator.nodes.prompt_user import prompt_user
        state = _base_state(missing_inputs=["service_name", "region"])
        result = prompt_user(state)
        prompt = result["clarifying_question"]
        assert "service_name" in prompt
        assert "region" in prompt


# ─────────────────────────────────────────────────────────────────────────────
# MockSubAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestMockSubAgent:
    def test_returns_result_with_confidence_0_85(self):
        from src.agents.mock.agent import MockSubAgent
        agent = MockSubAgent()
        result = agent.invoke("test task", [], {})
        assert result["confidence_score"] == 0.85
        assert result["result"].startswith("[MOCK]")
        assert result["error"] is None

    def test_includes_sources(self):
        from src.agents.mock.agent import MockSubAgent
        agent = MockSubAgent()
        result = agent.invoke("task", [], {"key": "val"})
        assert len(result["sources"]) == 1
        assert "title" in result["sources"][0]
        assert "url" in result["sources"][0]

    def test_task_name_in_result(self):
        from src.agents.mock.agent import MockSubAgent
        agent = MockSubAgent()
        result = agent.invoke("my specific task", [], {})
        assert "my specific task" in result["result"]
