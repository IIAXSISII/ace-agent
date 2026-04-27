"""
Property-Based Tests for feature-02-foundation-infra — Guardrails Correctness Properties.

Properties tested:
  30 — PII Redaction Completeness
  31 — Prompt Injection Blocking
  32 — Guardrail Violation Log Completeness

Feature: feature-02-foundation-infra
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Stub langchain_aws before any module under test is imported so tests run
# without real AWS credentials or the full langchain-aws install.
# ---------------------------------------------------------------------------
if "langchain_aws" not in sys.modules:
    _stub = ModuleType("langchain_aws")
    _stub.ChatBedrock = MagicMock()
    sys.modules["langchain_aws"] = _stub

os.environ.setdefault("MOCK_STORAGE", "true")
# Note: BEDROCK_GUARDRAIL_ID is set per-test via monkeypatch/patch, not at module level
# to avoid polluting other tests that test the passthrough (unset) behavior.

# ---------------------------------------------------------------------------
# Import the modules under test after stubs are in place
# ---------------------------------------------------------------------------
from src.guardrails.bedrock import log_violation  # noqa: E402
from src.orchestrator.nodes.scan_output_guardrails import (  # noqa: E402
    _GUARDRAIL_BLOCKED_RESPONSE,
    scan_output_guardrails,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_guardrail_env(monkeypatch):
    """Ensure BEDROCK_GUARDRAIL_ID is set for all tests in this module."""
    monkeypatch.setenv("BEDROCK_GUARDRAIL_ID", "test-guardrail-id")


# ---------------------------------------------------------------------------
# PII pattern helpers
# ---------------------------------------------------------------------------

_UPPER = st.characters(whitelist_categories=("Lu",), whitelist_characters="ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_LOWER = st.characters(whitelist_categories=("Ll",), whitelist_characters="abcdefghijklmnopqrstuvwxyz")
_ALNUM_UPPER = st.sampled_from(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))
_WORD = st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="_")


def _st_name() -> st.SearchStrategy[str]:
    """Generate a realistic full name: 'Firstname Lastname'."""
    first = st.builds(
        lambda c, rest: c + rest,
        _UPPER,
        st.text(_LOWER, min_size=2, max_size=8),
    )
    last = st.builds(
        lambda c, rest: c + rest,
        _UPPER,
        st.text(_LOWER, min_size=2, max_size=8),
    )
    return st.builds(lambda f, ln: f"{f} {ln}", first, last)


def _st_email() -> st.SearchStrategy[str]:
    """Generate an email address: 'user@domain.tld'."""
    local = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="."),
        min_size=3,
        max_size=10,
    )
    domain = st.text(
        alphabet=st.characters(whitelist_categories=("Ll",)),
        min_size=3,
        max_size=8,
    )
    tld = st.sampled_from(["com", "org", "net", "io"])
    return st.builds(lambda loc, d, t: f"{loc}@{d}.{t}", local, domain, tld)


def _st_api_key() -> st.SearchStrategy[str]:
    """Generate an AWS-style access key: 'AKIA' + 16 uppercase alphanumeric chars."""
    suffix = st.text(
        alphabet=st.sampled_from(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")),
        min_size=16,
        max_size=16,
    )
    return suffix.map(lambda s: f"AKIA{s}")


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def pii_containing_text() -> st.SearchStrategy[dict]:
    """
    Generate a dict with:
      - 'text': a string containing at least one injected PII value
      - 'pii_values': list of the raw PII strings injected into 'text'
      - 'pii_type': which PII type was injected ('name', 'email', 'api_key')
    """
    name_strategy = _st_name().map(
        lambda n: {"pii_type": "name", "pii_value": n, "placeholder": "{NAME}"}
    )
    email_strategy = _st_email().map(
        lambda e: {"pii_type": "email", "pii_value": e, "placeholder": "{EMAIL}"}
    )
    api_key_strategy = _st_api_key().map(
        lambda k: {"pii_type": "api_key", "pii_value": k, "placeholder": "{API_KEY}"}
    )

    pii_entry = st.one_of(name_strategy, email_strategy, api_key_strategy)

    prefix = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Zs")),
        min_size=0,
        max_size=40,
    )
    suffix = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Zs")),
        min_size=0,
        max_size=40,
    )

    return st.builds(
        lambda entry, pre, suf: {
            "text": f"{pre} {entry['pii_value']} {suf}".strip(),
            "pii_value": entry["pii_value"],
            "pii_type": entry["pii_type"],
            "placeholder": entry["placeholder"],
        },
        pii_entry,
        prefix,
        suffix,
    )


def injection_pattern_text() -> st.SearchStrategy[str]:
    """
    Generate strings containing at least one prompt injection pattern.
    Drawn from the canonical pool defined in the spec.
    """
    patterns = [
        "ignore previous instructions",
        "you are now",
        "disregard all prior",
        "jailbreak",
        "DAN mode",
    ]
    prefix = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Zs")),
        min_size=0,
        max_size=30,
    )
    suffix = st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Zs")),
        min_size=0,
        max_size=30,
    )
    return st.builds(
        lambda pattern, pre, suf: f"{pre} {pattern} {suf}".strip(),
        st.sampled_from(patterns),
        prefix,
        suffix,
    )


def violation_event() -> st.SearchStrategy[dict]:
    """
    Generate a dict suitable for passing as kwargs to log_violation().
    Fields: violation_type, severity, redacted_content, request_id.
    """
    return st.fixed_dictionaries({
        "violation_type": st.sampled_from(["PII", "INJECTION", "CONTENT", "GROUNDING"]),
        "severity": st.sampled_from(["HIGH", "MEDIUM", "LOW"]),
        "redacted_content": st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd", "Zs", "Po")),
            min_size=0,
            max_size=500,
        ),
        "request_id": st.builds(lambda: str(uuid.uuid4())),
    })


# ---------------------------------------------------------------------------
# Base state factory
# ---------------------------------------------------------------------------

def _base_state(final_response: str = "") -> dict:
    return {
        "raw_request": "test request",
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
        "session_id": "sess-pbt-guardrails",
        "user_id": "user-pbt",
        "final_response": final_response,
        "citations": [],
        "error": None,
    }


# =============================================================================
# Property 30: PII Redaction Completeness
# =============================================================================

@given(pii=pii_containing_text())
@settings(max_examples=50)
def test_property30_pii_redaction_completeness(pii):
    # Feature: feature-02-foundation-infra, Property 30: PII Redaction Completeness
    """
    For any LLM output containing a PII entity, the guardrails wrapper must
    replace the PII value with a typed placeholder before returning the response.
    The raw PII value must not appear in the returned final_response.
    """
    raw_text = pii["text"]
    pii_value = pii["pii_value"]
    placeholder = pii["placeholder"]

    # Simulate Bedrock Guardrails masking: replace the PII value with its placeholder
    masked_text = raw_text.replace(pii_value, placeholder)

    mock_response = MagicMock()
    mock_response.content = masked_text

    state = _base_state(final_response=raw_text)

    with patch("src.orchestrator.nodes.scan_output_guardrails.get_guardrailed_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response
        mock_llm_factory.return_value = mock_llm

        with patch("src.guardrails.bedrock.put_item"):
            result = scan_output_guardrails(state)

    # The raw PII value must not appear in the returned response
    assert pii_value not in result["final_response"], (
        f"Raw PII value '{pii_value}' ({pii['pii_type']}) must not appear in "
        f"final_response after guardrail masking. Got: {result['final_response']!r}"
    )

    # The placeholder must be present (guardrail did mask it)
    assert placeholder in result["final_response"], (
        f"Expected placeholder '{placeholder}' in final_response after masking. "
        f"Got: {result['final_response']!r}"
    )


@given(
    name=_st_name(),
    email=_st_email(),
    api_key=_st_api_key(),
)
@settings(max_examples=30)
def test_property30_multiple_pii_types_all_masked(name, email, api_key):
    # Feature: feature-02-foundation-infra, Property 30: PII Redaction Completeness (multi-entity)
    """
    When an LLM output contains multiple PII entities of different types,
    all must be masked in a single pass — none of the raw values may survive.
    """
    raw_text = f"Contact {name} at {email} using key {api_key}"
    masked_text = (
        raw_text
        .replace(name, "{NAME}")
        .replace(email, "{EMAIL}")
        .replace(api_key, "{API_KEY}")
    )

    mock_response = MagicMock()
    mock_response.content = masked_text

    state = _base_state(final_response=raw_text)

    with patch("src.orchestrator.nodes.scan_output_guardrails.get_guardrailed_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_response
        mock_llm_factory.return_value = mock_llm

        with patch("src.guardrails.bedrock.put_item"):
            result = scan_output_guardrails(state)

    for raw_pii in (name, email, api_key):
        assert raw_pii not in result["final_response"], (
            f"Raw PII '{raw_pii}' must not appear in final_response after multi-entity masking."
        )


# =============================================================================
# Property 31: Prompt Injection Blocking
# =============================================================================

@given(injection_text=injection_pattern_text())
@settings(max_examples=50)
def test_property31_prompt_injection_blocking(injection_text):
    # Feature: feature-02-foundation-infra, Property 31: Prompt Injection Blocking
    """
    For any input containing a prompt injection pattern, scan_output_guardrails
    must return state with final_response == _GUARDRAIL_BLOCKED_RESPONSE and
    put_item must be called with violationType='INJECTION'.
    """
    captured_put_item_calls: list[dict] = []

    def fake_put_item(table_name: str, item: dict) -> None:
        captured_put_item_calls.append({"table_name": table_name, "item": item})

    state = _base_state(final_response=injection_text)

    with patch("src.orchestrator.nodes.scan_output_guardrails.get_guardrailed_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        # Simulate guardrail raising an intervention exception on injection patterns
        mock_llm.invoke.side_effect = Exception(
            "Guardrail intervention: prompt injection detected and blocked"
        )
        mock_llm_factory.return_value = mock_llm

        with patch("src.guardrails.bedrock.put_item", fake_put_item):
            result = scan_output_guardrails(state)

    # The response must be the blocked indicator
    assert result["final_response"] == _GUARDRAIL_BLOCKED_RESPONSE, (
        f"Expected blocked response indicator for injection input. "
        f"Got: {result['final_response']!r}"
    )

    # put_item must have been called at least once
    assert len(captured_put_item_calls) >= 1, (
        "put_item must be called to log the injection violation"
    )

    # The violation log entry must have violationType='INJECTION'
    violation_items = [
        c["item"] for c in captured_put_item_calls
        if c["table_name"] == "guardrail-violations"
    ]
    assert len(violation_items) >= 1, (
        "At least one violation must be logged to the guardrail-violations table"
    )
    assert violation_items[0]["violationType"] == "INJECTION", (
        f"Expected violationType='INJECTION', got: {violation_items[0].get('violationType')!r}"
    )


@given(injection_text=injection_pattern_text())
@settings(max_examples=30)
def test_property31_injection_violation_has_high_severity(injection_text):
    # Feature: feature-02-foundation-infra, Property 31: Prompt Injection Blocking (severity check)
    """
    Injection violations must be logged with severity='HIGH'.
    """
    captured: list[dict] = []

    def fake_put_item(table_name: str, item: dict) -> None:
        captured.append(item)

    state = _base_state(final_response=injection_text)

    with patch("src.orchestrator.nodes.scan_output_guardrails.get_guardrailed_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("blocked by guardrail intervention")
        mock_llm_factory.return_value = mock_llm

        with patch("src.guardrails.bedrock.put_item", fake_put_item):
            scan_output_guardrails(state)

    assert len(captured) >= 1
    assert captured[0]["severity"] == "HIGH", (
        f"Injection violations must have severity='HIGH', got: {captured[0].get('severity')!r}"
    )


@given(injection_text=injection_pattern_text())
@settings(max_examples=30)
def test_property31_injection_violation_request_id_matches_session(injection_text):
    # Feature: feature-02-foundation-infra, Property 31: Prompt Injection Blocking (request_id)
    """
    The requestId in the violation log must match the session_id from state.
    """
    captured: list[dict] = []

    def fake_put_item(table_name: str, item: dict) -> None:
        captured.append(item)

    session_id = f"sess-{uuid.uuid4()}"
    state = _base_state(final_response=injection_text)
    state["session_id"] = session_id

    with patch("src.orchestrator.nodes.scan_output_guardrails.get_guardrailed_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("guardrail blocked this request")
        mock_llm_factory.return_value = mock_llm

        with patch("src.guardrails.bedrock.put_item", fake_put_item):
            scan_output_guardrails(state)

    assert len(captured) >= 1
    assert captured[0]["requestId"] == session_id, (
        f"requestId must match session_id. "
        f"Expected: {session_id!r}, got: {captured[0].get('requestId')!r}"
    )


# =============================================================================
# Property 32: Guardrail Violation Log Completeness
# =============================================================================

_REQUIRED_VIOLATION_FIELDS = {
    "violationId",
    "violationType",
    "severity",
    "redactedContent",
    "requestId",
    "policyVersion",
    "timestamp",
    "ttl",
}


@given(violation=violation_event())
@settings(max_examples=50)
def test_property32_violation_log_completeness(violation):
    # Feature: feature-02-foundation-infra, Property 32: Guardrail Violation Log Completeness
    """
    For every call to log_violation(), exactly one put_item call must be made
    to the guardrail-violations table, and the item must contain all required
    fields with correct types.
    """
    captured: list[dict] = []

    def fake_put_item(table_name: str, item: dict) -> None:
        captured.append({"table_name": table_name, "item": item})

    with patch("src.guardrails.bedrock.put_item", fake_put_item):
        log_violation(**violation)

    # Exactly one put_item call
    assert len(captured) == 1, (
        f"log_violation must call put_item exactly once. Called {len(captured)} times."
    )

    call = captured[0]
    assert call["table_name"] == "guardrail-violations", (
        f"Must write to 'guardrail-violations', got: {call['table_name']!r}"
    )

    item = call["item"]

    # All required fields must be present
    missing_fields = _REQUIRED_VIOLATION_FIELDS - item.keys()
    assert not missing_fields, (
        f"Violation log entry is missing required fields: {missing_fields}"
    )

    # Type checks
    assert isinstance(item["violationId"], str) and len(item["violationId"]) > 0
    assert item["violationType"] == violation["violation_type"]
    assert item["severity"] == violation["severity"]
    assert item["redactedContent"] == violation["redacted_content"]
    assert item["requestId"] == violation["request_id"]
    assert isinstance(item["policyVersion"], str)
    assert isinstance(item["timestamp"], str) and len(item["timestamp"]) > 0
    assert isinstance(item["ttl"], int)

    # TTL must be in the future
    assert item["ttl"] > int(time.time()), (
        f"ttl {item['ttl']} must be greater than current time {int(time.time())}"
    )


@given(violation=violation_event())
@settings(max_examples=30)
def test_property32_violation_id_is_unique_uuid(violation):
    # Feature: feature-02-foundation-infra, Property 32: Guardrail Violation Log Completeness (UUID uniqueness)
    """
    Each log_violation() call must produce a unique violationId that is a valid UUID.
    """
    ids: list[str] = []

    def fake_put_item(table_name: str, item: dict) -> None:
        ids.append(item["violationId"])

    with patch("src.guardrails.bedrock.put_item", fake_put_item):
        log_violation(**violation)
        log_violation(**violation)

    assert len(ids) == 2
    # Both must be valid UUIDs
    for vid in ids:
        parsed = uuid.UUID(vid)
        assert str(parsed) == vid, f"violationId '{vid}' is not a canonical UUID string"

    # They must be distinct (no ID reuse)
    assert ids[0] != ids[1], "Each log_violation() call must produce a unique violationId"


@given(violation=violation_event())
@settings(max_examples=30)
def test_property32_ttl_is_90_days_from_now(violation):
    # Feature: feature-02-foundation-infra, Property 32: Guardrail Violation Log Completeness (TTL)
    """
    The ttl field must be within 2 seconds of int(time.time()) + 90 days.
    """
    _90_DAYS = 90 * 24 * 60 * 60
    captured: list[dict] = []

    def fake_put_item(table_name: str, item: dict) -> None:
        captured.append(item)

    before = int(time.time())

    with patch("src.guardrails.bedrock.put_item", fake_put_item):
        log_violation(**violation)

    after = int(time.time())

    item = captured[0]
    expected_min = before + _90_DAYS
    expected_max = after + _90_DAYS + 2  # 2-second tolerance

    assert expected_min <= item["ttl"] <= expected_max, (
        f"ttl {item['ttl']} is outside the expected 90-day window "
        f"[{expected_min}, {expected_max}]"
    )


@given(violation=violation_event())
@settings(max_examples=30)
def test_property32_violation_type_preserved_exactly(violation):
    # Feature: feature-02-foundation-infra, Property 32: Guardrail Violation Log Completeness (field fidelity)
    """
    The violationType and severity written to DynamoDB must exactly match
    the values passed to log_violation() — no transformation or normalisation.
    """
    captured: list[dict] = []

    def fake_put_item(table_name: str, item: dict) -> None:
        captured.append(item)

    with patch("src.guardrails.bedrock.put_item", fake_put_item):
        log_violation(**violation)

    item = captured[0]
    assert item["violationType"] == violation["violation_type"]
    assert item["severity"] == violation["severity"]
    assert item["redactedContent"] == violation["redacted_content"]
    assert item["requestId"] == violation["request_id"]
