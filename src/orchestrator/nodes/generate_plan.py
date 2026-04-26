from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

PLAN_SCHEMA_DESCRIPTION = """Generate an execution plan as a JSON object with:
- "execution_plan": an ordered list of step objects, each containing:
  - "step_index": integer starting at 0
  - "description": what this step does (string)
  - "expected_category": one of: incident_investigation, infrastructure_change, cost_analysis, deployment, monitoring_query, knowledge_retrieval, code_review
  - "required_capability": capability descriptor string matched against sub-agent registry
  - "agent_id": null (resolved at routing time)
  - "tool_name": the tool to invoke (string)
  - "tool_inputs": dict of input parameters for the tool
  - "expected_output_schema": JSON Schema object describing expected output
  - "confidence_score": float between 0.0 and 1.0
  - "is_flagged": true if confidence_score < 0.75, false otherwise
  - "flag_rationale": explanation string if is_flagged is true, otherwise null
  - "requires_approval": true for destructive actions (deletions, config changes, deployments), false otherwise

Respond ONLY with valid JSON. No explanation, no markdown, no code blocks."""


def generate_plan(state: "OrchestratorState") -> "OrchestratorState":
    task_category = state.get("task_category") or "knowledge_retrieval"

    try:
        from src.orchestrator.prompts import load_prompt_template

        prompt_template = load_prompt_template(task_category)
        system_messages = prompt_template.format_messages(input=PLAN_SCHEMA_DESCRIPTION)
        system_content = "\n".join(
            m.content for m in system_messages if hasattr(m, "content")
        )
        system_content = f"{system_content}\n\n{PLAN_SCHEMA_DESCRIPTION}"
    except Exception:
        system_content = (
            f"You are a senior cloud engineer planning a {task_category} task.\n\n"
            + PLAN_SCHEMA_DESCRIPTION
        )

    try:
        llm = ChatBedrock(
            model_id=os.getenv(
                "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
            )
        )

        raw_request = state.get("raw_request", "")
        entities = state.get("entities") or {}
        missing_inputs = state.get("missing_inputs") or []

        user_content = json.dumps(
            {
                "raw_request": raw_request,
                "task_category": task_category,
                "entities": entities,
                "resolved_inputs": missing_inputs,
            },
            indent=2,
        )

        from langchain_core.messages import SystemMessage

        messages = [
            SystemMessage(content=system_content),
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
        raw_plan = parsed.get("execution_plan", [])

        if not isinstance(raw_plan, list):
            raw_plan = []

        execution_plan = []
        for i, step in enumerate(raw_plan):
            if not isinstance(step, dict):
                continue

            confidence_score = float(step.get("confidence_score", 0.5))
            confidence_score = max(0.0, min(1.0, confidence_score))

            is_flagged = confidence_score < 0.75
            flag_rationale = step.get("flag_rationale")
            if is_flagged and not flag_rationale:
                flag_rationale = (
                    f"Step confidence {confidence_score:.2f} is below the 0.75 threshold."
                )
            elif not is_flagged:
                flag_rationale = None

            execution_plan.append(
                {
                    "step_index": int(step.get("step_index", i)),
                    "description": str(step.get("description", "")),
                    "expected_category": str(step.get("expected_category", task_category)),
                    "required_capability": str(step.get("required_capability", "")),
                    "agent_id": None,
                    "tool_name": str(step.get("tool_name", "")),
                    "tool_inputs": step.get("tool_inputs") or {},
                    "expected_output_schema": step.get("expected_output_schema") or {},
                    "confidence_score": confidence_score,
                    "is_flagged": is_flagged,
                    "flag_rationale": flag_rationale,
                    "requires_approval": bool(step.get("requires_approval", False)),
                }
            )

    except Exception:
        execution_plan = []

    return {**state, "execution_plan": execution_plan}
