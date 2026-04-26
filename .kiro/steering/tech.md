---
inclusion: always
---

# Tech Stack

## Languages & Frameworks

| Layer | Technology | Notes |
|---|---|---|
| Agent logic | Python (`src/`) | All orchestrator and sub-agent code |
| IaC | CloudFormation YAML (`cloudformation/`) | Nested stacks only — no CDK |
| Orchestration | LangGraph `StateGraph` | Nodes, conditional edges, `OrchestratorState` |
| Tool abstractions | LangChain `BaseTool` | Every tool **must** be a `BaseTool` subclass — no bare functions |
| LLM | `ChatBedrock` via `langchain-aws` | Claude models only |
| Prompt templates | `ChatPromptTemplate` via `langchain-core` | Always loaded from `prompt-template-registry` DynamoDB — **never** f-strings |
| HTTP server | FastAPI + uvicorn | `POST /invocations` (port 8080) + `GET /ping` → `{"status": "Healthy"}` |
| Chat UI | Chainlit | ECS Fargate in prod; port 8000 locally |

## AWS Services

| Service | Role |
|---|---|
| AgentCore Runtime | Hosts all agent containers (Firecracker, ARM64, serverless) |
| AgentCore Observability | Production observability — CloudWatch-powered dashboards, X-Ray traces, Runtime/Memory/Gateway metrics |
| Bedrock Knowledge Bases | Managed RAG — S3 source + S3 Vectors backend |
| Bedrock Guardrails | PII, prompt injection, content safety, grounding — violations → `guardrail-violations` table |
| AgentCore Memory | Short-term (session) and long-term (cross-session) memory |
| AgentCore Gateway | MCP protocol gateway for all sub-agent tool calls |
| AgentCore Identity | OAuth2 / IdP integration (Okta / Azure Entra ID) |
| DynamoDB | 7 tables — access only via `src/storage/dynamodb.py` helpers |
| S3 | 3 buckets (`golden-dataset`, `eval-results`, `artifacts`) — access only via `src/storage/s3.py` helpers |
| AWS X-Ray | Distributed tracing in production |
| Athena + Glue | Ad-hoc analytics over eval results |

### DynamoDB Tables

| Table | Purpose |
|---|---|
| `execution-logs` | Immutable step-level audit log (90-day TTL) |
| `subagent-registry` | Available sub-agents, capabilities, schemas |
| `prompt-template-registry` | Versioned prompt templates per task category |
| `guardrail-violations` | Guardrail events (PII, injection, content, grounding) |
| `eval-run-results` | Offline evaluation run metrics |
| `human-review-queue` | 5%-sampled requests for human review |
| `session-state` | Active session context and plan state |

## Observability Stack

| Tool | Role | Notes |
|---|---|---|
| ADOT (AWS Distro for OpenTelemetry) | Traces, metrics, logs | `AwsXRayIdGenerator` + `opentelemetry-propagator-aws-xray` |
| Langfuse | LLM trace capture — **local dev only** (docker-compose) | v3 (requires ClickHouse, Redis, MinIO); SDK v3+; import from `langfuse.langchain` — **not** `langfuse.callback` |
| VictoriaMetrics | Prometheus-compatible metrics backend — **local dev only** (docker-compose); replaces standalone Prometheus | |
| Grafana | Unified dashboards — **local dev only** (docker-compose) | Port 3001 locally |
| VictoriaTraces | Distributed traces — **local dev only** (docker-compose); Jaeger-compatible query API on port 9428 | Replaces Jaeger |
| AWS X-Ray | Trace propagation | Production only; W3C TraceContext used locally |

- `OTEL_STACK=local|production` — controls which ADOT Collector pipeline is active
- `DISABLE_ADOT_OBSERVABILITY` — verify exact var name against AgentCore Runtime docs; prevents the runtime's built-in ADOT from conflicting with the agent's own OTEL instrumentation in production

## Infrastructure as Code

Stacks are organized into three tiers by change frequency — deploy and update each independently:

| Tier | Path | Stacks | Change frequency |
|---|---|---|---|
| Foundation | `cloudformation/stacks/foundation/` | `networking`, `identity`, `data`, `storage` | Rarely |
| Platform | `cloudformation/stacks/platform/` | `knowledge`, `guardrails`, `memory`, `gateway`, `observability` | Occasionally |
| Application | `cloudformation/stacks/application/agents/` | One stack per agent | Frequently |

- Cross-stack values shared via `Fn::ImportValue` — never hardcode ARNs or IDs
- Export naming: `${AWS::StackName}-<ResourceName>` on every `Outputs` entry
- Key outputs also published to SSM Parameter Store for application code consumption
- `DeletionPolicy: Retain` + `UpdateReplacePolicy: Retain` on all stateful resources (DynamoDB, S3, KMS)
- Every resource tagged: `Environment`, `Application`, `ManagedBy: CloudFormation`
- `VpcId` and `SubnetIds` are always parameters — never create or modify the VPC
- Always create a change set before updating production — never deploy directly without previewing
- Run `cfn-lint` on all templates before any deployment

## Key Libraries

| Library | Purpose |
|---|---|
| `langchain-aws` | `ChatBedrock`, `AmazonKnowledgeBasesRetriever` |
| `langgraph` | Orchestrator `StateGraph` |
| `langchain-core` | `BaseTool`, `ChatPromptTemplate` |
| `langgraph-checkpoint-aws` | `AgentCoreMemorySaver` (prod checkpointer), `AgentCoreMemoryStore` (long-term memory) |
| `ragas` | RAG evaluation metrics (faithfulness, answer relevance, context precision/recall) |
| `opentelemetry-sdk` + `opentelemetry-sdk-extension-aws` + `opentelemetry-propagator-aws-xray` | ADOT instrumentation with X-Ray ID generator and propagator |
| `langfuse` | LLM observability — `langfuse.langchain.CallbackHandler` |
| `chainlit` | Chat UI + LangGraph callback integration |
| `fastapi` + `uvicorn` | AgentCore-compatible HTTP server |

## Critical Coding Rules

These are hard rules — violations will break the system or violate security/compliance requirements.

| Rule | Requirement |
|---|---|
| Tools | Always `BaseTool` subclasses — never pass bare functions to `AgentExecutor` |
| Prompts | Always loaded from `prompt-template-registry` via `load_prompt_template()` — no f-strings in agent code |
| State | Session/plan state in `session-state` DynamoDB — no in-memory state across request boundaries |
| Guardrails | All violations (PII, injection, content, grounding) written to `guardrail-violations` table |
| IAM | Each sub-agent has its own scoped IAM role — never share roles across agents |
| Storage | Use `src/storage/dynamodb.py` and `src/storage/s3.py` — never instantiate boto3 clients directly in agent/tool code |
| Environment | All env differences via env vars and CloudFormation parameter files — no hardcoded environment-specific values |
| Langfuse | Import `CallbackHandler` from `langfuse.langchain`; pass via `config={"callbacks": [handler]}` per chain invocation — **local dev only**, conditionally wired when `OTEL_STACK=local` |
| ADOT | Initialize `TracerProvider` with `AwsXRayIdGenerator()` from `opentelemetry.sdk.extension.aws.trace` |
| Containers | Build for ARM64; `/ping` must return `{"status": "Healthy"}` |

## Common Commands

```bash
# Start full local stack (ADOT, VictoriaTraces, Langfuse, VictoriaMetrics, Grafana, Chainlit)
docker compose up -d

# Run Orchestrator locally
uvicorn src.orchestrator.main:app --port 8080 --reload

# Run a sub-agent locally (e.g. Confluence)
uvicorn src.agents.confluence.agent:app --port 8081 --reload

# Validate all templates before deploying
cfn-lint cloudformation/stacks/**/*.yaml

# Deploy by tier (foundation → platform → agents)
make deploy-foundation ENV=production
make deploy-platform ENV=production
make deploy-agents ENV=production

# Fast path: update a single agent stack only
make deploy-agent AGENT=confluence ENV=production

# Preview changes before applying (always do this in production)
make preview STACK=confluence-agent TIER=application/agents ENV=production

# Detect drift across all stacks
make drift-detect ENV=production

# Tear down all stacks (reverse dependency order)
make destroy ENV=production
```

## Required Local Environment Variables

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_STACK=local
export LANGFUSE_PUBLIC_KEY=<local-key>
export LANGFUSE_SECRET_KEY=<local-secret>
export LANGFUSE_BASE_URL=http://localhost:3000
export AWS_PROFILE=<your-profile>
```

## Local Service URLs

| Service | URL |
|---|---|
| Chainlit UI | http://localhost:8000 |
| Orchestrator API | http://localhost:8080 |
| VictoriaTraces | http://localhost:9428 |
| Langfuse | http://localhost:3000 |
| Grafana | http://localhost:3001 |
| VictoriaMetrics | http://localhost:9091 |
| MinIO console | http://localhost:9090 |
| ADOT Collector (gRPC) | localhost:4317 |
