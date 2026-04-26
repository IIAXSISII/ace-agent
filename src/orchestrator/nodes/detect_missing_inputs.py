from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

SYSTEM_PROMPT = """You are a cloud engineering assistant that identifies missing required inputs for a task.

Given the user's request, task category, extracted entities, and execution plan (if available), identify any required inputs that are missing and would prevent execution.

Respond ONLY with a JSON object containing:
- "missing_inputs": a list of objects, each with:
  - "name": the parameter name (string)
  - "description": what this input is used for (string)
  - "type": the expected type, e.g. "string", "datetime", "integer", "list" (string)
  - "example": a concrete example value (string)

If no inputs are missing, return {"missing_inputs": []}.

Respond ONLY with valid JSON. No explanation, no markdown, no code blocks."""


def detect_missing_inputs(state: "OrchestratorState") -> "OrchestratorState":
    try:
        llm = ChatBedrock(
            model_id=os.getenv(
                "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
            )
        )

        raw_request = state.get("raw_request", "")
        task_category = state.get("task_category", "unknown")
        entities = state.get("entities") or {}
        execution_plan = state.get("execution_plan") or []

        user_content = json.dumps(
            {
                "raw_request": raw_request,
                "task_category": task_category,
                "entities": entities,
                "execution_plan": execution_plan,
            },
            indent=2,
        )

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ]

        response = llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)

        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        parsed = json.loads(content)
        missing_inputs = parsed.get("missing_inputs", [])

        if not isinstance(missing_inputs, list):
            missing_inputs = []

        # Ensure each entry has the required fields
        validated = []
        for item in missing_inputs:
            if isinstance(item, dict) and "name" in item:
                validated.append(
                    {
                        "name": str(item.get("name", "")),
                        "description": str(item.get("description", "")),
                        "type": str(item.get("type", "string")),
                        "example": str(item.get("example", "")),
                    }
                )

    except Exception:
        validated = []

    return {**state, "missing_inputs": validated}
