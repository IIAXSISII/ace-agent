---
inclusion: always
---

# Product: AWS Cloud Engineering Agent

A multi-agent AI system acting as a senior Cloud Engineer co-worker for internal teams. Users submit natural language or structured requests; the system classifies intent, builds a validated execution plan, prompts for missing inputs, and orchestrates specialized sub-agents to interact with internal tools and knowledge systems.

## Task Categories

Requests are classified into one of: `incident_investigation`, `infrastructure_change`, `cost_analysis`, `deployment`, `monitoring_query`, `knowledge_retrieval`, `code_review`.

## Core Capabilities

- **Request intake**: Natural language or structured JSON input; intent classification drives sub-agent routing
- **Execution planning**: Ordered, confidence-scored plans are shown to the user before any execution begins
- **Multi-agent orchestration**: Specialized sub-agents (Confluence, CloudWatch, VictoriaMetrics, GitHub) are invoked via AgentCore Gateway over MCP protocol
- **Knowledge retrieval**: RAG over internal docs, runbooks, and incident history via Amazon Bedrock Knowledge Bases
- **Observability**: OTEL traces on all containers via AgentCore Observability (production) and Langfuse + VictoriaTraces + VictoriaMetrics + Grafana (local dev)

## Design Principles

- **Correctness over speed**: Every plan step is validated pre- and post-execution; outputs must be cross-referenced against ≥2 independent sources before being surfaced to the user
- **Transparency**: Plans are always shown before execution; every decision is logged with confidence scores and citations to `execution-logs` DynamoDB table
- **Least privilege**: Each sub-agent has its own scoped IAM role with a defined allowed-action set — never share roles across agents
- **Infrastructure as code**: All AWS resources are managed via CloudFormation YAML (`cloudformation/`) — no manual console operations ever

## Architectural Constraints

- All agent HTTP servers must expose `POST /invocations` and `GET /ping` (AgentCore Runtime contract)
- New sub-agents follow the pattern: `tools.py` (BaseTool subclasses) + `agent.py` (AgentExecutor) + CloudFormation stack under `cloudformation/stacks/application/agents/` + `subagent-registry` DynamoDB entry
- Prompt templates are loaded from DynamoDB (`prompt-template-registry`), not hardcoded
- Session and plan state lives in the `session-state` DynamoDB table; do not use in-memory state for anything that must survive a request boundary
- Guardrail violations (PII, prompt injection, content, grounding) are always written to `guardrail-violations` table

## Code Style Rules

- Python for all agent logic (`src/`); CloudFormation YAML for all IaC (`cloudformation/`)
- Use `BaseTool` subclasses for every tool — no bare functions passed to agents
- Use `ChatPromptTemplate` from `langchain-core`; never build prompt strings via f-strings in agent code
- CloudFormation stacks consume `VpcId` and `SubnetIds` from parameters — never create or modify the VPC
- Environment differences are handled via env vars and CloudFormation parameter files (`local.json` / `production.json`) only — no `if env == "production"` branches in Python code
