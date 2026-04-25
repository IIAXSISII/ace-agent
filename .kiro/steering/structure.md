---
inclusion: always
---

# Project Structure

## Repository Layout

```
/
├── src/                          # All Python agent code
│   ├── ui/                       # Chainlit chat UI
│   │   ├── app.py                # Entrypoint (@cl.on_message, @cl.on_chat_start)
│   │   ├── handlers.py           # ChainlitStepHandler — surfaces LangGraph nodes as cl.Step
│   │   ├── renderers.py          # Structured output renderers (plan, citations, metrics, confidence)
│   │   └── auth.py               # AgentCore Identity / OAuth callback
│   ├── orchestrator/             # Top-level Orchestrator agent
│   │   ├── graph.py              # LangGraph StateGraph (OrchestratorState + nodes + edges)
│   │   ├── nodes/                # One file per graph node (classify, retrieve, plan, validate, etc.)
│   │   ├── memory.py             # AgentCoreMemorySaver (prod) / MemorySaver (local) + AgentCoreMemoryStore
│   │   ├── prompts.py            # load_prompt_template() — DynamoDB → ChatPromptTemplate
│   │   └── main.py               # AgentCore Runtime entrypoint (FastAPI: /invocations, /ping)
│   ├── agents/                   # Specialized sub-agents
│   │   ├── base.py               # Shared AgentExecutor factory + Langfuse CallbackHandler (local only, conditional on OTEL_STACK)
│   │   ├── confluence/
│   │   │   ├── tools.py          # ConfluenceSearchTool, ConfluenceGetPageTool (BaseTool subclasses)
│   │   │   └── agent.py          # AgentExecutor for Confluence agent
│   │   ├── cloudwatch/
│   │   │   ├── tools.py          # GetMetricStatisticsTool, InsightsQueryTool, etc.
│   │   │   └── agent.py
│   │   ├── victoriametrics/
│   │   │   ├── tools.py          # QueryRangeTool, QueryTool
│   │   │   └── agent.py
│   │   └── github/
│   │       ├── tools.py          # SearchCodeTool, GetFileTool, GetPRTool, ListWorkflowRunsTool, etc.
│   │       └── agent.py
│   ├── rag/
│   │   ├── retriever.py          # AmazonKnowledgeBasesRetriever + ContextualCompressionRetriever
│   │   └── reranker.py           # CrossEncoderReranker / LLMChainFilter wrapper
│   ├── eval/
│   │   ├── runner.py             # Offline eval pipeline (golden-dataset S3 → ragas)
│   │   ├── sampler.py            # 5% live request sampler → human-review-queue DynamoDB
│   │   └── metrics.py            # ragas metric definitions + plan quality scorer
│   ├── guardrails/
│   │   └── bedrock.py            # ChatBedrock wrapper with guardrailConfig
│   ├── storage/
│   │   ├── dynamodb.py           # DynamoDB client helpers (all 7 tables)
│   │   └── s3.py                 # S3 client helpers (golden-dataset, eval-results, artifacts)
│   └── observability/
│       ├── otel.py               # ADOT SDK setup (TracerProvider with AwsXRayIdGenerator, MeterProvider)
│       └── langfuse.py           # langfuse.langchain.CallbackHandler factory (Langfuse SDK v3+)
├── cloudformation/               # All infrastructure as code (CloudFormation YAML)
│   ├── stacks/
│   │   ├── foundation/           # Rarely-changing shared infrastructure
│   │   │   ├── networking.yaml   # VPC Endpoints + Security Groups (existing VpcId/SubnetIds from params)
│   │   │   ├── identity.yaml     # AgentCore Identity + IAM roles + Secrets Manager
│   │   │   ├── data.yaml         # DynamoDB tables + KMS keys
│   │   │   └── storage.yaml      # S3 buckets + Athena workgroup + Glue catalog
│   │   ├── platform/             # Managed services — deploy after foundation
│   │   │   ├── knowledge.yaml    # Bedrock KB + S3 source + S3 Vectors
│   │   │   ├── guardrails.yaml   # Bedrock Guardrails policy
│   │   │   ├── memory.yaml       # AgentCore Memory stores
│   │   │   ├── gateway.yaml      # AgentCore Gateway + MCP tool registrations
│   │   │   └── observability.yaml # AgentCore Observability config + ADOT Collector + CloudWatch log groups
│   │   └── application/
│   │       └── agents/           # One stack per agent — deploy independently
│   │           ├── orchestrator.yaml
│   │           ├── confluence-agent.yaml
│   │           ├── cloudwatch-agent.yaml
│   │           ├── victoriametrics-agent.yaml
│   │           └── github-agent.yaml
│   ├── modules/                  # Reusable CloudFormation modules
│   │   └── agent-runtime-endpoint/ # Shared pattern: Runtime + IAM role + Gateway registration
│   ├── parameters/
│   │   ├── local.json            # Local overrides (local ADOT endpoints, mock creds)
│   │   └── production.json       # Production values (VpcId, SubnetIds, model IDs, budgets)
│   ├── scripts/
│   │   ├── deploy.sh             # Deploys stacks in dependency order
│   │   ├── update-agent.sh       # Fast path: deploys a single agent stack
│   │   └── destroy.sh            # Tears down all stacks in reverse dependency order
│   └── Makefile                  # Convenience targets wrapping scripts/
├── grafana/
│   └── dashboards/               # Pre-built Grafana dashboard JSON definitions (local docker-compose only — not deployed to AWS)
├── docker-compose.yml            # Local observability stack (Chainlit, ADOT Collector, Jaeger, Langfuse, VictoriaMetrics, Grafana)
└── .kiro/
    ├── specs/                    # Kiro spec files
    └── steering/                 # Steering rules for AI assistants
```

## Adding a New Sub-Agent

Follow this checklist in order — all four steps are required:

1. `src/agents/<name>/tools.py` — each tool is a `BaseTool` subclass; no bare functions
2. `src/agents/<name>/agent.py` — build `AgentExecutor` via the `base.py` factory
3. `cloudformation/stacks/application/agents/<name>.yaml` — use the `agent-runtime-endpoint` module; provisions AgentCore Runtime endpoint, scoped IAM role, and Gateway registration; no other stacks need modification
4. `subagent-registry` DynamoDB table — register the agent with its capabilities and schema

## Agent Entrypoint Contract

Every agent (Orchestrator and sub-agents) **must** expose a FastAPI app with exactly these two routes:

- `POST /invocations` — request handler (AgentCore Runtime contract, port 8080)
- `GET /ping` — health check returning `{"status": "Healthy"}`

The entrypoint lives in `main.py` for the Orchestrator and `agent.py` for sub-agents. All containers must be built for **ARM64**.

## CloudFormation Stack Rules

Stacks are organized into three tiers by change frequency — **foundation** (rarely changes), **platform** (occasionally), **application/agents** (frequently). Deploy and update each tier independently.

- Templates live under `cloudformation/stacks/<tier>/`; agent stacks under `stacks/application/agents/`
- Cross-stack values shared via `Fn::ImportValue` — **never** hardcode ARNs or IDs across stacks
- Export naming convention: `${AWS::StackName}-<ResourceName>` on every `Outputs` entry
- Consume `VpcId` and `SubnetIds` from parameters — **never** create or modify the VPC
- `DeletionPolicy: Retain` + `UpdateReplacePolicy: Retain` on all stateful resources (DynamoDB, S3, KMS)
- Every resource tagged: `Environment`, `Application`, `ManagedBy: CloudFormation`, `Stack: !Ref AWS::StackName`
- Publish key outputs to SSM Parameter Store (`AWS::SSM::Parameter`) so application code can read them without `Fn::ImportValue` coupling
- **Always create a change set** before updating any production stack — never `deploy` directly to production without previewing
- Run `cfn-lint` on all templates before any deployment

## Environment Configuration

All environment differences are handled via environment variables and CloudFormation parameter files (`local.json` / `production.json`). The `OTEL_STACK` variable (`local` | `production`) controls which ADOT Collector pipeline is active. Never hardcode environment-specific values in Python source files.

Set the appropriate `DISABLE_ADOT_OBSERVABILITY` env var (verify exact name against AgentCore Runtime docs) in AgentCore Runtime launch env vars to prevent the runtime's built-in ADOT from conflicting with the agent's own OTEL instrumentation.

## DynamoDB Tables

| Table | Purpose |
|---|---|
| `execution-logs` | Immutable step-level audit log (90-day TTL) |
| `subagent-registry` | Available sub-agents, capabilities, schemas |
| `prompt-template-registry` | Versioned prompt templates per task category |
| `guardrail-violations` | Guardrail events (PII, injection, content, grounding) |
| `eval-run-results` | Offline evaluation run metrics |
| `human-review-queue` | 5%-sampled requests for human review |
| `session-state` | Active session context and plan state |

Use `src/storage/dynamodb.py` helpers for all table access — do not instantiate boto3 DynamoDB clients directly in agent or tool code.

## Key Coding Conventions

- **Python** for all agent logic (`src/`); **CloudFormation YAML** for all IaC (`cloudformation/`)
- Tools must be `BaseTool` subclasses — never pass bare functions to an `AgentExecutor`
- Prompt templates are loaded from `prompt-template-registry` DynamoDB via `load_prompt_template()` — never build prompt strings with f-strings in agent code
- Session and plan state lives in `session-state` DynamoDB — do not use in-memory state for anything that must survive a request boundary
- Guardrail violations (PII, prompt injection, content, grounding) must always be written to the `guardrail-violations` table
- Each sub-agent has its own scoped IAM role — never share roles across agents
- Langfuse: import `CallbackHandler` from `langfuse.langchain`; pass via `config={"callbacks": [handler]}` — **local dev only**, never use the deprecated `langfuse.callback` module
- ADOT: initialize `TracerProvider` with `AwsXRayIdGenerator()` from `opentelemetry.sdk.extension.aws.trace`
