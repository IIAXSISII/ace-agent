from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

VALID_CATEGORIES = {
    "incident_investigation",
    "infrastructure_change",
    "cost_analysis",
    "deployment",
    "monitoring_query",
    "knowledge_retrieval",
    "code_review",
}

SYSTEM_PROMPT = """You are a cloud engineering request classifier. Analyze the user's request and respond with a JSON object containing exactly these fields:

- "task_category": one of: incident_investigation, infrastructure_change, cost_analysis, deployment, monitoring_query, knowledge_retrieval, code_review
- "entities": a dict of extracted entities (service names, time ranges, environments, resource identifiers, etc.)
- "confidence_score": a float between 0.0 and 1.0 representing your classification confidence
- "clarifying_question": a string with a clarifying question if confidence_score < 0.7, otherwise null

Respond ONLY with valid JSON. No explanation, no markdown, no code blocks."""


def classify_request(state: "OrchestratorState") -> "OrchestratorState":
    raw_request = state.get("raw_request", "")

    try:
        llm = ChatBedrock(
            model_id=os.getenv(
                "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
            )
        )

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=raw_request),
        ]

        response = llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        # Strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        parsed = json.loads(content)

        task_category = parsed.get("task_category")
        if task_category not in VALID_CATEGORIES:
            task_category = None

        entities = parsed.get("entities") or {}
        if not isinstance(entities, dict):
            entities = {}

        confidence_score = float(parsed.get("confidence_score", 0.0))
        confidence_score = max(0.0, min(1.0, confidence_score))

        clarifying_question = parsed.get("clarifying_question")

        if confidence_score < 0.7:
            if not clarifying_question:
                clarifying_question = (
                    "Could you please provide more details about your request? "
                    "For example, which AWS service, environment, or time range are you referring to?"
                )
            task_category = None
        else:
            clarifying_question = None

    except Exception:
        confidence_score = 0.0
        task_category = None
        entities = {}
        clarifying_question = (
            "I couldn't understand your request. Could you please rephrase it?"
        )

    return {
        **state,
        "task_category": task_category,
        "entities": entities,
        "confidence_score": confidence_score,
        "clarifying_question": clarifying_question,
    }
