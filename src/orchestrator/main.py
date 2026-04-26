"""
ACE Orchestrator — FastAPI entrypoint.

Routes:
  GET  /ping        → {"status": "Healthy"}
  POST /invocations → invoke LangGraph graph
  GET  /metrics     → Prometheus metrics
"""
import json
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import Response
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from src.orchestrator.graph import build_graph
from src.observability.otel import init_tracer

logger = logging.getLogger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "orchestrator_requests_total",
    "Total requests",
)
REQUEST_DURATION = Histogram(
    "orchestrator_request_duration_seconds",
    "Request duration",
)
STEP_FAILURES = Counter(
    "orchestrator_step_failures_total",
    "Step failures",
)
CONFIDENCE_SCORE = Histogram(
    "orchestrator_confidence_score",
    "Confidence score distribution",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="ACE Orchestrator")

# Initialize tracer at module load (Req 15.6 / task 9.2)
try:
    init_tracer()
except Exception as e:  # pragma: no cover
    logger.warning("Failed to initialize tracer: %s", e)


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    logger.info(json.dumps({"event": "orchestrator_started", "service": "ace-orchestrator"}))


# ── Middleware ────────────────────────────────────────────────────────────────

@app.middleware("http")
async def lifecycle_logging_middleware(request: Request, call_next):
    """Log request lifecycle events (Req 15.1 / task 9.3)."""
    start_time = time.time()
    logger.info(json.dumps({
        "event": "request_received",
        "method": request.method,
        "path": request.url.path,
    }))
    response = await call_next(request)
    duration_ms = (time.time() - start_time) * 1000
    logger.info(json.dumps({
        "event": "request_completed",
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": round(duration_ms, 2),
    }))
    return response


# ── Request model ─────────────────────────────────────────────────────────────

class InvocationRequest(BaseModel):
    raw_request: str
    session_id: str
    user_id: str = "local-user"


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/ping")
async def ping():
    return {"status": "Healthy"}


@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics endpoint (Req 15.9 / task 10.3)."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/invocations")
async def invocations(req: InvocationRequest):
    """Invoke the LangGraph orchestrator graph (Req 1.1 / task 9.1)."""
    REQUEST_COUNT.inc()
    start = time.time()

    graph = build_graph()
    initial_state = {
        "raw_request": req.raw_request,
        "task_category": None,
        "entities": {},
        "confidence_score": 0.0,
        "clarifying_question": None,
        "execution_plan": [],
        "missing_inputs": [],
        "pending_approval": False,
        "current_step_index": 0,
        "hop_count": 0,
        "token_budget_used": 0,
        "token_budget_limit": int(os.getenv("TOKEN_BUDGET_LIMIT", "50000")),
        "visited_steps": [],
        "step_results": [],
        "context_window": [],
        "session_id": req.session_id,
        "user_id": req.user_id,
        "final_response": None,
        "citations": [],
        "error": None,
    }
    config = {"configurable": {"thread_id": req.session_id}}

    result = await graph.ainvoke(initial_state, config=config)

    duration = time.time() - start
    REQUEST_DURATION.observe(duration)

    # Count step failures from step_results
    for step in result.get("step_results", []):
        if step.get("post_validation_passed") is False and step.get("retry_count", 0) >= 2:
            STEP_FAILURES.inc()

    # Record final confidence score
    final_confidence = result.get("confidence_score", 0.0)
    CONFIDENCE_SCORE.observe(final_confidence)

    # Lifecycle log: plan_generated / plan_completed
    if result.get("execution_plan"):
        logger.info(json.dumps({
            "event": "plan_generated",
            "session_id": req.session_id,
            "steps": len(result["execution_plan"]),
        }))
    if result.get("final_response"):
        logger.info(json.dumps({
            "event": "plan_completed",
            "session_id": req.session_id,
            "confidence_score": final_confidence,
        }))

    return {
        "final_response": result.get("final_response"),
        "citations": result.get("citations", []),
        "confidence_score": final_confidence,
        "error": result.get("error"),
        "session_id": req.session_id,
    }
