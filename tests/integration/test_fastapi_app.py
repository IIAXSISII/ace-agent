"""
Integration tests for the FastAPI app — task 14.5.
Feature: feature-01-core-orchestrator

Tests:
  (a) GET /ping returns {"status": "Healthy"}
  (b) POST /invocations with MOCK_STORAGE=true and MOCK_PROMPTS=true produces
      a non-empty final_response and at least one execution-logs put_item call
  (c) GET /metrics returns Prometheus text with orchestrator_requests_total present
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
# Pattern mirrors tests/integration/test_graph_integration.py

if "langchain_aws" not in sys.modules:
    _stub_lc_aws = ModuleType("langchain_aws")
    _stub_lc_aws.ChatBedrock = MagicMock()  # type: ignore[attr-defined]
    _stub_lc_aws.AmazonKnowledgeBasesRetriever = MagicMock()  # type: ignore[attr-defined]
    sys.modules["langchain_aws"] = _stub_lc_aws

if "langgraph_checkpoint_aws" not in sys.modules:
    _stub_lgcaws = ModuleType("langgraph_checkpoint_aws")
    _stub_lgcaws.AgentCoreMemorySaver = MagicMock()  # type: ignore[attr-defined]
    sys.modules["langgraph_checkpoint_aws"] = _stub_lgcaws

# Stub opentelemetry core + extensions used by otel.py (imported transitively via main.py)
# The core opentelemetry packages are not installed in the test venv, so we stub them all.
for _mod in [
    "opentelemetry",
    "opentelemetry.trace",
    "opentelemetry.sdk",
    "opentelemetry.sdk.trace",
    "opentelemetry.sdk.trace.export",
    "opentelemetry.sdk.extension",
    "opentelemetry.sdk.extension.aws",
    "opentelemetry.sdk.extension.aws.trace",
    "opentelemetry.propagator",
    "opentelemetry.propagator.aws_xray",
    "opentelemetry.exporter",
    "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto",
    "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
]:
    if _mod not in sys.modules:
        _s = ModuleType(_mod)
        # Core stubs
        _s.trace = MagicMock()  # type: ignore[attr-defined]
        _s.set_tracer_provider = MagicMock()  # type: ignore[attr-defined]
        # SDK stubs
        _s.TracerProvider = MagicMock()  # type: ignore[attr-defined]
        _s.BatchSpanProcessor = MagicMock()  # type: ignore[attr-defined]
        # AWS extension stubs
        _s.AwsXRayIdGenerator = MagicMock()  # type: ignore[attr-defined]
        _s.AwsXRayPropagator = MagicMock()  # type: ignore[attr-defined]
        # OTLP exporter stub
        _s.OTLPSpanExporter = MagicMock()  # type: ignore[attr-defined]
        sys.modules[_mod] = _s

if "langfuse" not in sys.modules:
    _stub_lf = ModuleType("langfuse")
    sys.modules["langfuse"] = _stub_lf
if "langfuse.langchain" not in sys.modules:
    _stub_lf_lc = ModuleType("langfuse.langchain")
    _stub_lf_lc.CallbackHandler = MagicMock()  # type: ignore[attr-defined]
    sys.modules["langfuse.langchain"] = _stub_lf_lc

if "chainlit" not in sys.modules:
    _stub_cl = ModuleType("chainlit")
    sys.modules["chainlit"] = _stub_cl

# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm_response(payload: dict) -> MagicMock:
    """Return a mock that looks like a ChatBedrock response."""
    mock = MagicMock()
    mock.content = json.dumps(payload)
    return mock


def _classify_payload(confidence: float = 0.9) -> dict:
    return {
        "task_category": "monitoring_query",
        "entities": {"service": "EC2"},
        "confidence_score": confidence,
        "clarifying_question": None,
    }


def _detect_payload() -> dict:
    return {"missing_inputs": []}


def _plan_payload() -> dict:
    return {
        "execution_plan": [
            {
                "step_index": 0,
                "description": "Step 0: query metrics",
                "expected_category": "monitoring_query",
                "required_capability": "query metrics",
                "agent_id": None,
                "tool_name": "get_metric_statistics",
                "tool_inputs": {"namespace": "AWS/EC2"},
                "expected_output_schema": {},
                "confidence_score": 0.9,
                "is_flagged": False,
                "flag_rationale": None,
                "requires_approval": False,
            }
        ]
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_client():
    """
    Build a TestClient for the FastAPI app with MemorySaver patched in.
    Scope is module-level so the app is only imported once per test module.
    """
    from langgraph.checkpoint.memory import MemorySaver
    from fastapi.testclient import TestClient

    with patch("src.orchestrator.memory.get_checkpointer", return_value=MemorySaver()):
        from src.orchestrator.main import app
        client = TestClient(app, raise_server_exceptions=True)
        yield client


# ── (a) GET /ping ─────────────────────────────────────────────────────────────

class TestPing:
    """(a) GET /ping must return 200 {"status": "Healthy"}."""

    def test_ping_status_code(self, test_client):
        response = test_client.get("/ping")
        assert response.status_code == 200

    def test_ping_response_body(self, test_client):
        response = test_client.get("/ping")
        assert response.json() == {"status": "Healthy"}


# ── (b) POST /invocations ─────────────────────────────────────────────────────

class TestInvocations:
    """
    (b) POST /invocations with MOCK_STORAGE=true and MOCK_PROMPTS=true must:
        - return 200
        - include a non-empty final_response
        - have called put_item at least once (execution-logs entry written)
    """

    def _invoke(self, test_client):
        """Run a full happy-path invocation with mocked LLM calls."""
        with patch("src.orchestrator.nodes.classify_request.ChatBedrock") as MockClassify, \
             patch("src.orchestrator.nodes.detect_missing_inputs.ChatBedrock") as MockDetect, \
             patch("src.orchestrator.nodes.generate_plan.ChatBedrock") as MockPlan, \
             patch("src.orchestrator.nodes.write_execution_log.put_item") as mock_put:

            MockClassify.return_value.invoke.return_value = _llm_response(_classify_payload())
            MockDetect.return_value.invoke.return_value = _llm_response(_detect_payload())
            MockPlan.return_value.invoke.return_value = _llm_response(_plan_payload())

            payload = {
                "raw_request": "investigate high CPU on prod EC2",
                "session_id": "test-session-fastapi",
                "user_id": "test-user",
            }
            response = test_client.post("/invocations", json=payload)
            return response, mock_put

    def test_invocations_status_code(self, test_client):
        response, _ = self._invoke(test_client)
        assert response.status_code == 200

    def test_invocations_final_response_non_empty(self, test_client):
        response, _ = self._invoke(test_client)
        body = response.json()
        assert "final_response" in body
        assert body["final_response"] is not None
        assert len(body["final_response"]) > 0

    def test_invocations_execution_log_written(self, test_client):
        _, mock_put = self._invoke(test_client)
        assert mock_put.called, "put_item must be called at least once for execution-logs"

    def test_invocations_response_contains_session_id(self, test_client):
        response, _ = self._invoke(test_client)
        body = response.json()
        assert body.get("session_id") == "test-session-fastapi"

    def test_invocations_no_error_in_response(self, test_client):
        response, _ = self._invoke(test_client)
        body = response.json()
        assert body.get("error") is None


# ── (c) GET /metrics ──────────────────────────────────────────────────────────

class TestMetrics:
    """
    (c) GET /metrics must:
        - return 200
        - have content-type containing "text/plain" (Prometheus format)
        - include "orchestrator_requests_total" in the body
    """

    def test_metrics_status_code(self, test_client):
        response = test_client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_content_type_is_text_plain(self, test_client):
        response = test_client.get("/metrics")
        assert "text/plain" in response.headers.get("content-type", "")

    def test_metrics_contains_orchestrator_requests_total(self, test_client):
        response = test_client.get("/metrics")
        assert "orchestrator_requests_total" in response.text
