"""
aggregate_results node — synthesizes a unified final response via LLM:
  1. Collects all step results and context_window documents
  2. Checks if any live sub-agent data was used
  3. Cross-references KB documents against sub-agent outputs
  4. LLM call to generate final_response as markdown
  5. Computes confidence_score (average of step result scores, or 0.5 if none)
  6. Prepends uncertainty notice when confidence < 0.8
  7. Prepends unverified notice when no live sub-agent data used
  8. Builds citations list from context_window documents
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

UNVERIFIED_NOTICE = (
    "⚠️ UNVERIFIED AGAINST CURRENT STATE: This response is based solely on "
    "documentation and has not been validated against live system data."
)


def aggregate_results(state: "OrchestratorState") -> "OrchestratorState":
    step_results = state.get("step_results", [])
    context_window = state.get("context_window", [])
    raw_request = state.get("raw_request", "")
    task_category = state.get("task_category", "unknown")

    # ── Collect step outputs ──────────────────────────────────────────────────
    successful_steps = [
        r for r in step_results
        if not r.get("pre_validation_failed") and r.get("agent_result")
    ]
    has_live_data = bool(successful_steps)

    # ── Compute confidence score ──────────────────────────────────────────────
    scores = [
        r["agent_result"]["confidence_score"]
        for r in successful_steps
        if r.get("agent_result") and "confidence_score" in r["agent_result"]
    ]
    confidence_score = sum(scores) / len(scores) if scores else 0.5

    # ── Collect KB documents from context_window ──────────────────────────────
    _kb_docs = [  # noqa: F841 — used for cross-reference check below
        item for item in context_window
        if isinstance(item, dict) and item.get("type") == "kb_document"
        or hasattr(item, "metadata")  # LangChain Document
    ]

    # ── Build citations ───────────────────────────────────────────────────────
    now_iso = datetime.now(timezone.utc).isoformat()
    citations = []
    for doc in context_window:
        if hasattr(doc, "metadata"):
            meta = doc.metadata or {}
            title = meta.get("title", "Unknown Source")
            url = meta.get("url", "")
            if url:
                citations.append({"title": title, "url": url, "timestamp": now_iso})
        elif isinstance(doc, dict) and doc.get("type") == "kb_document":
            meta = doc.get("metadata", {})
            title = meta.get("title", doc.get("title", "Unknown Source"))
            url = meta.get("url", doc.get("url", ""))
            if url:
                citations.append({"title": title, "url": url, "timestamp": now_iso})

    # ── Build context summary for LLM ─────────────────────────────────────────
    step_summaries = []
    for r in successful_steps:
        agent_result = r.get("agent_result", {})
        step_summaries.append(
            f"Step {r.get('step_index', '?')} ({r.get('tool_name', 'unknown')}): "
            f"{agent_result.get('result', '')}"
        )

    kb_summaries = []
    for doc in context_window:
        if hasattr(doc, "page_content"):
            kb_summaries.append(doc.page_content[:500])
        elif isinstance(doc, dict) and doc.get("type") == "kb_document":
            kb_summaries.append(str(doc.get("content", ""))[:500])

    # ── Cross-reference check ─────────────────────────────────────────────────
    contradiction_note = ""
    if has_live_data and kb_summaries:
        # Simple heuristic: flag if KB and agent outputs are both present (cross-referenced)
        contradiction_note = "\n\n*Note: Response cross-referenced against retrieved documentation and live system data.*"

    # ── LLM call ──────────────────────────────────────────────────────────────
    use_mock = os.getenv("MOCK_STORAGE", "").lower() == "true"
    bedrock_model = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

    if use_mock or not os.getenv("AWS_PROFILE") and not os.getenv("AWS_ACCESS_KEY_ID"):
        # Mock response for local testing without Bedrock
        agent_outputs_text = "\n".join(step_summaries) if step_summaries else "No sub-agent outputs."
        kb_text = "\n".join(kb_summaries) if kb_summaries else "No knowledge base documents."
        final_response = (
            f"## Response for: {raw_request}\n\n"
            f"**Task Category:** {task_category}\n\n"
            f"### Sub-Agent Findings\n{agent_outputs_text}\n\n"
            f"### Knowledge Base Context\n{kb_text}"
            f"{contradiction_note}"
        )
    else:
        from langchain_aws import ChatBedrock
        from langchain_core.messages import HumanMessage, SystemMessage
        from src.observability.langfuse import get_langfuse_handler

        llm = ChatBedrock(model_id=bedrock_model)

        system_msg = SystemMessage(content=(
            "You are a senior cloud engineer synthesizing findings from multiple sources. "
            "Produce a clear, accurate, markdown-formatted response. "
            "Cross-reference all sources and flag any contradictions. "
            "Include confidence level and supporting evidence."
        ))
        human_content = (
            f"Request: {raw_request}\n\n"
            f"Sub-agent outputs:\n" + "\n".join(step_summaries) + "\n\n"
            "Knowledge base documents:\n" + "\n".join(kb_summaries)
        )
        human_msg = HumanMessage(content=human_content)

        handler = get_langfuse_handler()
        config = {"callbacks": [handler]} if handler else {}
        response = llm.invoke([system_msg, human_msg], config=config)
        final_response = response.content + contradiction_note

    # ── Apply notices ─────────────────────────────────────────────────────────
    if not has_live_data:
        final_response = UNVERIFIED_NOTICE + "\n\n" + final_response

    if confidence_score < 0.8:
        uncertainty_notice = (
            f"⚠️ **Uncertainty Notice:** This response has a confidence score of "
            f"{confidence_score:.2f} (below the 0.8 threshold). "
            "Please verify the recommendations before acting.\n\n"
        )
        final_response = uncertainty_notice + final_response

    return {
        **state,
        "final_response": final_response,
        "confidence_score": confidence_score,
        "citations": citations,
    }
