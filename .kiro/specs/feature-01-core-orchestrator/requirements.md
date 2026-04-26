# Requirements: F01 — Core Orchestrator

> Implements: Req 1–4, 13–14, 15 (local observability only), 16, 29  
> Deferred to later features: Bedrock Knowledge Bases (F03), Bedrock Guardrails (F02), AgentCore Memory/Gateway/Identity (F02), production observability (F05), evaluation pipeline (F09).  
> Local simplifications: `MemorySaver` replaces `AgentCoreMemorySaver`; mock sub-agents replace real integrations; mock retriever replaces `AmazonKnowledgeBasesRetriever`; guardrails are a passthrough wrapper.

---

## Requirement 1: Request Intake and Classification

**User Story:** As an internal team member, I want to submit a cloud engineering request in natural language or structured JSON, so that the agent understands my intent without requiring me to know the exact tool or API to call.

### Acceptance Criteria

1. THE Orchestrator SHALL accept requests submitted as natural language text, structured JSON, or a combination of both via `POST /invocations`.
2. WHEN a request is received, THE Orchestrator SHALL classify it into exactly one of: `incident_investigation`, `infrastructure_change`, `cost_analysis`, `deployment`, `monitoring_query`, `knowledge_retrieval`, `code_review`.
3. WHEN a request is received, THE Orchestrator SHALL extract all entities (service names, time ranges, environments, resource identifiers) and store them in `OrchestratorState.entities` within 5 seconds.
4. WHEN the Orchestrator cannot classify a request with a `confidence_score` of 0.7 or higher, THE Orchestrator SHALL set `clarifying_question` and route to `prompt_user` before proceeding.
5. THE Orchestrator SHALL maintain `task_category`, `entities`, `confidence_score`, and `clarifying_question` in `OrchestratorState` throughout the entire execution lifecycle.

---

## Requirement 2: Execution Plan Generation

**User Story:** As an internal team member, I want the agent to produce a transparent execution plan before acting, so that I can understand and optionally approve what it intends to do.

### Acceptance Criteria

1. WHEN a request has been classified, THE Orchestrator SHALL generate an `execution_plan` consisting of an ordered list of steps, each specifying: `agent_id`, `tool_name`, `tool_inputs`, `expected_output_schema`, `confidence_score`, `expected_category`, and `required_capability`.
2. THE Orchestrator SHALL assign a `confidence_score` (0.0–1.0) to each step in the `execution_plan`.
3. WHEN a step has a `confidence_score` below 0.75, THE Orchestrator SHALL set `is_flagged = True` and populate `flag_rationale` for that step.
4. THE Orchestrator SHALL present the `execution_plan` to the user via Chainlit before any step executes.
5. WHERE `pending_approval` is `True`, THE Orchestrator SHALL wait for explicit user confirmation before executing the plan.
6. WHEN a user requests a modification to the `execution_plan`, THE Orchestrator SHALL incorporate the modification and regenerate the plan before proceeding.

---

## Requirement 3: Missing Input Detection and User Prompting

**User Story:** As an internal team member, I want the agent to ask me for missing information rather than failing silently or making assumptions.

### Acceptance Criteria

1. WHEN the Orchestrator identifies a `Missing_Input` required by any step, THE Orchestrator SHALL pause execution and populate `missing_inputs` in `OrchestratorState`.
2. THE Orchestrator SHALL consolidate all identified `missing_inputs` into a single prompt when multiple inputs are missing, rather than asking one at a time mid-execution.
3. WHEN a user provides a response to a missing-input prompt, THE Orchestrator SHALL validate the response against the expected type and format before incorporating it into the plan.
4. IF a user provides an invalid response, THEN THE Orchestrator SHALL explain the validation error and re-prompt with an example of a valid input.
5. THE Orchestrator SHALL not proceed with execution of any step that has an unresolved `Missing_Input`.

---

## Requirement 4: Multi-Agent Orchestration

**User Story:** As a platform operator, I want the system to coordinate multiple specialized sub-agents, so that complex cross-system tasks are handled efficiently and accurately.

### Acceptance Criteria

1. THE Orchestrator SHALL discover available sub-agents exclusively at runtime by querying the `subagent-registry` DynamoDB table; THE Orchestrator SHALL contain no hardcoded sub-agent names, tool names, or integration types.
2. WHEN executing a plan step, THE Orchestrator SHALL select the sub-agent whose `capabilityDescriptor` best matches the step's `required_capability` using the two-phase capability matching algorithm (category filter → semantic similarity score).
3. THE Orchestrator SHALL pass the full `context_window`, including prior step outputs, to each sub-agent at invocation time.
4. WHEN a sub-agent returns an error or a result with `confidence_score` below 0.7, THE Orchestrator SHALL retry the step with enriched context or escalate to the user with a diagnostic summary.
5. THE Orchestrator SHALL execute independent plan steps in parallel when no data dependency exists between them, with a maximum of 5 concurrent sub-agent invocations per request.
6. THE Orchestrator SHALL enforce a maximum execution time of 120 seconds per sub-agent invocation, after which THE Orchestrator SHALL cancel the invocation and report a timeout error.
7. THE Orchestrator SHALL aggregate outputs from all sub-agents into a unified, coherent response before presenting results to the user.
8. THE Orchestrator SHALL enforce a maximum of 10 sequential sub-agent hops per request; WHEN this limit is reached THE Orchestrator SHALL halt execution and return a diagnostic error.
9. WHEN the Orchestrator detects that the same sub-agent has been invoked with identical inputs more than once within a single request, THE Orchestrator SHALL terminate the execution loop and return a cycle-detection diagnostic error.
10. THE Orchestrator SHALL track total token consumption across all sub-agent invocations; WHEN consumption exceeds the configurable token budget THE Orchestrator SHALL halt execution and notify the user.

---

## Requirement 13: Execution Engine and Step Validation

**User Story:** As a platform operator, I want every execution step to be validated before and after it runs, so that the agent never takes destructive or incorrect actions based on incomplete information.

### Acceptance Criteria

1. BEFORE executing any step, THE Orchestrator SHALL run `validate_step_pre` checking: all required inputs are present, the sub-agent is available, and the action is within the defined permission scope.
2. AFTER each step completes, THE Orchestrator SHALL run `validate_step_post` verifying the output matches the expected schema and `confidence_score` threshold.
3. WHEN `validate_step_post` fails, THE Orchestrator SHALL retry the step up to 2 times with enriched context before marking the step as failed.
4. THE Orchestrator SHALL write an immutable execution log entry to the `execution-logs` DynamoDB table for every step, recording: `stepIndex`, `subAgent`, `tool`, `toolInputs` (redacted), `toolOutput`, `validationResult`, `confidenceScore`, `errorMessage`, `tokenCount`, `promptTemplateId`, `promptTemplateVersion`, and `ttl` (90-day expiry).
5. WHEN a destructive action (resource deletion, configuration change, deployment) is included in the `execution_plan`, THE Orchestrator SHALL require explicit user confirmation regardless of the `pending_approval` configuration.
6. THE Orchestrator SHALL enforce a permission model where each sub-agent has a defined `allowedActions` list, and THE Orchestrator SHALL reject any step that requests an action outside that set.

---

## Requirement 14: Accuracy and Senior Engineer Quality

**User Story:** As an internal team member, I want the agent's outputs to reflect the judgment and accuracy of a senior cloud engineer, so that I can trust its recommendations.

### Acceptance Criteria

1. THE Orchestrator SHALL cross-reference outputs against at least two independent sources before presenting a diagnosis or recommendation.
2. WHEN the Orchestrator produces a recommendation, THE Orchestrator SHALL include a confidence level (high/medium/low), supporting evidence, and any assumptions made.
3. THE Orchestrator SHALL flag any recommendation that relies solely on retrieved documentation without live data validation as "unverified against current state."
4. WHEN an execution produces a result that contradicts retrieved knowledge, THE Orchestrator SHALL surface the contradiction to the user and present both perspectives.
5. THE Orchestrator SHALL not present a final answer with a `confidence_score` below 0.8 without explicitly stating the uncertainty and the reason for it.

---

## Requirement 15: Local Observability Stack

**User Story:** As a developer, I want a full local observability stack so that I can debug agent behavior, inspect LLM traces, and view metrics without deploying to AWS.

> **Scope note:** This requirement covers local observability only (docker-compose). Production observability (AgentCore Observability, X-Ray, CloudWatch) is deferred to F05.

### Acceptance Criteria

1. THE Orchestrator SHALL emit structured logs for every request lifecycle event: request received, plan generated, step started, step completed, step failed, plan completed.
2. THE Orchestrator SHALL emit ADOT traces for each request, mapping the full execution path across all nodes, including latency per node.
3. THE repository SHALL include a `docker-compose.yml` at the repo root that starts: Chainlit UI (port 8000), ADOT Collector (port 4317), Langfuse (port 3000), VictoriaTraces (port 9428), VictoriaMetrics (port 9091), and Grafana (port 3001).
4. WHEN `OTEL_STACK=local`, THE Orchestrator SHALL wire the `langfuse.langchain.CallbackHandler` (imported from `langfuse.langchain`) into every LLM chain invocation via `config={"callbacks": [handler]}`.
5. WHEN `OTEL_STACK` is not `local`, THE Langfuse handler SHALL NOT be wired — it is a local-only tool.
6. THE ADOT `TracerProvider` SHALL be initialized with `AwsXRayIdGenerator()` from `opentelemetry.sdk.extension.aws.trace` from day one.
7. THE ADOT exporter endpoint SHALL be configurable via `OTEL_EXPORTER_OTLP_ENDPOINT`; locally it points to `http://localhost:4317`.
8. A developer SHALL be able to run `docker compose up -d` and immediately see agent traces in VictoriaTraces and LLM traces in Langfuse without additional configuration.
9. THE Orchestrator SHALL expose a Prometheus-compatible `/metrics` endpoint for request volume, average execution time, step failure rate, and `confidence_score` distribution.

---

## Requirement 16: Prompt Template Management

**User Story:** As a platform operator, I want prompt templates to be versioned and centrally managed in DynamoDB, so that system prompts are consistent, auditable, and updatable without code changes.

### Acceptance Criteria

1. THE Orchestrator SHALL load prompt templates from the `prompt-template-registry` DynamoDB table via `load_prompt_template(task_category, version)` — never via f-strings or hardcoded strings in agent code.
2. THE `prompt-template-registry` table SHALL contain at least one versioned system prompt per task category (7 categories).
3. WHEN a sub-agent is invoked, THE Orchestrator SHALL record the `promptTemplateId` and `promptTemplateVersion` in the execution log entry for that step.
4. BEFORE invoking any sub-agent, THE Orchestrator SHALL validate that the rendered prompt contains no unresolved placeholder variables; IF unresolved placeholders exist THEN THE Orchestrator SHALL abort the step and log the rendering error with template ID and missing variable name.
5. IN local development, WHEN the `prompt-template-registry` table is unavailable, THE Orchestrator SHALL fall back to local mock templates (controlled by `MOCK_PROMPTS=true` env var).

---

## Requirement 29: Chainlit Chat UI

**User Story:** As an internal team member, I want a web-based chat interface to interact with the agent, so that I can submit requests, see real-time execution status, and receive structured output.

### Acceptance Criteria

1. THE Chainlit UI SHALL be included in `docker-compose.yml` and run locally on port 8000 without AWS credentials.
2. WHEN a user submits a request via the Chainlit UI, THE UI SHALL display a real-time step indicator for each plan step as it executes, showing the sub-agent name, tool invoked, and current status (running / completed / failed) via `cl.Step`.
3. THE Chainlit UI SHALL render the `execution_plan` as a collapsible structured list before execution begins, allowing the user to approve, modify, or cancel the plan inline.
4. WHEN the Orchestrator prompts for missing inputs or user confirmation, THE Chainlit UI SHALL surface the prompt as an interactive message and forward the user's response back to the Orchestrator.
5. THE Chainlit UI SHALL render final responses in structured format: markdown for narrative text, collapsible JSON blocks for raw tool outputs, tables for metric data, and inline citations.
6. THE Chainlit UI SHALL display a confidence indicator (🟢 High / 🟡 Medium / 🔴 Low) alongside each recommendation and visually distinguish flagged low-confidence steps.
7. WHEN `CHAINLIT_AUTH_SECRET` is unset (local dev), THE Chainlit UI SHALL run without authentication. WHEN set (production), it SHALL enforce OAuth via AgentCore Identity.
