"""
Unit tests for src/guardrails/bedrock.py

Tests:
  - test_passthrough_when_guardrail_id_unset
  - test_guardrail_config_when_id_set
  - test_log_violation_writes_all_fields
  - test_log_violation_ttl_is_90_days

Feature: feature-02-foundation-infra
"""
from __future__ import annotations

import os
import sys
import time
from types import ModuleType
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub langchain_aws before importing the module under test so tests run
# without real AWS credentials or the full langchain-aws install.
# ---------------------------------------------------------------------------
if "langchain_aws" not in sys.modules:
    _stub = ModuleType("langchain_aws")
    _stub.ChatBedrock = MagicMock()
    sys.modules["langchain_aws"] = _stub

os.environ.setdefault("MOCK_STORAGE", "true")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_90_DAYS_SECONDS = 90 * 24 * 60 * 60


def _import_module():
    """Re-import bedrock module so env-var changes take effect cleanly."""
    import importlib
    import src.guardrails.bedrock as mod
    importlib.reload(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetGuardrailedLlm:
    def test_passthrough_when_guardrail_id_unset(self, monkeypatch):
        """When BEDROCK_GUARDRAIL_ID is not set, ChatBedrock is constructed
        without a 'guardrails' kwarg."""
        monkeypatch.delenv("BEDROCK_GUARDRAIL_ID", raising=False)

        mock_cls = MagicMock()
        with patch("src.guardrails.bedrock.ChatBedrock", mock_cls):
            from src.guardrails.bedrock import get_guardrailed_llm
            get_guardrailed_llm()

        _, kwargs = mock_cls.call_args
        assert "guardrails" not in kwargs, (
            "ChatBedrock should not receive 'guardrails' when BEDROCK_GUARDRAIL_ID is unset"
        )

    def test_guardrail_config_when_id_set(self, monkeypatch):
        """When BEDROCK_GUARDRAIL_ID=test-id, ChatBedrock receives guardrails
        with guardrailIdentifier == 'test-id'."""
        monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "test-id")

        mock_cls = MagicMock()
        with patch("src.guardrails.bedrock.ChatBedrock", mock_cls):
            from src.guardrails.bedrock import get_guardrailed_llm
            get_guardrailed_llm()

        _, kwargs = mock_cls.call_args
        assert "guardrails" in kwargs, "ChatBedrock must receive 'guardrails' when BEDROCK_GUARDRAIL_ID is set"
        assert kwargs["guardrails"]["guardrailIdentifier"] == "test-id"

    def test_model_id_uses_env_var(self, monkeypatch):
        """BEDROCK_MODEL_ID env var is forwarded as model_id."""
        monkeypatch.delenv("BEDROCK_GUARDRAIL_ID", raising=False)
        monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

        mock_cls = MagicMock()
        with patch("src.guardrails.bedrock.ChatBedrock", mock_cls):
            from src.guardrails.bedrock import get_guardrailed_llm
            get_guardrailed_llm()

        _, kwargs = mock_cls.call_args
        assert kwargs["model_id"] == "anthropic.claude-3-haiku-20240307-v1:0"

    def test_explicit_model_id_overrides_env(self, monkeypatch):
        """Explicit model_id argument takes precedence over BEDROCK_MODEL_ID."""
        monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

        mock_cls = MagicMock()
        with patch("src.guardrails.bedrock.ChatBedrock", mock_cls):
            from src.guardrails.bedrock import get_guardrailed_llm
            get_guardrailed_llm(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0")

        _, kwargs = mock_cls.call_args
        assert kwargs["model_id"] == "anthropic.claude-3-5-sonnet-20241022-v2:0"


class TestLogViolation:
    def test_log_violation_writes_all_fields(self):
        """log_violation() calls put_item exactly once with all required fields."""
        captured: list[dict] = []

        def fake_put_item(table_name: str, item: dict) -> None:
            captured.append({"table_name": table_name, "item": item})

        with patch("src.guardrails.bedrock.put_item", fake_put_item):
            from src.guardrails.bedrock import log_violation
            log_violation(
                violation_type="INJECTION",
                severity="HIGH",
                redacted_content="ignore previous instructions",
                request_id="req-abc-123",
                policy_version="DRAFT",
            )

        assert len(captured) == 1, "put_item must be called exactly once"

        call_args = captured[0]
        assert call_args["table_name"] == "guardrail-violations"

        item = call_args["item"]
        required_fields = {
            "violationId",
            "violationType",
            "severity",
            "redactedContent",
            "requestId",
            "policyVersion",
            "timestamp",
            "ttl",
        }
        missing = required_fields - item.keys()
        assert not missing, f"Item is missing required fields: {missing}"

        # Spot-check values
        assert item["violationType"] == "INJECTION"
        assert item["severity"] == "HIGH"
        assert item["redactedContent"] == "ignore previous instructions"
        assert item["requestId"] == "req-abc-123"
        assert item["policyVersion"] == "DRAFT"

    def test_log_violation_ttl_is_90_days(self):
        """The ttl field is within 1 second of int(time.time()) + 90 days."""
        captured: list[dict] = []

        def fake_put_item(table_name: str, item: dict) -> None:
            captured.append(item)

        before = int(time.time())

        with patch("src.guardrails.bedrock.put_item", fake_put_item):
            from src.guardrails.bedrock import log_violation
            log_violation(
                violation_type="PII",
                severity="MEDIUM",
                redacted_content="{EMAIL} was found",
                request_id="req-xyz-456",
            )

        after = int(time.time())

        item = captured[0]
        expected_min = before + _90_DAYS_SECONDS
        expected_max = after + _90_DAYS_SECONDS

        assert expected_min <= item["ttl"] <= expected_max + 1, (
            f"ttl {item['ttl']} is not within 1 second of 90 days from now "
            f"(expected range: {expected_min}–{expected_max + 1})"
        )

    def test_log_violation_violation_id_is_uuid(self):
        """violationId must be a valid UUID string."""
        import uuid

        captured: list[dict] = []

        def fake_put_item(table_name: str, item: dict) -> None:
            captured.append(item)

        with patch("src.guardrails.bedrock.put_item", fake_put_item):
            from src.guardrails.bedrock import log_violation
            log_violation(
                violation_type="CONTENT",
                severity="LOW",
                redacted_content="some content",
                request_id="req-001",
            )

        item = captured[0]
        # Should not raise ValueError
        parsed = uuid.UUID(item["violationId"])
        assert str(parsed) == item["violationId"]

    def test_log_violation_timestamp_is_utc_iso(self):
        """timestamp must be a UTC ISO-8601 string."""
        from datetime import datetime

        captured: list[dict] = []

        def fake_put_item(table_name: str, item: dict) -> None:
            captured.append(item)

        with patch("src.guardrails.bedrock.put_item", fake_put_item):
            from src.guardrails.bedrock import log_violation
            log_violation(
                violation_type="GROUNDING",
                severity="HIGH",
                redacted_content="hallucinated content",
                request_id="req-002",
            )

        item = captured[0]
        # Should parse without error
        dt = datetime.fromisoformat(item["timestamp"])
        assert dt.tzinfo is not None, "timestamp must be timezone-aware"
