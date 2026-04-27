from typing import TypedDict, List, Optional, Dict, Any


class OrchestratorState(TypedDict):
    # ── Request ──────────────────────────────────────────────────────────────
    raw_request: str
    task_category: Optional[str]          # one of 7 categories after classification
    entities: Dict[str, Any]              # extracted service names, time ranges, etc.
    confidence_score: float               # classification confidence (0.0–1.0)
    clarifying_question: Optional[str]    # set when confidence_score < 0.7

    # ── Plan ─────────────────────────────────────────────────────────────────
    execution_plan: List[Dict[str, Any]]  # ordered steps; each has confidence_score
    missing_inputs: List[Dict[str, Any]]  # unresolved required parameters
    pending_approval: bool                # waiting for user plan confirmation

    # ── Execution ────────────────────────────────────────────────────────────
    current_step_index: int
    hop_count: int                        # max 10 sequential hops enforced
    token_budget_used: int
    token_budget_limit: int
    visited_steps: List[str]             # (agent_id, inputs_hash) for cycle detection
    step_results: List[Dict[str, Any]]   # accumulated sub-agent outputs

    # ── Context ──────────────────────────────────────────────────────────────
    context_window: List[Any]            # LangChain Documents + step outputs
    session_id: str
    user_id: str

    # ── Output ───────────────────────────────────────────────────────────────
    final_response: Optional[str]
    citations: List[Dict[str, Any]]      # {title, url, timestamp}
    error: Optional[Dict[str, Any]]


class PlanStep(TypedDict):
    step_index: int
    description: str
    expected_category: str          # one of 6 integration categories
    required_capability: str        # matched against capabilityDescriptor
    agent_id: Optional[str]         # resolved at routing time
    tool_name: str
    tool_inputs: Dict[str, Any]
    expected_output_schema: Dict    # JSON Schema
    confidence_score: float
    is_flagged: bool                # True when confidence_score < 0.75
    flag_rationale: Optional[str]
    requires_approval: bool         # True for destructive actions


class ExecutionLogEntry(TypedDict):
    requestId: str                  # PK
    stepTimestamp: str              # SK (ISO-8601)
    stepIndex: int
    subAgent: str
    tool: str
    toolInputs: Dict                # redacted by guardrails before write
    toolOutput: Dict
    validationResult: str           # PASS | FAIL | RETRY
    confidenceScore: float
    errorMessage: Optional[str]
    tokenCount: int
    promptTemplateId: str           # Req 16.2
    promptTemplateVersion: str
    ttl: int                        # Unix epoch, 90-day expiry


from langgraph.graph import StateGraph, END

from src.orchestrator.memory import get_checkpointer
from src.orchestrator.nodes.classify_request import classify_request
from src.orchestrator.nodes.retrieve_knowledge import retrieve_knowledge
from src.orchestrator.nodes.detect_missing_inputs import detect_missing_inputs
from src.orchestrator.nodes.prompt_user import prompt_user
from src.orchestrator.nodes.generate_plan import generate_plan
from src.orchestrator.nodes.present_plan import present_plan
from src.orchestrator.nodes.validate_step_pre import validate_step_pre
from src.orchestrator.nodes.invoke_subagent import invoke_subagent
from src.orchestrator.nodes.validate_step_post import validate_step_post
from src.orchestrator.nodes.aggregate_results import aggregate_results
from src.orchestrator.nodes.scan_output_guardrails import scan_output_guardrails
from src.orchestrator.nodes.write_execution_log import write_execution_log


# ── Routing functions ─────────────────────────────────────────────────────────

def _route_classify_request(state: OrchestratorState) -> str:
    # If a clarifying question was set, route to prompt_user to surface it.
    # If confidence is high enough, proceed to retrieve_knowledge.
    if state.get("confidence_score", 0.0) >= 0.7:
        return "retrieve_knowledge"
    return "prompt_user"


def _route_detect_missing_inputs(state: OrchestratorState) -> str:
    # In F01, missing inputs are surfaced via clarifying_question but execution
    # proceeds to generate_plan regardless (no real interrupt mechanism yet).
    # The missing_inputs list is preserved in state for the plan generator to use.
    return "generate_plan"


def _route_present_plan(state: OrchestratorState) -> str:
    # pending_approval=False means auto-approved (F01) or user confirmed → proceed
    # pending_approval=True means user requested a modification → regenerate
    if state.get("pending_approval", False):
        return "generate_plan"
    return "validate_step_pre"


def _route_validate_step_pre(state: OrchestratorState) -> str:
    # TODO: implement — route based on pre-validation result stored in state
    # Returns "invoke_subagent" when valid, "aggregate_results" when invalid
    step_results = state.get("step_results", [])
    last = step_results[-1] if step_results else {}
    if last.get("pre_validation_failed"):
        return "aggregate_results"
    return "invoke_subagent"


def _route_validate_step_post(state: OrchestratorState) -> str:
    # TODO: implement — route based on post-validation result, retry count, and remaining steps
    step_results = state.get("step_results", [])
    last = step_results[-1] if step_results else {}
    execution_plan = state.get("execution_plan", [])
    current_step_index = state.get("current_step_index", 0)
    retry_count = last.get("retry_count", 0)

    if last.get("post_validation_passed"):
        # Pass — check if more steps remain
        if current_step_index < len(execution_plan) - 1:
            return "validate_step_pre"
        return "aggregate_results"
    else:
        # Fail — retry up to 2 times
        if retry_count < 2:
            return "invoke_subagent"
        return "aggregate_results"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph():
    """
    Builds, compiles, and returns the StateGraph with all 12 nodes and conditional edges.
    Does NOT attach a checkpointer — that is handled in task 2.4 via get_checkpointer().
    """
    graph = StateGraph(OrchestratorState)

    # Register all 12 nodes
    graph.add_node("classify_request", classify_request)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("detect_missing_inputs", detect_missing_inputs)
    graph.add_node("prompt_user", prompt_user)
    graph.add_node("generate_plan", generate_plan)
    graph.add_node("present_plan", present_plan)
    graph.add_node("validate_step_pre", validate_step_pre)
    graph.add_node("invoke_subagent", invoke_subagent)
    graph.add_node("validate_step_post", validate_step_post)
    graph.add_node("aggregate_results", aggregate_results)
    graph.add_node("scan_output_guardrails", scan_output_guardrails)
    graph.add_node("write_execution_log", write_execution_log)

    # Entry point
    graph.set_entry_point("classify_request")

    # Conditional edges
    graph.add_conditional_edges(
        "classify_request",
        _route_classify_request,
        {
            "retrieve_knowledge": "retrieve_knowledge",
            "prompt_user": "prompt_user",
        },
    )

    graph.add_conditional_edges(
        "prompt_user",
        lambda state: "retrieve_knowledge",
        {
            "retrieve_knowledge": "retrieve_knowledge",
        },
    )

    graph.add_edge("retrieve_knowledge", "detect_missing_inputs")

    graph.add_conditional_edges(
        "detect_missing_inputs",
        _route_detect_missing_inputs,
        {
            "generate_plan": "generate_plan",
            "prompt_user": "prompt_user",
        },
    )

    graph.add_edge("generate_plan", "present_plan")

    graph.add_conditional_edges(
        "present_plan",
        _route_present_plan,
        {
            "validate_step_pre": "validate_step_pre",
            "generate_plan": "generate_plan",
        },
    )

    graph.add_conditional_edges(
        "validate_step_pre",
        _route_validate_step_pre,
        {
            "invoke_subagent": "invoke_subagent",
            "aggregate_results": "aggregate_results",
        },
    )

    graph.add_edge("invoke_subagent", "validate_step_post")

    graph.add_conditional_edges(
        "validate_step_post",
        _route_validate_step_post,
        {
            "validate_step_pre": "validate_step_pre",
            "aggregate_results": "aggregate_results",
            "invoke_subagent": "invoke_subagent",
        },
    )

    graph.add_edge("aggregate_results", "scan_output_guardrails")
    graph.add_edge("scan_output_guardrails", "write_execution_log")
    graph.add_edge("write_execution_log", END)

    return graph.compile(checkpointer=get_checkpointer())
