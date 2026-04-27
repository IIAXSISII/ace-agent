# ACE Agent — AWS Cloud Engineering Agent

A multi-agent AI system that acts as a senior Cloud Engineer co-worker for internal teams. Submit natural language requests and ACE Agent classifies intent, builds a validated execution plan, prompts for missing inputs, and orchestrates specialized sub-agents to interact with internal tools and knowledge systems — all with confidence scoring, citations, and full auditability.

Requests are classified into one of seven task categories: `incident_investigation`, `infrastructure_change`, `cost_analysis`, `deployment`, `monitoring_query`, `knowledge_retrieval`, `code_review`.

Built on Amazon Bedrock AgentCore Runtime with LangGraph for orchestration, LangChain for tool integrations, and Claude via Amazon Bedrock as the foundation model.

---

## Architecture

```mermaid
graph TB
    subgraph Users["User Interfaces"]
        CHAINLIT[Chainlit Chat UI<br/>port 8000]
        API[REST API<br/>POST /invocations]
    end

    subgraph Orchestration["Orchestrator — FastAPI + LangGraph"]
        ORCH[Orchestrator Agent<br/>StateGraph · 12 nodes<br/>port 8080]
    end

    subgraph SubAgents["Sub-Agents — registry-driven"]
        MOCK[Mock Sub-Agents<br/>in-process · F01]
        FUTURE[Future: Confluence · CloudWatch<br/>VictoriaMetrics · GitHub]
    end

    subgraph AWS["AWS Services"]
        BEDROCK[Claude via Bedrock<br/>LLM inference]
        GUARDRAILS[Bedrock Guardrails<br/>PII · Injection · Content · Grounding]
        KB[Bedrock Knowledge Bases<br/>RAG retrieval]
        MEMORY[AgentCore Memory<br/>Short-term + Long-term]
        GATEWAY[AgentCore Gateway<br/>MCP protocol]
        IDENTITY[AgentCore Identity<br/>OAuth2 / IdP]
    end

    subgraph Observability["Local Observability Stack — docker-compose"]
        ADOT[ADOT Collector<br/>port 4317]
        VT[VictoriaTraces<br/>port 9428]
        VM[VictoriaMetrics<br/>port 9091]
        LF[Langfuse v3<br/>port 3000]
        GRAF[Grafana<br/>port 3001]
    end

    subgraph Data["Data Layer"]
        DDB[(DynamoDB<br/>7 tables)]
        S3[(S3<br/>3 buckets)]
    end

    CHAINLIT -->|HTTP + WebSocket| ORCH
    API --> ORCH
    ORCH -->|ChatBedrock| BEDROCK
    ORCH --> GUARDRAILS
    ORCH --> KB
    ORCH --> MEMORY
    ORCH --> SubAgents
    SubAgents --> GATEWAY
    GATEWAY --> IDENTITY
    ORCH --> DDB
    ORCH --> S3
    ORCH -->|OTLP gRPC| ADOT
    ADOT --> VT
    ADOT --> VM
    ORCH -->|SDK v3| LF
    VM --> GRAF
    VT --> GRAF
    LF --> GRAF
```

---

## Request Lifecycle

```mermaid
sequenceDiagram
    participant U as User (Chainlit / API)
    participant ORCH as Orchestrator (LangGraph)
    participant MEM as Memory (MemorySaver local · AgentCore prod)
    participant LLM as Claude (Bedrock)
    participant SA as Sub-Agent (mock in F01)
    participant DDB as DynamoDB

    U->>ORCH: POST /invocations {raw_request, session_id}
    ORCH->>MEM: Load checkpoint (session_id)

    Note over ORCH,LLM: classify_request node
    ORCH->>LLM: Classify intent + extract entities
    LLM-->>ORCH: task_category · entities · confidence_score

    alt confidence < 0.7
        ORCH->>U: clarifying_question via prompt_user
        U->>ORCH: Clarification
        ORCH->>LLM: Re-classify
    end

    Note over ORCH,LLM: retrieve_knowledge node
    ORCH->>ORCH: Retrieve top-5 KB documents (mock locally)

    Note over ORCH,LLM: detect_missing_inputs node
    ORCH->>LLM: Check for missing required inputs
    alt missing_inputs not empty
        ORCH->>U: Consolidated missing-input prompt
        U->>ORCH: Provide inputs
    end

    Note over ORCH,LLM: generate_plan + present_plan nodes
    ORCH->>LLM: Generate execution_plan with confidence scores
    ORCH->>U: Present plan for approval
    U->>ORCH: Approve / modify

    loop For each plan step
        Note over ORCH,SA: validate → invoke → validate loop
        ORCH->>ORCH: validate_step_pre (inputs, permissions, availability)
        ORCH->>SA: invoke_subagent (120s timeout)
        SA-->>ORCH: result + confidence_score
        ORCH->>ORCH: validate_step_post (schema, confidence threshold)
        ORCH->>DDB: write_execution_log (immutable, 90-day TTL)
        ORCH->>MEM: Append to context_window
    end

    Note over ORCH,LLM: aggregate_results node
    ORCH->>LLM: Aggregate + cross-reference ≥2 sources
    ORCH->>ORCH: scan_output_guardrails (passthrough locally · Bedrock in prod)
    ORCH->>DDB: write_execution_log (final)
    ORCH->>U: Final response + citations + confidence
```

---

## LangGraph State Machine

The orchestrator is a 12-node LangGraph `StateGraph` defined in `src/orchestrator/graph.py`. Each node is a pure function `(OrchestratorState) → OrchestratorState` in its own file under `src/orchestrator/nodes/`.

```mermaid
flowchart TD
    START((START)) --> classify_request

    classify_request -->|confidence ≥ 0.7| retrieve_knowledge
    classify_request -->|confidence < 0.7| prompt_user

    prompt_user -->|clarification received| classify_request

    retrieve_knowledge --> detect_missing_inputs

    detect_missing_inputs -->|missing_inputs empty| generate_plan
    detect_missing_inputs -->|missing_inputs present| prompt_user

    generate_plan --> present_plan

    present_plan -->|approved| validate_step_pre
    present_plan -->|modified| generate_plan

    validate_step_pre -->|valid| invoke_subagent
    validate_step_pre -->|invalid| aggregate_results

    invoke_subagent --> validate_step_post

    validate_step_post -->|pass · more steps| validate_step_pre
    validate_step_post -->|pass · done| aggregate_results
    validate_step_post -->|fail · retries < 2| invoke_subagent
    validate_step_post -->|fail · retries exhausted| aggregate_results

    aggregate_results --> scan_output_guardrails
    scan_output_guardrails --> write_execution_log
    write_execution_log --> END_NODE((END))

    style START fill:#22c55e,color:#fff
    style END_NODE fill:#ef4444,color:#fff
```

Safety edges checked at every `invoke_subagent` entry:
- `hop_count ≥ 10` → route to `aggregate_results` with diagnostic error
- Cycle detected (`(agent_id, inputs_hash)` already in `visited_steps`) → halt
- `token_budget_used ≥ token_budget_limit` → halt with budget-exceeded error

Independent plan steps are dispatched concurrently via LangGraph's `Send` API (max 5 concurrent).

---

## Local Development

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- [uv](https://docs.astral.sh/uv/) package manager
- AWS credentials with Bedrock access (for LLM inference only)

### Quick Start

```bash
# 1. Clone and configure environment
cp .env.example .env
# Edit .env — set AWS_PROFILE and optionally LANGFUSE keys

# 2. Start the full observability + UI stack
docker compose up -d

# 3. Install Python dependencies
uv pip install -e ".[dev]"

# 4. Run the orchestrator (hot-reload)
uvicorn src.orchestrator.main:app --port 8080 --reload
```

The Chainlit UI is available at http://localhost:8000 and connects to the orchestrator automatically.

### Local Service URLs

| Service | URL | Purpose |
|---|---|---|
| Chainlit UI | http://localhost:8000 | Chat interface |
| Orchestrator API | http://localhost:8080 | FastAPI — `POST /invocations`, `GET /ping` |
| VictoriaTraces | http://localhost:9428 | Distributed trace UI + query API |
| Langfuse | http://localhost:3000 | LLM trace capture and analysis |
| Grafana | http://localhost:3001 | Unified dashboards (admin/admin) |
| VictoriaMetrics | http://localhost:9091 | Prometheus-compatible metrics |
| ADOT Collector | localhost:4317 | OTLP gRPC receiver |
| MinIO Console | http://localhost:9090 | S3-compatible blob store (Langfuse backend) |

### Environment Variables

Copy `.env.example` and configure:

```bash
# AWS — required for Bedrock LLM inference
AWS_PROFILE=<your-aws-profile>
AWS_REGION=us-east-1

# Orchestrator
MOCK_STORAGE=true              # In-memory fixtures instead of real DynamoDB/S3
MOCK_PROMPTS=true              # Local YAML templates instead of DynamoDB
TOKEN_BUDGET_LIMIT=50000       # Max tokens per request

# Observability
OTEL_STACK=local               # Activates local ADOT pipeline + Langfuse
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
LANGFUSE_PUBLIC_KEY=<local-key>
LANGFUSE_SECRET_KEY=<local-secret>
LANGFUSE_BASE_URL=http://localhost:3000

# Leave blank locally — production-only services
AGENTCORE_MEMORY_STORE_ID=
AGENTCORE_GATEWAY_ENDPOINT=
KNOWLEDGE_BASE_ID=
GUARDRAIL_ID=
CHAINLIT_AUTH_SECRET=
```

---

## Observability Stack

```mermaid
flowchart LR
    subgraph App["Application"]
        ORCH[Orchestrator<br/>FastAPI + LangGraph]
    end

    subgraph Collector["ADOT Collector"]
        ADOT[OTLP Receiver<br/>gRPC :4317]
    end

    subgraph Traces["Trace Storage"]
        VT[VictoriaTraces<br/>:9428]
    end

    subgraph Metrics["Metrics Storage"]
        VM[VictoriaMetrics<br/>:9091]
    end

    subgraph LLM["LLM Observability"]
        LF[Langfuse v3<br/>:3000]
    end

    subgraph Dashboards["Dashboards"]
        GRAF[Grafana<br/>:3001]
    end

    ORCH -->|OTLP gRPC<br/>traces + metrics| ADOT
    ORCH -->|Langfuse SDK v3<br/>LLM traces| LF
    ADOT -->|otlphttp exporter| VT
    ADOT -->|prometheusremotewrite| VM
    ADOT -->|prometheus scrape<br/>/metrics endpoint| ORCH
    VT --> GRAF
    VM --> GRAF
    LF --> GRAF
```

| Tool | What it does | When to use it |
|---|---|---|
| VictoriaTraces | Stores distributed traces from all orchestrator nodes. OTLP-native, receives traces via ADOT. | Debug request latency, trace the full execution path across all 12 graph nodes, inspect span timings. |
| VictoriaMetrics | Prometheus-compatible metrics backend. Receives metrics via ADOT's `prometheusremotewrite` exporter and scrapes the orchestrator's `/metrics` endpoint. | Monitor request volume, step failure rates, confidence score distributions, token budget usage. |
| Langfuse | LLM-specific trace capture. Wired via `langfuse.langchain.CallbackHandler` when `OTEL_STACK=local`. SDK v3 with env-var-based config (`LANGFUSE_HOST`). | Inspect individual LLM calls — prompts, completions, token counts, latency. Debug prompt template behavior. |
| Grafana | Unified dashboards pre-wired to VictoriaTraces, VictoriaMetrics, and Langfuse as data sources. | Single pane of glass for all observability data. Pre-built ACE Agent overview dashboard included. |
| ADOT Collector | Receives OTLP telemetry and routes traces to VictoriaTraces and metrics to VictoriaMetrics. Configured via `otel-collector-config.yaml`. | Central telemetry pipeline — you don't interact with it directly, but it's the backbone of the local observability stack. |

In production, ADOT routes traces to AWS X-Ray and AgentCore Observability provides CloudWatch-powered dashboards. Langfuse is local-only.

---

## Production Deployment

### CloudFormation Stack Tiers

Infrastructure is organized into three tiers by change frequency. Deploy in order — each tier depends on the one before it.

```mermaid
flowchart TD
    subgraph Foundation["Foundation Tier — rarely changes"]
        NET[networking.yaml<br/>Security Group · VPC exports]
        ID[identity.yaml<br/>IAM roles · Secrets Manager]
        DATA[data.yaml<br/>7 DynamoDB tables]
        STOR[storage.yaml<br/>3 S3 buckets · Athena · Glue]
    end

    subgraph Platform["Platform Tier — occasionally changes"]
        GRD[guardrails.yaml<br/>Bedrock Guardrails policy]
        MEM[memory.yaml<br/>AgentCore Memory stores]
        GW[gateway.yaml<br/>AgentCore Gateway]
    end

    subgraph Application["Application Tier — frequently changes"]
        ORCH_STACK[orchestrator.yaml<br/>AgentCore Runtime endpoint]
        FUTURE_AGENTS[future agent stacks...]
    end

    NET --> ID --> DATA --> STOR
    STOR --> GRD --> MEM --> GW
    GW --> ORCH_STACK
    GW --> FUTURE_AGENTS

    style Foundation fill:#1e3a5f,color:#fff
    style Platform fill:#2d5a27,color:#fff
    style Application fill:#7c3aed,color:#fff
```

### Deploy Commands

All commands run from the `cloudformation/` directory via the Makefile.

```bash
# Full deployment — foundation → platform → application (in order)
make deploy-foundation ENV=production
make deploy-platform   ENV=production
make deploy-agents     ENV=production

# Update a single agent (fast path — no need to redeploy the full tier)
make deploy-agent AGENT=orchestrator ENV=production

# Preview changes before applying (always do this in production)
make preview STACK=orchestrator TIER=application/agents ENV=production

# Validate all templates
cfn-lint cloudformation/stacks/**/*.yaml

# Detect drift across all stacks
make drift-detect ENV=production

# Tear down everything (reverse dependency order, with confirmation prompt)
make destroy ENV=production
```

When `ENV=production`, the Makefile creates a CloudFormation change set, displays the diff, and waits for confirmation before executing. Non-production environments use direct deploy.

### Parameter Files

Each CloudFormation stack has its own parameter file under `cloudformation/parameters/`, named `{tier}-{stack}-{env}.json`:

| File | Stack |
|---|---|
| `local.json` | Shared local overrides — mock sub-agents, local ADOT endpoint, reduced token budget |
| `prod.json` | Shared production values — VpcId, SubnetIds, model IDs, full token budget |
| `foundation-networking-prod.json` | Foundation networking — VPC, subnets, CIDR |
| `foundation-identity-prod.json` | Foundation identity — IAM, Secrets Manager |
| `foundation-data-prod.json` | Foundation data — DynamoDB tables |
| `foundation-storage-prod.json` | Foundation storage — S3 buckets, Athena, Glue |
| `platform-guardrails-prod.json` | Platform guardrails — Bedrock Guardrails policy |
| `platform-memory-prod.json` | Platform memory — AgentCore Memory stores |
| `platform-gateway-prod.json` | Platform gateway — AgentCore Gateway |
| `application-orchestrator-prod.json` | Application orchestrator — AgentCore Runtime endpoint |

All environment differences are driven by these parameter files and environment variables. No `if env == "production"` branches in Python code.

---

## Local vs Production

| Concern | Local (docker-compose) | Production (AWS) |
|---|---|---|
| LangGraph checkpointer | `MemorySaver` (in-process) | `AgentCoreMemorySaver` (AgentCore Memory) |
| Long-term memory | Not available | `AgentCoreMemoryStore` (cross-session) |
| Sub-agents | Mock in-process (`src/agents/mock/`) | Real agents on AgentCore Runtime |
| Sub-agent routing | Direct in-process call | AgentCore Gateway (MCP protocol) |
| Knowledge retrieval | Mock retriever (fixture documents) | `AmazonKnowledgeBasesRetriever` (Bedrock KB) |
| Guardrails | Passthrough wrapper (no-op) | Bedrock Guardrails (PII, injection, content, grounding) |
| Trace backend | VictoriaTraces (via ADOT) | AWS X-Ray (via ADOT) |
| Metrics backend | VictoriaMetrics (via ADOT) | AgentCore Observability (CloudWatch) |
| LLM tracing | Langfuse v3 (`OTEL_STACK=local`) | AgentCore Observability |
| Dashboards | Grafana (port 3001) | AgentCore Observability (CloudWatch dashboards) |
| Authentication | Disabled (`CHAINLIT_AUTH_SECRET` unset) | OAuth2 via AgentCore Identity |
| Prompt templates | Local YAML files (`MOCK_PROMPTS=true`) | `prompt-template-registry` DynamoDB table |
| Storage | In-memory fixtures (`MOCK_STORAGE=true`) | DynamoDB (7 tables) + S3 (3 buckets) |
| Container platform | Docker Compose (ARM64) | AgentCore Runtime (Firecracker, ARM64) |
| LLM inference | Claude via Bedrock (configurable via `BEDROCK_MODEL_ID`) | Claude via Bedrock (same) |

---

## Testing

```bash
# Run unit tests (excludes integration tests)
uv run pytest tests/ --ignore=tests/integration -v --tb=short

# Run with mock storage and prompts (matches CI)
MOCK_STORAGE=true MOCK_PROMPTS=true uv run pytest tests/ --ignore=tests/integration -v

# Validate CloudFormation templates
cfn-lint cloudformation/stacks/**/*.yaml cloudformation/modules/**/*.yaml
```

Each graph node is a pure function and can be tested in isolation by constructing a minimal `OrchestratorState` dict and asserting on the returned state. Property-based tests use `hypothesis`.

---

## CI/CD

GitHub Actions runs on every PR to `main` with three parallel jobs:

| Job | What it does |
|---|---|
| `test` | Installs dependencies via `uv`, runs `pytest` with `MOCK_STORAGE=true` and `MOCK_PROMPTS=true` |
| `cfn-lint` | Lints all CloudFormation templates under `cloudformation/stacks/` and `cloudformation/modules/` |
| `docker-build` | Builds the orchestrator ARM64 Docker image (no push — build validation only) |

```yaml
# Triggered on PR to main
on:
  pull_request:
    branches: [main]
```

---

## Project Structure

```
├── src/
│   ├── orchestrator/          # LangGraph StateGraph + FastAPI entrypoint
│   │   ├── graph.py           # OrchestratorState + 12 nodes + conditional edges
│   │   ├── nodes/             # One file per graph node
│   │   ├── memory.py          # MemorySaver (local) / AgentCoreMemorySaver (prod)
│   │   ├── prompts.py         # load_prompt_template() from DynamoDB
│   │   └── main.py            # FastAPI: POST /invocations, GET /ping
│   ├── agents/                # Sub-agents (mock in F01, real in F04+)
│   ├── guardrails/            # Bedrock Guardrails wrapper
│   ├── storage/               # DynamoDB + S3 helpers (all table/bucket access)
│   ├── observability/         # ADOT + Langfuse setup
│   └── eval/                  # Offline evaluation pipeline
├── cloudformation/
│   ├── stacks/
│   │   ├── foundation/        # networking, identity, data, storage
│   │   ├── platform/          # guardrails, memory, gateway
│   │   └── application/agents/# One stack per agent
│   ├── modules/               # Reusable CloudFormation modules
│   ├── parameters/            # Per-stack: {tier}-{stack}-{env}.json + shared local/production
│   └── Makefile               # Deploy/preview/destroy targets
├── grafana/                   # Pre-built dashboards + provisioning
├── docker-compose.yml         # Full local dev stack
├── otel-collector-config.yaml # ADOT routing config
├── Dockerfile.orchestrator    # ARM64 multi-stage build
└── Dockerfile.chainlit        # Chainlit UI container
```
