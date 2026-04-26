"""
Guardrails wrapper for ChatBedrock.

get_guardrailed_llm() — single factory for all LLM calls that need guardrail config.
log_violation()       — writes a violation entry to the guardrail-violations DynamoDB table.

Never instantiate ChatBedrock directly in node code — always use get_guardrailed_llm().
Never instantiate boto3 clients directly — use src/storage/dynamodb.py helpers.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from langchain_aws import ChatBedrock

from src.storage.dynamodb import put_item


def get_guardrailed_llm(model_id: Optional[str] = None) -> ChatBedrock:
    """
    Returns a ChatBedrock instance.

    When BEDROCK_GUARDRAIL_ID is set, guardrailConfig is applied.
    When unset, returns a plain ChatBedrock (passthrough — safe for local dev).
    """
    guardrail_id = os.getenv("BEDROCK_GUARDRAIL_ID", "")
    model = model_id or os.getenv(
        "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
    )

    kwargs: dict = {"model_id": model}
    if guardrail_id:
        kwargs["guardrails"] = {
            "guardrailIdentifier": guardrail_id,
            "guardrailVersion": os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
            "trace": "enabled",
        }
    return ChatBedrock(**kwargs)


def log_violation(
    violation_type: str,
    severity: str,
    redacted_content: str,
    request_id: str,
    policy_version: str = "DRAFT",
) -> None:
    """
    Writes a violation log entry to the guardrail-violations DynamoDB table.

    Parameters
    ----------
    violation_type:
        PII | INJECTION | CONTENT | GROUNDING
    severity:
        HIGH | MEDIUM | LOW
    redacted_content:
        The (already-redacted) content that triggered the violation.
    request_id:
        Session or request identifier for correlation.
    policy_version:
        Guardrail policy version in use (default: DRAFT).
    """
    now = datetime.now(timezone.utc)
    ttl = int(now.timestamp()) + (90 * 24 * 60 * 60)  # 90 days

    put_item(
        table_name="guardrail-violations",
        item={
            "violationId": str(uuid.uuid4()),
            "violationType": violation_type,
            "severity": severity,
            "redactedContent": redacted_content,
            "requestId": request_id,
            "policyVersion": policy_version,
            "timestamp": now.isoformat(),
            "ttl": ttl,
        },
    )
