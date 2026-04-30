from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from langchain_core.documents import Document

if TYPE_CHECKING:
    from src.orchestrator.graph import OrchestratorState

FIXTURE_DOCS = [
    Document(
        page_content=(
            "Runbook: EC2 High CPU Investigation\n"
            "1. Check CloudWatch metrics for CPUUtilization > 80% sustained over 5 minutes.\n"
            "2. SSH into the instance and run `top` or `htop` to identify the offending process.\n"
            "3. Check application logs under /var/log/app/ for error spikes.\n"
            "4. If a runaway process is found, capture a thread dump before killing it.\n"
            "5. Scale out via Auto Scaling Group if load is legitimate.\n"
            "6. Open a post-mortem ticket if the event lasted > 15 minutes."
        ),
        metadata={
            "title": "EC2 High CPU Runbook",
            "url": "https://wiki.internal/runbooks/ec2-cpu",
            "source": "confluence",
        },
    ),
    Document(
        page_content=(
            "Runbook: RDS Connection Pool Exhaustion\n"
            "1. Check RDS CloudWatch metric DatabaseConnections — alert threshold is 80% of max_connections.\n"
            "2. Identify top connection consumers via `SELECT * FROM pg_stat_activity ORDER BY state_change DESC`.\n"
            "3. Check application connection pool settings (e.g. HikariCP maxPoolSize).\n"
            "4. Enable RDS Proxy to multiplex connections if the application cannot be patched quickly.\n"
            "5. Restart idle connections using `SELECT pg_terminate_backend(pid)` for sessions idle > 10 min.\n"
            "6. Review and tune `max_connections` parameter in the RDS parameter group."
        ),
        metadata={
            "title": "RDS Connection Pool Runbook",
            "url": "https://wiki.internal/runbooks/rds-connections",
            "source": "confluence",
        },
    ),
    Document(
        page_content=(
            "Architecture: Microservices Deployment Guide\n"
            "Deployment strategy: Blue/Green via CodeDeploy with automatic rollback on CloudWatch alarm.\n"
            "1. Build and push Docker image to ECR (ARM64 target platform).\n"
            "2. Update ECS task definition with new image digest.\n"
            "3. Create CodeDeploy deployment — traffic shifts 10% → 50% → 100% over 15 minutes.\n"
            "4. Monitor p99 latency and error rate during shift; rollback triggers if error rate > 1%.\n"
            "5. After full cutover, deregister old task set and clean up old ECR images (retain last 5).\n"
            "6. Update SSM Parameter Store with new image tag for audit trail."
        ),
        metadata={
            "title": "Microservices Deployment Guide",
            "url": "https://wiki.internal/arch/microservices",
            "source": "confluence",
        },
    ),
]


def _compute_rag_metrics(
    scored_docs: list[tuple[Document, float]],
    threshold: float,
    top_k: int,
) -> tuple[float, float]:
    """
    Compute approximated precision@K and recall@K using reranker scores as
    a proxy for relevance. A document is 'relevant' if score >= threshold.

    Returns (precision_at_k, recall_at_k).
    """
    relevant_in_top_k = sum(1 for _, s in scored_docs[:top_k] if s >= threshold)
    total_relevant = sum(1 for _, s in scored_docs if s >= threshold)
    precision_at_k = relevant_in_top_k / top_k if top_k > 0 else 0.0
    recall_at_k = relevant_in_top_k / total_relevant if total_relevant > 0 else 0.0
    return precision_at_k, recall_at_k


def retrieve_knowledge(state: "OrchestratorState") -> "OrchestratorState":
    import opentelemetry.trace as otel_trace

    knowledge_base_id = os.getenv("KNOWLEDGE_BASE_ID")
    top_k = int(os.getenv("KB_TOP_K", "5"))
    threshold = float(os.getenv("KB_RELEVANCE_THRESHOLD", "0.5"))
    reranker_enabled = os.getenv("RERANKER_ENABLED", "true").lower() == "true"

    query = state.get("raw_request", "")
    initial_cw = list(state.get("context_window") or [])
    now_iso = datetime.now(timezone.utc).isoformat()

    tracer = otel_trace.get_tracer(__name__)

    with tracer.start_as_current_span("knowledge.retrieve") as span:
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]

        if knowledge_base_id:
            try:
                from src.rag.retriever import build_kb_retriever

                retriever = build_kb_retriever(
                    knowledge_base_id,
                    top_k=top_k,
                    reranker_enabled=reranker_enabled,
                )

                invoke_config: dict = {}
                if os.getenv("OTEL_STACK") == "local":
                    from src.observability.langfuse import get_langfuse_handler
                    handler = get_langfuse_handler()
                    if handler:
                        invoke_config = {"callbacks": [handler]}

                docs = retriever.invoke(query, config=invoke_config) if invoke_config else retriever.invoke(query)

                # Apply relevance threshold filter
                included_docs: list[Document] = []
                for doc in docs:
                    score = doc.metadata.get("relevance_score", 1.0)
                    if score >= threshold:
                        included_docs.append(doc)
                    else:
                        span.add_event(
                            "doc_excluded",
                            attributes={
                                "doc_id": doc.metadata.get("source", doc.metadata.get("url", "unknown")),
                                "score": float(score),
                                "threshold": float(threshold),
                            },
                        )

                if not included_docs and docs:
                    span.add_event(
                        "all_docs_excluded",
                        attributes={
                            "threshold": float(threshold),
                            "docs_retrieved": len(docs),
                        },
                    )

                # Build scored_docs for metric computation
                scored_docs: list[tuple[Document, float]] = [
                    (doc, float(doc.metadata.get("relevance_score", 1.0)))
                    for doc in included_docs
                ]

                # Compute RAG metrics (only when reranker is enabled)
                precision_at_k: float | None = None
                recall_at_k: float | None = None
                if reranker_enabled:
                    precision_at_k, recall_at_k = _compute_rag_metrics(scored_docs, threshold, top_k)

                # Build citations
                citations = []
                for doc in included_docs:
                    meta = doc.metadata or {}
                    title = meta.get("title") or meta.get("source", "unknown")
                    url = meta.get("url") or meta.get("source", "unknown")
                    citations.append({"title": title, "url": url, "timestamp": now_iso})

                # Set OTEL span attributes
                span.set_attribute("rag.query_hash", query_hash)
                span.set_attribute("rag.k", top_k)
                span.set_attribute("rag.docs_retrieved", len(docs))
                span.set_attribute("rag.docs_included", len(included_docs))
                span.set_attribute("rag.reranker_applied", reranker_enabled)
                if precision_at_k is not None:
                    span.set_attribute("rag.precision_at_k", precision_at_k)
                if recall_at_k is not None:
                    span.set_attribute("rag.recall_at_k", recall_at_k)

                return {
                    **state,
                    "context_window": initial_cw + included_docs,
                    "citations": citations,
                }

            except Exception as exc:
                error = {"type": exc.__class__.__name__, "message": str(exc)}
                span.add_event(
                    "kb_retrieval_error",
                    attributes={"error_type": exc.__class__.__name__, "error_message": str(exc)},
                )
                return {**state, "error": error}

        else:
            # Mock path — fixture docs, no threshold, no metrics
            docs = list(FIXTURE_DOCS)
            citations = [
                {
                    "title": doc.metadata.get("title", "unknown"),
                    "url": doc.metadata.get("url", "unknown"),
                    "timestamp": now_iso,
                }
                for doc in docs
            ]

            span.set_attribute("rag.query_hash", query_hash)
            span.set_attribute("rag.k", top_k)
            span.set_attribute("rag.docs_retrieved", len(docs))
            span.set_attribute("rag.docs_included", len(docs))
            span.set_attribute("rag.reranker_applied", False)

            return {
                **state,
                "context_window": initial_cw + docs,
                "citations": citations,
            }
