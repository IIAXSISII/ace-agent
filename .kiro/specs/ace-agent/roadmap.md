# Delivery Roadmap: AWS Cloud Engineering Agent

> This roadmap breaks the [product vision](./vision.md) into independently deliverable features.
> Each feature is a separate Kiro spec under `.kiro/specs/` that produces working, deployable software.
> Features are ordered by dependency — each one builds on the previous without requiring the full system to exist first.

---

## Feature Map

```
Vision
  │
  ├── F01: Core Orchestrator          ← Start here. No dependencies.
  │     └── F02: Foundation Infra     ← Deploy to AWS for the first time
  │           ├── F03: Knowledge & RAG
  │           ├── F04: VictoriaMetrics Agent   ← First end-to-end integration (needs F02 only)
  │           ├── F05: Observability Stack      ← Full production tracing pipeline
  │           ├── F06: CloudWatch Agent
  │           ├── F07: GitHub Agent
  │           └── F08: Confluence Agent
  │
  └── F09: Evaluation Pipeline
        └── F10: Integration Framework  ← Unlocks self-service agent onboarding
```

---

## Feature Specs

| # | Spec Directory | What it delivers | Vision Requirements | Status |
|---|---|---|---|---|
| F01 | `feature-01-core-orchestrator` | LangGraph graph, request intake, plan generation, Chainlit UI, local dev stack | Req 1–4, 13–14, 15 (local), 16, 29 | 🔲 Not started |
| F02 | `feature-02-foundation-infra` | CloudFormation foundation + platform tiers, VPC endpoints, DynamoDB, S3, IAM | Req 20, 21, 22, 24, 25, 27, 28 | 🔲 Not started |
| F03 | `feature-03-knowledge-rag` | Bedrock Knowledge Bases, S3 Vectors, re-ranker, context injection into Orchestrator | Req 5, 12, 17 | 🔲 Not started |
| F04 | `feature-04-victoriametrics-agent` | First working end-to-end integration; establishes the sub-agent pattern with metrics querying | Req 10, 30, 31, 32 (partial) | 🔲 Not started |
| F05 | `feature-05-observability-stack` | AgentCore Observability enabled, ADOT Collector deployed, Chainlit UI on ECS Fargate, X-Ray traces; full production tracing pipeline | Req 15, 26 | 🔲 Not started |
| F06 | `feature-06-cloudwatch-agent` | Observability monitoring integration | Req 9 | 🔲 Not started |
| F07 | `feature-07-github-agent` | Source control + CI/CD integration | Req 11 | 🔲 Not started |
| F08 | `feature-08-confluence-agent` | Knowledge base integration | Req 6, 30, 31, 32 (full) | 🔲 Not started |
| F09 | `feature-09-evaluation-pipeline` | Golden dataset, ragas metrics, regression gate, human review queue | Req 18, 19 | 🔲 Not started |
| F10 | `feature-10-integration-framework` | Self-service agent onboarding, health polling, catalog | Req 23, 30–32 (full) | 🔲 Not started |

---

## Delivery Phases

### Phase 1 — Working Locally (F01)
**Goal:** A developer can run the Orchestrator locally, submit a request, see a plan generated, and interact via Chainlit. No AWS deployment required.

**Delivers:**
- LangGraph `StateGraph` with all nodes wired
- Request classification, entity extraction, plan generation
- Missing input detection and user prompting
- Pre/post execution validation
- Chainlit UI with real-time step streaming
- `docker-compose.yml` local stack (Jaeger, Langfuse, VictoriaMetrics, Grafana)
- All correctness properties 1–23 testable locally

**Done when:** A developer can `docker compose up -d` + `uvicorn src.orchestrator.main:app` and have a working agent that generates plans and validates steps, even with mock sub-agents. No AWS credentials required except for Bedrock API calls (LLM inference). AgentCore Memory is substituted with LangGraph `MemorySaver`; AgentCore Gateway is bypassed with direct tool calls.

---

### Phase 2 — Deployed to AWS (F02)
**Goal:** The foundation infrastructure exists in AWS. The Orchestrator runs on AgentCore Runtime. No integrations yet.

**Delivers:**
- CloudFormation foundation tier: `networking`, `identity`, `data`, `storage`
- CloudFormation platform tier: `guardrails`, `memory`, `gateway` (the `observability` platform stack is deferred to F05)
- Orchestrator deployed to AgentCore Runtime (ARM64 container)
- Bedrock Guardrails active on all LLM calls
- AgentCore Memory wired to Orchestrator
- AgentCore Identity + Secrets Manager

**Done when:** `make deploy-foundation ENV=production && make deploy-platform ENV=production` succeeds and the Orchestrator endpoint is reachable within the VPC.

---

### Phase 3 — Knowledge-Grounded (F03)
**Goal:** The Orchestrator retrieves relevant context from internal docs before generating plans.

**Delivers:**
- Bedrock Knowledge Bases provisioned with S3 source + S3 Vectors
- `AmazonKnowledgeBasesRetriever` integrated into Orchestrator graph
- Re-ranking step with `ContextualCompressionRetriever`
- RAG metrics (precision@K, recall@K) in execution traces
- Chunking strategy configured per document type

**Done when:** A request about a known service returns a plan that cites relevant runbook content from the Knowledge Base.

---

### Phase 4 — First Integration (F04)
**Goal:** The first real sub-agent is live using VictoriaMetrics. The full integration pattern is proven end-to-end with a metrics query.

**Delivers:**
- VictoriaMetrics_Agent deployed to AgentCore Runtime
- `agent-runtime-endpoint` CloudFormation module (reused by all future agents)
- `subagent-registry` populated with first real entry
- Capability matching algorithm live in Orchestrator
- Full end-to-end: user request → plan → VictoriaMetrics query → cited response

**Done when:** A developer runs the full local stack (`docker compose up -d` + Orchestrator + VictoriaMetrics_Agent), asks "show me the request rate for service X over the last hour", and gets a response with metrics data from the local VictoriaMetrics instance. The same flow works end-to-end in production after F05 deploys the observability stack.

---

### Phase 5 — Production Observability (F05)
**Goal:** Full production-grade observability is live immediately after the first integration, so every subsequent agent is observable from day one.

**Delivers:**
- AgentCore Observability enabled across all Runtime endpoints
- ADOT Collector deployed in production (routes traces to X-Ray)
- Chainlit UI deployed to ECS Fargate behind internal ALB
- AWS X-Ray end-to-end traces
- CloudWatch dashboards for session count, latency, token usage, error rates, and execution path tracing

**Done when:** A production request produces a complete end-to-end trace visible in X-Ray and AgentCore Observability CloudWatch dashboards.

---

### Phase 6 — Core Integrations (F06–F08, parallel)
**Goal:** The three remaining reference integrations are live. Engineers can use the agent for real monitoring queries, code review, and knowledge retrieval.

Each of F06–F08 is independently deployable — they share no dependencies on each other and can be built in parallel by different team members.

**Done when:** All four reference sub-agents are registered and routing correctly.

---

### Phase 7 — Quality Gates (F09)
**Goal:** Regressions are caught before deployment. Live quality is monitored.

**Delivers:**
- Golden Dataset (50+ examples per task category) in S3
- `ragas` evaluation pipeline integrated with CI/CD
- 5% live request sampling → human review queue
- Athena analytics over eval results
- Regression gate blocks deployment on >5% metric drop

**Done when:** A CI/CD pipeline run automatically evaluates the model and blocks a bad deployment.

---

### Phase 8 — Self-Service Integrations (F10)
**Goal:** Any team member can add a new integration in a day by following the four-step checklist.

**Delivers:**
- Health polling background process (updates `healthStatus` in registry)
- Integration catalog documentation
- Static analysis gate in CI (no hardcoded agent names in Orchestrator)
- Onboarding guide with worked example

**Done when:** A new engineer adds a mock integration following the checklist and the Orchestrator routes to it without any Orchestrator code changes.

---

## How to Create a Feature Spec

When you're ready to start a feature, create a new spec:

```
.kiro/specs/feature-XX-<name>/
├── requirements.md   # Subset of vision.md requirements relevant to this feature
├── design.md         # Design decisions for this feature (references architecture.md)
└── tasks.md          # Implementation tasks (generated by Kiro)
```

Each feature spec's `requirements.md` should:
- Reference the vision requirement numbers it implements (e.g., "Implements: Req 1, 2, 4")
- Only include acceptance criteria relevant to this feature's scope
- Note any simplifications or deferred items (e.g., "Guardrails deferred to F02")

Each feature spec's `design.md` should:
- Reference the relevant sections of `architecture.md`
- Only include design decisions needed for this feature
- Document any local-only simplifications (e.g., mock sub-agents, in-memory state)

---

## Cross-Cutting Concerns

These apply to every feature spec:

| Concern | Applies from | Notes |
|---|---|---|
| ARM64 containers | F01 | All containers built for ARM64 from day one |
| `BaseTool` subclasses | F01 | No bare functions ever |
| `langfuse.langchain.CallbackHandler` | F01 | Conditionally wired in `base.py` when `OTEL_STACK=local`; not active in production |
| ADOT instrumentation | F01 | `AwsXRayIdGenerator` in `otel.py` from the start; local → Jaeger (traces) + VictoriaMetrics (metrics) |
| CloudFormation `DeletionPolicy: Retain` | F02 | On all stateful resources |
| `subagent-registry` pattern | F04 | Every integration follows the four-step checklist |
| No hardcoded agent names in Orchestrator | F04 | Enforced by static analysis gate from F10 |
