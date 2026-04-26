from __future__ import annotations

import os
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


def retrieve_knowledge(state: "OrchestratorState") -> "OrchestratorState":
    knowledge_base_id = os.getenv("KNOWLEDGE_BASE_ID")

    if knowledge_base_id:
        try:
            from langchain_aws import AmazonKnowledgeBasesRetriever

            retriever = AmazonKnowledgeBasesRetriever(
                knowledge_base_id=knowledge_base_id,
                retrieval_config={"vectorSearchConfiguration": {"numberOfResults": 5}},
            )
            query = state.get("raw_request", "")
            docs = retriever.invoke(query)
        except Exception:
            docs = list(FIXTURE_DOCS)
    else:
        docs = list(FIXTURE_DOCS)

    context_window = list(state.get("context_window") or [])
    context_window.extend(docs)

    return {**state, "context_window": context_window}
