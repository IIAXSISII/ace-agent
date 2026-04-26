# Vision Document: AWS Cloud Engineering Agent

> **This is the product vision and full requirements catalog for the AWS Cloud Engineering Agent.**
> It defines the complete target state of the system. It is NOT a single feature spec — it is the source of truth from which individual feature specs are derived.
>
> See [`roadmap.md`](./roadmap.md) for how this vision is broken into independently deliverable features.
> See [`architecture.md`](./architecture.md) for the full system architecture.

## Introduction

The AWS Cloud Engineering Agent is a multi-agent system designed to act as a senior Cloud Engineer co-worker for internal teams. The system receives natural language or structured requests, analyzes them, builds an execution plan, validates the plan, prompts for missing inputs, and executes tasks by orchestrating specialized sub-agents that interface with internal tools and knowledge systems (Confluence, CloudWatch, VictoriaMetrics, GitHub, Amazon Bedrock Knowledge Bases, documentation sites, and others — with PagerDuty, Cost Explorer, and additional integrations supported via the extensible sub-agent framework). The system must produce accurate, reliable outputs consistent with the judgment and quality of a senior cloud engineer.

All agents (Orchestrator and Sub-Agents) are deployed as containerized workloads on Amazon Bedrock AgentCore Runtime, providing enterprise-grade session isolation, serverless scaling, and long-running execution support. All infrastructure — agents, memory stores, gateway configurations, identity policies, networking, and supporting AWS resources — is defined as CloudFormation IaC, making the entire system reproducible, version-controlled, and deployable to any environment with a single command.

---

## Glossary

- **Orchestrator**: The top-level agent responsible for receiving requests, decomposing them, building execution plans, and coordinating sub-agents.
- **Sub-Agent**: A specialized agent responsible for a single domain (e.g., CloudWatch, GitHub, Confluence) invoked by the Orchestrator.
- **Request**: A natural language or structured input submitted by an internal team member describing a cloud engineering task.
- **Execution_Plan**: A structured, ordered list of steps the Orchestrator produces before executing a task.
- **Tool**: An integration or API connector used by a Sub-Agent to interact with an external system.
- **Knowledge_Base**: The aggregated, indexed corpus of internal documentation, runbooks, incident history, and architectural context stored in a vector store.
- **Context_Window**: The accumulated state, retrieved knowledge, and intermediate results maintained across a multi-step execution.
- **Validation_Step**: A verification gate applied to the Execution_Plan or intermediate outputs before proceeding.
- **Confidence_Score**: A numeric value (0.0–1.0) representing the Orchestrator's certainty that a plan or output is correct and complete.
- **Missing_Input**: Any parameter, credential, or context item required to execute a step that has not been provided by the user.
- **Runbook**: A documented procedure for operating or troubleshooting a cloud system.
- **Incident**: A service degradation or outage event tracked by an incident management system (e.g., PagerDuty, OpsGenie).
- **Metric**: A time-series data point sourced from CloudWatch or VictoriaMetrics.
- **Trace**: A distributed tracing record used for root-cause analysis.
- **PR**: A GitHub Pull Request.
- **IaC**: Infrastructure as Code (e.g., Terraform, CloudFormation).
- **Prompt_Template**: A versioned, parameterized text template used to construct LLM prompts for a specific task category, including system prompt, few-shot examples, and variable slots.
- **Evaluation_Pipeline**: An automated pipeline that runs offline evaluation benchmarks against a Golden_Dataset to measure model and prompt quality across defined metrics.
- **Golden_Dataset**: A curated, versioned collection of labeled request/response pairs used as ground truth for offline evaluation of the agent's outputs.
- **Guardrail**: A safety control applied to inputs or outputs to detect and mitigate harmful, unsafe, or policy-violating content before it reaches an LLM or a user.
- **RAG_Metric**: A quantitative measure of retrieval-augmented generation quality, including faithfulness, answer relevance, context precision, and context recall (RAGAS-style).
- **Tool_Schema**: A JSON Schema definition describing the required and optional input parameters, types, and constraints for a specific Tool invocation.
- **AgentCore_Runtime**: The Amazon Bedrock AgentCore serverless runtime environment that hosts agent containers built with LangChain and LangGraph, providing Firecracker VM isolation, session isolation, and support for long-running workloads.
- **AgentCore_Memory**: The Amazon Bedrock AgentCore managed memory service providing short-term (multi-turn) and long-term (cross-session) memory stores shared across agents.
- **AgentCore_Gateway**: The Amazon Bedrock AgentCore managed MCP gateway that converts APIs, Lambda functions, and services into MCP-compatible tools discoverable by agents.
- **AgentCore_Identity**: The Amazon Bedrock AgentCore identity and authentication service managing agent credentials and access control, compatible with external IdPs.
- **CloudFormation_Stack**: A CloudFormation template (or set of nested templates) and its associated stack state that defines and provisions all AWS infrastructure resources for the system as code.
- **MCP**: Model Context Protocol — a standard protocol for exposing tools to AI agents, used by AgentCore Gateway.
- **OTEL**: OpenTelemetry — a vendor-neutral observability framework. This system uses the **AWS Distro for OpenTelemetry (ADOT)**, AWS's supported distribution that adds `AwsXRayIdGenerator` and `opentelemetry-propagator-aws-xray` for native X-Ray integration.
- **Langfuse**: An open-source LLM observability platform that captures prompt traces, tool call traces, token usage, latency, and evaluation scores for every LLM interaction.
- **VictoriaTraces**: An open-source distributed tracing system used locally to visualize agent execution traces across Sub-Agent hops. Exposes a Jaeger-compatible query API consumed by Grafana.
- **Chainlit**: An open-source Python framework for building production-ready chat UIs for LangChain/LangGraph applications, providing real-time step-by-step execution status, structured output rendering, and native LangGraph callback integration.
- **DynamoDB**: Amazon DynamoDB — a fully serverless, key-value and document NoSQL database used for execution logs, registries, audit logs, evaluation records, and hot session state with TTL-based expiry.
- **Bedrock_Knowledge_Bases**: Amazon Bedrock Knowledge Bases — a fully managed RAG service that indexes documents from connected sources into a vector store with metadata filtering and hybrid search, replacing a self-managed vector store.
- **Bedrock_Guardrails**: Amazon Bedrock Guardrails — a managed safety service that enforces PII detection/redaction, prompt injection detection, content safety filtering, and hallucination grounding checks on all LLM inputs and outputs.
- **Athena**: Amazon Athena — a serverless SQL query service used to run ad-hoc analytics over eval run results exported from DynamoDB to S3.
- **Integration_Category**: One of six defined classifications for Sub-Agent integrations: `observability_monitoring`, `incident_management`, `communication_collaboration`, `source_control_cicd`, `infrastructure_cloud`, or `knowledge_documentation`. Every Sub-Agent registered in the `subagent-registry` must belong to exactly one category.
- **Capability_Descriptor**: A plain-language string stored in the `subagent-registry` that describes what a Sub-Agent can do. The Orchestrator uses this field, combined with the `Integration_Category`, to match plan steps to the correct Sub-Agent at runtime.
- **Integration_Sub_Agent_Framework**: The standard interface contract, registration model, and four-step onboarding checklist that every Sub-Agent integration must satisfy. Defined in Req 30. Ensures the Orchestrator can discover and invoke any Sub-Agent without hardcoded knowledge of specific integrations.

---

## Requirements

### Requirement 1: Request Intake and Analysis

**User Story:** As an internal team member, I want to submit a cloud engineering request in natural language, so that the agent understands my intent without requiring me to know the exact tool or API to call.

#### Acceptance Criteria

1. THE Orchestrator SHALL accept requests submitted as natural language text, structured JSON, or a combination of both.
2. WHEN a request is received, THE Orchestrator SHALL classify the request into one of the defined task categories: incident investigation, infrastructure change, cost analysis, deployment, monitoring query, knowledge retrieval, or code review.
3. WHEN a request is received, THE Orchestrator SHALL extract all entities (service names, time ranges, environments, resource identifiers) present in the request within 5 seconds.
4. WHEN the Orchestrator cannot classify a request with a Confidence_Score of 0.7 or higher, THE Orchestrator SHALL ask the user one targeted clarifying question before proceeding.
5. THE Orchestrator SHALL maintain a structured representation of the parsed request, including intent, extracted entities, and classification, throughout the entire execution lifecycle.

---

### Requirement 2: Execution Plan Generation

**User Story:** As an internal team member, I want the agent to produce a transparent execution plan before acting, so that I can understand and optionally approve what it intends to do.

#### Acceptance Criteria

1. WHEN a request has been analyzed, THE Orchestrator SHALL generate an Execution_Plan consisting of an ordered list of steps, each specifying the Sub-Agent to invoke, the Tool to use, the inputs required, and the expected output.
2. THE Orchestrator SHALL assign a Confidence_Score to each step in the Execution_Plan based on available context and retrieved knowledge.
3. WHEN the Execution_Plan contains a step with a Confidence_Score below 0.75, THE Orchestrator SHALL flag that step and include a rationale for the uncertainty.
4. THE Orchestrator SHALL present the Execution_Plan to the user in a human-readable format before execution begins.
5. WHERE user approval is configured as required, THE Orchestrator SHALL wait for explicit user confirmation before executing the plan.
6. WHEN a user requests a modification to the Execution_Plan, THE Orchestrator SHALL incorporate the modification and regenerate the plan before proceeding.

---

### Requirement 3: Missing Input Detection and User Prompting

**User Story:** As an internal team member, I want the agent to ask me for missing information rather than failing silently or making assumptions, so that executions are always based on complete and accurate inputs.

#### Acceptance Criteria

1. WHEN the Orchestrator identifies a Missing_Input required by any step in the Execution_Plan, THE Orchestrator SHALL pause execution and prompt the user with a specific, contextual question identifying the missing parameter.
2. THE Orchestrator SHALL consolidate all identified Missing_Inputs into a single prompt when multiple inputs are missing before execution begins, rather than asking one at a time mid-execution.
3. WHEN a user provides a response to a Missing_Input prompt, THE Orchestrator SHALL validate the response against the expected type and format before incorporating it into the plan.
4. IF a user provides an invalid response to a Missing_Input prompt, THEN THE Orchestrator SHALL explain the validation error and re-prompt with an example of a valid input.
5. THE Orchestrator SHALL not proceed with execution of any step that has an unresolved Missing_Input.

---

### Requirement 4: Multi-Agent Orchestration

**User Story:** As a platform operator, I want the system to coordinate multiple specialized sub-agents, so that complex cross-system tasks are handled efficiently and accurately.

#### Acceptance Criteria

1. THE Orchestrator SHALL discover available Sub-Agents exclusively at runtime by querying the `subagent-registry` DynamoDB table (Req 27); THE Orchestrator SHALL contain no hardcoded knowledge of specific Sub-Agent names, tool names, or integration types.
2. WHEN executing a plan step, THE Orchestrator SHALL select the Sub-Agent whose `capabilityDescriptor` field in the `subagent-registry` best matches the step's required action, using the capability matching algorithm defined in Req 30.
3. THE Orchestrator SHALL pass the full Context_Window, including prior step outputs and retrieved knowledge, to each Sub-Agent at invocation time.
4. WHEN a Sub-Agent returns an error or a result with a Confidence_Score below 0.7, THE Orchestrator SHALL retry the step with an enriched context or escalate to the user with a diagnostic summary.
5. THE Orchestrator SHALL execute independent plan steps in parallel when no data dependency exists between them, with a maximum of 5 concurrent Sub-Agent invocations per request.
6. THE Orchestrator SHALL enforce a maximum execution time of 120 seconds per Sub-Agent invocation, after which THE Orchestrator SHALL cancel the invocation and report a timeout error.
7. THE Orchestrator SHALL aggregate outputs from all Sub-Agents into a unified, coherent response before presenting results to the user.
8. THE Orchestrator SHALL enforce a maximum of 10 sequential Sub-Agent hops per request, and WHEN this limit is reached THE Orchestrator SHALL halt execution and return a diagnostic error to the user.
9. WHEN the Orchestrator detects that the same Sub-Agent has been invoked with identical inputs more than once within a single request, THE Orchestrator SHALL terminate the execution loop and return a cycle-detection diagnostic error.
10. THE Orchestrator SHALL track the total token consumption across all Sub-Agent invocations for a request, and WHEN consumption exceeds the configurable token budget THE Orchestrator SHALL halt execution and notify the user of the budget exceeded condition.

---

### Requirement 5: Knowledge Base and Context Management

**User Story:** As an internal team member, I want the agent to leverage internal documentation, runbooks, and historical incident data, so that its responses reflect our specific infrastructure and operational context.

#### Acceptance Criteria

1. THE Knowledge_Base SHALL index content from Confluence spaces, GitHub repositories, internal documentation sites, and historical incident records.
2. WHEN a request is received, THE Orchestrator SHALL query the Knowledge_Base and retrieve the top 5 most semantically relevant documents before generating the Execution_Plan.
3. THE Orchestrator SHALL include retrieved Knowledge_Base documents in the Context_Window passed to all Sub-Agents for the duration of the request.
4. WHEN a Sub-Agent retrieves new information during execution (e.g., a CloudWatch log, an incident record), THE Orchestrator SHALL append that information to the Context_Window.
5. THE Knowledge_Base SHALL be updated with new content within 1 hour of a source document being created or modified in a connected system.
6. THE Orchestrator SHALL cite the source document (title, URL, and retrieval timestamp) for every piece of knowledge used in generating a response.

---

### Requirement 6: Confluence Integration *(Reference Implementation — Integration Sub-Agent Framework)*

**User Story:** As an internal team member, I want the agent to search and retrieve content from Confluence, so that it can reference internal runbooks, architecture docs, and team wikis when answering questions or building plans.

> **Note:** This requirement is a reference implementation of the Integration Sub-Agent Framework (Req 30). The Confluence_Agent satisfies the standard sub-agent interface contract and is registered in the `subagent-registry` under the `knowledge_documentation` integration category. It demonstrates the pattern that all integrations must follow.

#### Acceptance Criteria

1. WHEN a plan step requires internal documentation, THE Confluence_Agent SHALL search the configured Confluence spaces using keyword and semantic queries.
2. THE Confluence_Agent SHALL return the page title, URL, last-modified date, and relevant excerpt for each retrieved document.
3. WHEN a Confluence page is retrieved, THE Confluence_Agent SHALL extract structured content (tables, code blocks, headings) and include it in the Context_Window.
4. IF the Confluence API returns an authentication error, THEN THE Confluence_Agent SHALL report the error to the Orchestrator with the HTTP status code and cease further Confluence queries for that request.

---

### Requirement 7: PagerDuty Integration *(Catalog Entry — not in current roadmap)*

**User Story:** As an on-call engineer, I want the agent to query PagerDuty for active incidents and historical event data, so that it can assist with incident triage and root-cause analysis.

> **Note:** This integration is architecturally supported via the Integration Sub-Agent Framework (Req 30) but is **not part of the current delivery roadmap**. It can be added at any time using the four-step onboarding checklist with zero Orchestrator changes. The PagerDuty_Agent would be registered in the `subagent-registry` under the `incident_management` integration category.

#### Acceptance Criteria

1. WHEN a plan step requires incident data, THE PagerDuty_Agent SHALL query PagerDuty for incidents matching the specified service, severity, and time range.
2. THE PagerDuty_Agent SHALL return the incident ID, title, status, severity, assigned responder, timeline of events, and linked alerts for each retrieved incident.
3. WHEN an incident is identified, THE PagerDuty_Agent SHALL retrieve full incident details including body, impact description, affected services, acknowledgements, resolution notes, and log entries with timestamps.
4. WHEN an active Incident is identified, THE PagerDuty_Agent SHALL include the current responder and escalation policy in the Context_Window.
5. IF no incidents match the query criteria, THEN THE PagerDuty_Agent SHALL return an empty result set and notify the Orchestrator that no active incidents were found.

---

### Requirement 8: Cost Analysis Integration *(Catalog Entry — not in current roadmap)*

**User Story:** As a cloud engineer, I want the agent to query AWS Cost Explorer for cost and usage data, so that it can surface spending trends, identify cost anomalies, and support cost optimization recommendations.

> **Note:** This integration is architecturally supported via the Integration Sub-Agent Framework (Req 30) but is **not part of the current delivery roadmap**. It can be added at any time using the four-step onboarding checklist with zero Orchestrator changes. The CostExplorer_Agent would be registered in the `subagent-registry` under the `infrastructure_cloud` integration category.

#### Acceptance Criteria

1. WHEN a plan step requires cost data, THE CostExplorer_Agent SHALL query AWS Cost Explorer for the specified service, account, time range, and granularity (daily, monthly).
2. THE CostExplorer_Agent SHALL return total cost, cost by service, cost by tag, and month-over-month change for the requested scope.
3. WHEN cost anomalies are detected (spend more than 20% above the trailing 30-day average for a service), THE CostExplorer_Agent SHALL flag the anomaly and include it in the response with the affected service, anomalous period, and delta.
4. THE CostExplorer_Agent SHALL include the AWS account ID, currency, and query time range in all cost responses.
5. IF the Cost Explorer API returns an authorization error, THEN THE CostExplorer_Agent SHALL report the error to the Orchestrator with the HTTP status code and cease further cost queries for that request.

---

### Requirement 9: CloudWatch Integration *(Reference Implementation — Integration Sub-Agent Framework)*

**User Story:** As a cloud engineer, I want the agent to query CloudWatch metrics and logs, so that it can diagnose infrastructure issues and surface relevant observability data.

> **Note:** This requirement is a reference implementation of the Integration Sub-Agent Framework (Req 30). The CloudWatch_Agent satisfies the standard sub-agent interface contract and is registered in the `subagent-registry` under the `observability_monitoring` integration category.

#### Acceptance Criteria

1. WHEN a plan step requires metrics data, THE CloudWatch_Agent SHALL query CloudWatch Metrics for the specified namespace, metric name, dimensions, and time range.
2. WHEN a plan step requires log analysis, THE CloudWatch_Agent SHALL execute a CloudWatch Logs Insights query and return matching log events with timestamps and log group names.
3. THE CloudWatch_Agent SHALL summarize metric trends (average, p50, p95, p99, max) over the requested time range and include anomaly annotations where AWS Anomaly Detection flags are present.
4. IF a CloudWatch query returns more than 1,000 log events, THEN THE CloudWatch_Agent SHALL paginate results and return a summarized view with the option to retrieve the full dataset.
5. THE CloudWatch_Agent SHALL include the AWS account ID, region, and query execution time in all responses.

---

### Requirement 10: VictoriaMetrics Integration *(Reference Implementation — Integration Sub-Agent Framework)*

**User Story:** As a cloud engineer, I want the agent to query VictoriaMetrics for time-series metrics, so that it can access our custom observability stack alongside CloudWatch.

> **Note:** This requirement is a reference implementation of the Integration Sub-Agent Framework (Req 30). The VictoriaMetrics_Agent satisfies the standard sub-agent interface contract and is registered in the `subagent-registry` under the `observability_monitoring` integration category.

#### Acceptance Criteria

1. WHEN a plan step requires time-series data from VictoriaMetrics, THE VictoriaMetrics_Agent SHALL execute a MetricsQL query against the configured VictoriaMetrics endpoint.
2. THE VictoriaMetrics_Agent SHALL return metric labels, data points, and the query execution time for each result series.
3. WHEN both CloudWatch and VictoriaMetrics data are requested for the same time range, THE Orchestrator SHALL correlate the results and present a unified view.
4. IF the VictoriaMetrics endpoint is unreachable, THEN THE VictoriaMetrics_Agent SHALL report the connectivity error to the Orchestrator and mark the step as failed without blocking other plan steps.

---

### Requirement 11: GitHub Integration *(Reference Implementation — Integration Sub-Agent Framework)*

**User Story:** As a cloud engineer, I want the agent to interact with GitHub repositories, so that it can review IaC changes, inspect deployment history, and assist with PR reviews.

> **Note:** This requirement is a reference implementation of the Integration Sub-Agent Framework (Req 30). The GitHub_Agent satisfies the standard sub-agent interface contract and is registered in the `subagent-registry` under the `source_control_cicd` integration category.

#### Acceptance Criteria

1. WHEN a plan step requires code or configuration review, THE GitHub_Agent SHALL retrieve the specified file, PR, or commit from the configured GitHub organization.
2. WHEN a plan step requires code or repository discovery, THE GitHub_Agent SHALL execute a code search or repository search query against the configured GitHub organization and return matching file paths, repository names, and relevant excerpts.
3. THE GitHub_Agent SHALL analyze IaC files (Terraform, CloudFormation) for security misconfigurations, deprecated resource types, and deviations from internal naming conventions.
4. WHEN a PR is retrieved, THE GitHub_Agent SHALL summarize the changes, identify affected infrastructure resources, and flag any high-risk modifications.
5. THE GitHub_Agent SHALL retrieve the deployment history for a specified service by querying GitHub Actions workflow runs and return the last 10 deployments with status, actor, and timestamp.
6. IF a GitHub API rate limit is reached, THEN THE GitHub_Agent SHALL notify the Orchestrator, include the rate-limit reset time, and pause GitHub queries until the limit resets.

---

### Requirement 12: Vector Store and Semantic Search

**User Story:** As a platform operator, I want the agent to use Amazon Bedrock Knowledge Bases for semantic search across all indexed knowledge, so that it can find relevant context even when exact keyword matches don't exist, without managing vector store infrastructure.

#### Acceptance Criteria

1. THE system SHALL use Bedrock_Knowledge_Bases as the managed RAG service, with Amazon S3 as the document source and Amazon S3 Vectors as the vector store backend.
2. WHEN the Orchestrator queries the Knowledge_Base, Bedrock_Knowledge_Bases SHALL return the top-K results ranked by semantic similarity to the query embedding, where K is configurable (default: 5).
3. Bedrock_Knowledge_Bases SHALL support metadata filtering by source system, document type, team, and date range on all retrieval queries.
4. WHEN a document is deleted from a source system, the corresponding S3 source object SHALL be deleted and Bedrock_Knowledge_Bases SHALL re-sync the index within 1 hour via its managed ingestion pipeline.
5. Bedrock_Knowledge_Bases SHALL support incremental ingestion so that only new or modified documents are re-embedded during each sync cycle.
6. THE Bedrock_Knowledge_Bases instance, its S3 source bucket, S3 Vectors index, and IAM roles SHALL be provisioned and managed via the CloudFormation_Stack `knowledge` nested stack.

---

### Requirement 13: Execution Engine and Step Validation

**User Story:** As a platform operator, I want every execution step to be validated before and after it runs, so that the agent never takes destructive or incorrect actions based on incomplete information.

#### Acceptance Criteria

1. BEFORE executing any step, THE Orchestrator SHALL perform a pre-execution Validation_Step that checks all required inputs are present, the Sub-Agent is available, and the action is within the defined permission scope.
2. AFTER each step completes, THE Orchestrator SHALL perform a post-execution Validation_Step that verifies the output matches the expected schema and Confidence_Score threshold.
3. WHEN a post-execution Validation_Step fails, THE Orchestrator SHALL retry the step up to 2 times with enriched context before marking the step as failed.
4. THE Orchestrator SHALL write an immutable execution log entry to the `execution-logs` DynamoDB table (Req 27) for every step, recording the input, output, timestamp, Sub-Agent used, and validation result.
5. WHEN a destructive action (resource deletion, configuration change, deployment) is included in the Execution_Plan, THE Orchestrator SHALL require explicit user confirmation regardless of the approval configuration setting.
6. THE Orchestrator SHALL enforce a permission model where each Sub-Agent has a defined set of allowed actions, and THE Orchestrator SHALL reject any step that requests an action outside the Sub-Agent's allowed set.

---

### Requirement 14: Accuracy and Senior Engineer Quality

**User Story:** As an internal team member, I want the agent's outputs to reflect the judgment and accuracy of a senior cloud engineer, so that I can trust its recommendations and act on them without extensive manual verification.

#### Acceptance Criteria

1. THE Orchestrator SHALL cross-reference outputs against at least two independent sources (e.g., Knowledge_Base retrieval + live metric data) before presenting a diagnosis or recommendation.
2. WHEN the Orchestrator produces a recommendation, THE Orchestrator SHALL include a confidence level (high/medium/low), the supporting evidence, and any assumptions made.
3. THE Orchestrator SHALL flag any recommendation that relies solely on retrieved documentation without live data validation as "unverified against current state."
4. WHEN an execution produces a result that contradicts retrieved Knowledge_Base content, THE Orchestrator SHALL surface the contradiction to the user and present both perspectives.
5. THE Orchestrator SHALL apply cloud engineering best practices (least privilege, immutable infrastructure, observability-first) as evaluation criteria when reviewing IaC or deployment plans.
6. THE Orchestrator SHALL not present a final answer with a Confidence_Score below 0.8 without explicitly stating the uncertainty and the reason for it.

---

### Requirement 15: Observability and Audit

**User Story:** As a platform operator, I want full observability into the agent's decisions and actions, so that I can audit its behavior, debug failures, and continuously improve its accuracy.

#### Acceptance Criteria

1. THE Orchestrator SHALL emit structured logs for every request lifecycle event: request received, plan generated, step started, step completed, step failed, plan completed.
2. THE Orchestrator SHALL expose a trace for each request that maps the full execution path across all Sub-Agents, including latency per step.
3. WHEN a request results in an error or low-confidence output, THE Orchestrator SHALL generate a diagnostic report including the failed step, the error message, the context available at the time of failure, and suggested remediation.
4. THE Orchestrator SHALL retain execution logs and traces for a minimum of 90 days.
5. THE Orchestrator SHALL expose metrics for request volume, average execution time, step failure rate, and Confidence_Score distribution via a metrics endpoint compatible with VictoriaMetrics/Prometheus scraping.
6. THE system SHALL instrument every agent container (Orchestrator and all Sub-Agents) with the AWS Distro for OpenTelemetry (ADOT) Python SDK (`opentelemetry-sdk` + `opentelemetry-sdk-extension-aws` + `opentelemetry-propagator-aws-xray`), emitting traces, metrics, and logs to a configurable ADOT Collector endpoint.
7. THE system SHALL use AgentCore Observability as the primary production observability layer, with all features enabled: Runtime observability (session count, latency, token usage, error rates), Memory observability, Gateway observability (tool invocation counts, latency, error rates), execution path tracing, AWS X-Ray distributed traces, and CloudWatch Logs for all agent containers.
8. EVERY trace SHALL capture the following span attributes at minimum: `request_id`, `session_id`, `user_id`, `task_category`, `sub_agent_name`, `tool_name`, `tool_inputs` (redacted), `confidence_score`, `token_count`, `step_index`, `validation_result`, and `error_code` (if applicable).
9. THE ADOT SDK SHALL propagate trace context using the AWS X-Ray propagator in production and W3C TraceContext headers in local development, across all service boundaries — from Chainlit UI → Orchestrator → Sub-Agent → AgentCore Gateway → external tool — so that a single end-to-end trace is visible for every request.
10. EVERY LLM invocation SHALL be captured as a child span of the parent request trace, including: model ID, prompt token count, completion token count, latency, guardrail policy version applied, and guardrail action taken (PASS / BLOCK / REDACT).
11. EVERY tool call via AgentCore Gateway SHALL be captured as a child span including: tool name, MCP endpoint, input schema hash, response status, and latency.
12. THE Orchestrator SHALL emit a span event for each state transition in the LangGraph `StateGraph` (node entry, node exit, edge traversal, retry, escalation) so that the full graph execution path is reconstructable from the trace.
13. IN local development, VictoriaTraces SHALL receive all ADOT traces and display the full end-to-end trace including Chainlit → Orchestrator → Sub-Agent → Gateway hops with all span attributes, enabling multi-hop debugging.
14. IN local development, Langfuse SHALL capture every LLM prompt, completion, tool call, token count, latency, and RAG_Metric score. Langfuse is a local-only tool run via `docker-compose` and is NOT deployed to AWS.
15. IN local development, VictoriaMetrics SHALL serve as the Prometheus-compatible time-series metrics backend, replacing standalone Prometheus. VictoriaMetrics is a local-only tool run via `docker-compose` and is NOT deployed to AWS.
16. IN local development, Grafana SHALL provide pre-built dashboards pre-wired to VictoriaTraces, Langfuse, and VictoriaMetrics. Grafana is a local-only tool run via `docker-compose` and is NOT deployed to AWS.
17. THE repository SHALL include a `docker-compose.yml` at the repo root that starts a Local_Observability_Stack consisting of: a Chainlit UI (port 8000), an ADOT Collector, Langfuse, VictoriaTraces, VictoriaMetrics, and Grafana — all pre-configured to receive telemetry from locally running agents. Standalone Prometheus is NOT included — VictoriaMetrics handles all metrics scraping and storage.
18. WHEN running locally, THE agent containers SHALL emit ADOT telemetry to `http://localhost:4317` (the local ADOT Collector) with no code changes required relative to the production configuration.
19. THE ADOT exporter endpoint SHALL be configurable via the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable, with the `local` parameter set pointing to the local ADOT Collector and the `production` parameter set pointing to the AgentCore Observability endpoint.
20. A developer SHALL be able to start the full Local_Observability_Stack with a single `docker compose up` command and immediately see agent traces in VictoriaTraces, LLM traces in Langfuse, and metrics in Grafana without any additional configuration.
21. THE Local_Observability_Stack SHALL include pre-configured Grafana dashboards mirroring the structure of the production AgentCore Observability dashboards so that developers observe equivalent metrics and traces locally.

---

### Requirement 16: Prompt Template Management

**User Story:** As a platform operator, I want prompt templates to be versioned and centrally managed, so that system prompts and few-shot examples are consistent, auditable, and easy to update without code changes.

#### Acceptance Criteria

1. THE Orchestrator SHALL maintain a Prompt_Template registry backed by the `prompt-template-registry` DynamoDB table (Req 27), storing at least one versioned system prompt per task category (incident investigation, infrastructure change, cost analysis, deployment, monitoring query, knowledge retrieval, code review).
2. WHEN a Sub-Agent is invoked, THE Orchestrator SHALL select the Prompt_Template version corresponding to the task category and the active prompt configuration, and SHALL record the template ID and version in the execution log.
3. THE Orchestrator SHALL support injection of few-shot examples into a Prompt_Template based on the classified task type, selecting examples from a curated example store associated with that category.
4. BEFORE invoking any Sub-Agent, THE Orchestrator SHALL render the selected Prompt_Template with all required variable slots populated and SHALL validate that no unresolved placeholders remain in the rendered prompt.
5. IF a Prompt_Template rendering produces an unresolved placeholder, THEN THE Orchestrator SHALL abort the step, log the rendering error with the template ID and the missing variable name, and surface the error to the user.

---

### Requirement 17: RAG Quality and Retrieval Evaluation

**User Story:** As a platform operator, I want retrieval quality to be measured and enforced, so that only relevant, high-quality documents are included in the context passed to Sub-Agents.

#### Acceptance Criteria

1. WHEN Bedrock_Knowledge_Bases returns results for a query, THE Orchestrator SHALL compute and record precision@K and recall@K RAG_Metrics for that query, where K matches the configured retrieval count.
2. THE Orchestrator SHALL apply a re-ranking step after initial retrieval from Bedrock_Knowledge_Bases, using a cross-encoder or LLM-based scorer to reorder results by relevance before including them in the Context_Window.
3. Bedrock_Knowledge_Bases SHALL support a configurable chunking strategy per document type, including chunk size (in tokens) and overlap (in tokens), with defaults applied when no document-type-specific configuration exists.
4. WHEN a retrieved document's relevance score falls below the configured minimum relevance threshold, THE Orchestrator SHALL exclude that document from the Context_Window and SHALL log the exclusion with the document ID and score.
5. THE Orchestrator SHALL expose the per-query precision@K and recall@K values in the execution trace so that they are available for trend analysis via the observability metrics endpoint.

---

### Requirement 18: Tool Use Validation

**User Story:** As a platform operator, I want all tool calls to be validated before execution and tracked for accuracy, so that incorrect or malformed tool invocations are caught before they cause side effects.

#### Acceptance Criteria

1. BEFORE executing any Tool invocation, THE Orchestrator SHALL validate the tool call inputs against the Tool_Schema for that Tool, and IF validation fails THEN THE Orchestrator SHALL abort the step and return a schema validation error with the field name and constraint that was violated.
2. THE Orchestrator SHALL track tool selection accuracy as a metric, defined as the ratio of steps where the correct Tool was chosen to total Tool invocations, and SHALL expose this metric via the observability metrics endpoint.
3. THE Orchestrator SHALL support a dry-run mode for Tool invocations in which the tool call is validated against its Tool_Schema and logged but not executed against the external system.
4. WHEN dry-run mode is active, THE Orchestrator SHALL return a dry-run result indicating the Tool that would have been called, the validated inputs, and the expected output schema, without performing any external action.

---

### Requirement 19: Evaluation Framework

**User Story:** As a platform operator, I want a comprehensive offline and online evaluation framework, so that model and prompt quality is continuously measured, regressions are caught before deployment, and live output quality is monitored.

#### Acceptance Criteria

1. THE Evaluation_Pipeline SHALL maintain a versioned Golden_Dataset of at least 50 labeled request/response pairs per task category, stored in the `golden-dataset` S3 bucket (Req 28) with S3 Versioning enabled as the authoritative source.
2. WHEN a model version or Prompt_Template version changes, THE Evaluation_Pipeline SHALL automatically execute an offline evaluation run against the full Golden_Dataset before the change is eligible for deployment. The trigger SHALL be implemented as a CI/CD pipeline step that detects version changes in the model ID or prompt template registry and invokes the evaluation runner.
3. THE Evaluation_Pipeline SHALL measure and record the following metrics for each offline evaluation run: answer correctness, tool selection accuracy, faithfulness, answer relevance, context precision, context recall (RAGAS-style RAG_Metrics), plan quality score, and response latency (p50 and p95).
4. WHEN an offline evaluation run produces a score that is more than 5% below the established baseline on any metric, THE Evaluation_Pipeline SHALL block the deployment and generate a regression report identifying the affected metric, the baseline value, the new value, and the delta.
5. THE Orchestrator SHALL sample 5% of live production requests and route them to a human review queue with a structured rubric covering correctness, completeness, safety, and alignment with senior engineer judgment.
6. THE Evaluation_Pipeline SHALL store all evaluation run results, metric values, and Golden_Dataset versions in a queryable data store, retaining results for a minimum of 180 days to support trend analysis.

---

### Requirement 20: Guardrails and Safety

**User Story:** As a platform operator, I want Amazon Bedrock Guardrails enforced on all LLM interactions, so that PII, secrets, prompt injections, hallucinations, and unsafe content are detected and mitigated by a managed service without custom guardrail code.

#### Acceptance Criteria

1. THE system SHALL configure a Bedrock_Guardrails policy applied to all LLM invocations by the Orchestrator and Sub-Agents, covering: PII detection and masking (names, email addresses, API keys, secrets, tokens), prompt injection detection, content safety filtering, and grounding checks for hallucination detection.
2. WHEN Bedrock_Guardrails detects PII in an input or output, it SHALL automatically redact the PII and replace it with a typed placeholder (e.g., {NAME}, {EMAIL}, {API_KEY}) before the content reaches the LLM or the user.
3. WHEN Bedrock_Guardrails detects a prompt injection attempt, it SHALL block the request and return a policy violation message to the Orchestrator, which SHALL log the event with severity HIGH and surface an explanation to the user.
4. WHEN Bedrock_Guardrails detects harmful, offensive, or policy-violating content in an input or output, it SHALL block the content and return a policy violation message to the user.
5. WHEN Bedrock_Guardrails grounding checks detect a hallucinated or ungrounded claim in an LLM output, it SHALL flag the output and the Orchestrator SHALL suppress it and request a regeneration with enriched context.
6. ALL Bedrock_Guardrails violation events SHALL be logged to a dedicated DynamoDB table (guardrail-violations) with: violation type, severity, redacted offending content, request ID, guardrail policy version, and UTC timestamp — retained for a minimum of 90 days.
7. THE Bedrock_Guardrails policy, its configuration, and the guardrail-violations DynamoDB table SHALL be provisioned and managed via the CloudFormation_Stack.

---

### Requirement 21: Bedrock AgentCore Runtime Deployment

**User Story:** As a platform operator, I want every agent (Orchestrator and all Sub-Agents) deployed as a containerized workload on Amazon Bedrock AgentCore Runtime, so that I get enterprise-grade session isolation, serverless scaling, and long-running execution support without managing infrastructure.

#### Acceptance Criteria

1. THE Orchestrator and each Sub-Agent SHALL be packaged as a container image and deployed to AgentCore_Runtime as a separate AgentCore Runtime endpoint.
2. EACH AgentCore_Runtime deployment SHALL be configured with Firecracker VM-level session isolation so that no agent session shares memory or compute with another session.
3. THE AgentCore_Runtime deployment for the Orchestrator SHALL be configured to support long-running workloads with a session timeout of up to 8 hours to accommodate complex multi-step executions.
4. ALL AgentCore_Runtime endpoints SHALL be deployed into an existing VPC and subnets provided as CloudFormation stack parameter inputs (`VpcId` and `SubnetIds`), with AWS PrivateLink enabled so that no agent traffic traverses the public internet.
5. WHEN an AgentCore_Runtime endpoint becomes unhealthy, the platform SHALL automatically restart the endpoint without operator intervention, and the Orchestrator SHALL retry the affected step.
6. THE AgentCore_Runtime deployment SHALL use LangChain and LangGraph as the agent framework, with Claude (via Amazon Bedrock) as the default foundation model.

---

### Requirement 22: AgentCore Memory Integration

**User Story:** As an internal team member, I want the agent to maintain conversation context across turns and remember relevant context from past sessions, so that I don't have to repeat myself and the agent improves over time.

#### Acceptance Criteria

1. THE Orchestrator SHALL use AgentCore_Memory for short-term memory to maintain the full conversation context across all turns within a single session.
2. THE Orchestrator SHALL use AgentCore_Memory for long-term memory to persist user preferences, frequently referenced services, and past incident resolutions across sessions.
3. WHEN a new session starts, THE Orchestrator SHALL query AgentCore_Memory for long-term context relevant to the current request and include it in the initial Context_Window.
4. AgentCore_Memory stores SHALL be shared across the Orchestrator and all Sub-Agents so that any Sub-Agent can read context written by another Sub-Agent within the same session.
5. ALL memory writes SHALL be scoped to the authenticated user identity so that one user's memory is never accessible to another user.

---

### Requirement 23: AgentCore Gateway for Tool Integration

**User Story:** As a platform operator, I want all external tool integrations exposed through AgentCore Gateway as MCP-compatible tools, so that agents can discover and invoke tools through a single secure endpoint without point-to-point integrations, and new integrations can be added without modifying existing agent code.

#### Acceptance Criteria

1. EACH external tool integration SHALL be registered in AgentCore_Gateway as an MCP-compatible tool endpoint; the set of registered integrations is not fixed and SHALL grow as new Sub-Agents are added.
2. THE AgentCore_Gateway SHALL serve as the single entry point for all tool invocations from Sub-Agents, replacing direct API calls from agent code to external systems.
3. ALL tool endpoints registered in AgentCore_Gateway SHALL require OAuth2 authentication, and AgentCore_Identity SHALL manage the credential lifecycle for each tool.
4. THE AgentCore_Gateway SHALL provide a tool discovery endpoint that the Orchestrator queries at startup to populate the Sub-Agent registry with available tools and their Tool_Schemas.
5. WHEN a new tool integration is added, it SHALL be registerable in AgentCore_Gateway without requiring a redeployment of any existing agent container.
6. THE AgentCore_Gateway SHALL enforce per-tool rate limits and SHALL return a structured rate-limit error to the calling Sub-Agent when a limit is exceeded.

---

### Requirement 24: AgentCore Identity and Access Management

**User Story:** As a platform operator, I want all agent-to-tool and agent-to-agent authentication managed by AgentCore Identity, so that credentials are never hardcoded, rotated automatically, and access is auditable.

#### Acceptance Criteria

1. ALL agent identities (Orchestrator and each Sub-Agent) SHALL be provisioned as AgentCore_Identity principals with scoped IAM roles following least-privilege principles.
2. THE AgentCore_Identity service SHALL integrate with the organization's existing IdP (Okta or Azure Entra ID) for user-to-agent authentication.
3. NO credentials, API keys, or secrets SHALL be embedded in agent container images or environment variables; all secrets SHALL be retrieved at runtime from AWS Secrets Manager via AgentCore_Identity.
4. WHEN a user authenticates to the system via the Chainlit UI or another interface, THE AgentCore_Identity service SHALL issue a scoped session token that is propagated to all Sub-Agents invoked within that session.
5. ALL agent identity events (authentication, token issuance, access denial) SHALL be logged to AWS CloudTrail for audit purposes.

---

### Requirement 25: CloudFormation IaC for All Infrastructure

**User Story:** As a platform operator, I want all infrastructure — agents, memory stores, gateway configurations, identity policies, networking, and supporting AWS resources — defined as CloudFormation IaC, so that the entire system is reproducible, version-controlled, and deployable to any environment with a single command.

#### Acceptance Criteria

1. ALL AWS resources required by the system SHALL be defined in a CloudFormation_Stack using nested CloudFormation templates, including: AgentCore Runtime endpoints, AgentCore Memory stores, AgentCore Gateway tool registrations, AgentCore Identity principals, Bedrock_Knowledge_Bases instance and S3 Vectors index, Bedrock_Guardrails policy, DynamoDB tables (execution-logs, subagent-registry, prompt-template-registry, guardrail-violations, eval-run-results, human-review-queue, session-state), S3 buckets (golden-dataset, eval-results, artifacts), Athena workgroup and Glue Data Catalog, VPC Endpoints and Security Groups (deployed into existing VPC/subnets provided via parameters), IAM roles and policies, Secrets Manager secrets, KMS keys, and CloudWatch log groups. The CloudFormation_Stack SHALL NOT create or modify the VPC, subnets, route tables, or gateways — these are provided as parameter inputs.
2. THE CloudFormation_Stack SHALL be organized into the following nested stacks: `agents` (one nested stack per agent), `gateway` (AgentCore Gateway + tool registrations), `memory` (AgentCore Memory stores), `knowledge` (Bedrock Knowledge Bases + S3 source bucket + S3 Vectors), `guardrails` (Bedrock Guardrails policy), `data` (all DynamoDB tables + KMS keys), `storage` (S3 buckets + Athena + Glue), `networking` (VPC Endpoints + Security Groups deployed into existing VPC/subnets from parameters — no VPC or subnet creation), `identity` (AgentCore Identity + IAM roles + Secrets Manager), and `observability` (AgentCore Observability configuration, ADOT Collector, Chainlit UI on ECS Fargate, CloudWatch log groups). Langfuse, VictoriaMetrics, and Grafana are local-only tools run via `docker-compose` and are NOT provisioned in any CloudFormation stack.
3. THE CloudFormation_Stack SHALL support two named parameter sets: `local` and `production`, each with environment-specific configuration (model IDs, memory store sizes, token budgets), managed via CloudFormation parameter files.
4. ALL CloudFormation stack outputs SHALL export the AgentCore Runtime endpoint ARNs, Gateway endpoint URL, Memory store IDs, Identity pool IDs, Bedrock Knowledge Bases KB ID, Bedrock Guardrails policy ARN, and all DynamoDB table ARNs so that they can be consumed by CI/CD pipelines and other stacks.
5. THE CloudFormation_Stack SHALL be deployable with `aws cloudformation deploy` from a clean AWS account with only the required IAM permissions, completing full infrastructure provisioning without manual steps.
6. WHEN a new Sub-Agent is added to the system, its AgentCore Runtime endpoint, IAM role, Gateway tool registration, and Memory store access policy SHALL be provisionable by adding a single new CloudFormation template under `cloudformation/stacks/application/agents/<name>.yaml` without modifying any existing template.
7. THE CloudFormation_Stack SHALL support a `aws cloudformation delete-stack` target that cleanly removes all provisioned resources in dependency order without leaving orphaned resources.

---

### Requirement 26: Observability Stack Deployment (CloudFormation)

**User Story:** As a platform operator, I want the production observability stack defined in CloudFormation IaC, using AgentCore Observability as the primary monitoring layer, so that observability infrastructure is provisioned, configured, and version-controlled as part of the same deployment pipeline.

#### Acceptance Criteria

1. THE CloudFormation_Stack SHALL include a dedicated observability nested stack that provisions: a Chainlit UI instance on ECS Fargate behind an internal ALB within the existing VPC, an ADOT Collector deployment, and CloudWatch log groups for all agents. Langfuse, VictoriaMetrics, and Grafana SHALL NOT be provisioned in AWS — they are local development tools only, run via `docker-compose`.
2. THE system SHALL use AgentCore Observability as the primary production observability layer, providing CloudWatch-powered dashboards for session count, latency, duration, token usage, error rates, and execution path tracing across all AgentCore services.
3. ALL observability services SHALL be deployed into the existing VPC and subnets provided via CloudFormation stack parameters, accessible only via private subnets and AWS PrivateLink.
4. THE ADOT Collector SHALL be configured to route traces to AWS X-Ray in production, with the routing rules defined in the CloudFormation stack parameters.
5. THE `local` CloudFormation parameter set SHALL set all agent `OTEL_EXPORTER_OTLP_ENDPOINT` values to the local ADOT Collector endpoint (`http://localhost:4317`) so that local development routes telemetry to the docker-compose stack (Jaeger, Langfuse, VictoriaMetrics, Grafana) without requiring AWS credentials for observability.

---

### Requirement 27: DynamoDB Data Store

**User Story:** As a platform operator, I want all structured operational data — execution logs, registries, audit logs, evaluation records, and session state — stored in Amazon DynamoDB, so that the system has a fully serverless, high-throughput, zero-ops structured data layer.

#### Acceptance Criteria

1. THE system SHALL provision the following DynamoDB tables, each managed via the CloudFormation_Stack:
   - `execution-logs`: PK=`requestId`, SK=`stepTimestamp` — stores immutable execution log entries per step (Req 13.4)
   - `subagent-registry`: PK=`agentId` — stores Sub-Agent capability descriptors, tool schemas, and availability state (Req 4.1)
   - `prompt-template-registry`: PK=`taskCategory`, SK=`version` — stores versioned Prompt_Templates per task category (Req 16)
   - `guardrail-violations`: PK=`requestId`, SK=`violationTimestamp`, GSI on `violationType` + `violationTimestamp` — stores Bedrock_Guardrails violation audit log (Req 20.6)
   - `eval-run-results`: PK=`runId`, SK=`timestamp`, GSI on `taskCategory` + `timestamp` — stores offline evaluation run metric scores (Req 19)
   - `human-review-queue`: PK=`reviewId`, SK=`submittedAt`, GSI on `status` + `submittedAt` — stores 5% sampled live requests pending human review (Req 19.5)
   - `session-state`: PK=`sessionId` — stores active session state, pending approval state, and missing input state with TTL-based expiry (Req 2.5, 3)
2. ALL DynamoDB tables SHALL be provisioned with on-demand (pay-per-request) billing mode to match the bursty agent workload pattern.
3. ALL DynamoDB tables SHALL have point-in-time recovery (PITR) enabled.
4. THE `execution-logs` and `guardrail-violations` tables SHALL have a DynamoDB TTL attribute set to enforce the 90-day retention requirement (Req 13.4, 20.6).
5. THE `eval-run-results` table SHALL have a DynamoDB Streams export configured to write records to the S3 eval-results bucket for Athena analytics (Req 19.6).
6. ALL DynamoDB tables SHALL be encrypted at rest using AWS KMS keys managed via the CloudFormation_Stack.
7. ALL DynamoDB table definitions, GSIs, TTL configurations, stream configurations, and KMS keys SHALL be provisioned and managed via the CloudFormation_Stack.

---

### Requirement 28: S3 and Athena Data Layer

**User Story:** As a platform operator, I want Golden Dataset files, artifacts, and evaluation analytics data stored in S3 with Athena for ad-hoc trend queries, so that I have a cost-efficient, serverless analytics layer without maintaining a relational database.

#### Acceptance Criteria

1. THE system SHALL provision the following S3 buckets, each managed via the CloudFormation_Stack:
   - `golden-dataset`: stores versioned Golden_Dataset JSONL files per task category, with S3 Versioning enabled (Req 19.1)
   - `eval-results`: receives DynamoDB Streams exports of eval run results for Athena analytics, partitioned by `year/month/taskCategory` (Req 19.6)
   - `artifacts`: stores Grafana dashboard JSON definitions, CloudFormation template backups, and prompt template backups (Req 26.4)
2. ALL S3 buckets SHALL have server-side encryption enabled using AWS KMS keys managed via the CloudFormation_Stack.
3. ALL S3 buckets SHALL have public access blocked and bucket policies enforcing VPC-only access via S3 VPC endpoints.
4. THE `eval-results` bucket SHALL have an AWS Glue Data Catalog table defined over it, partitioned by `year`, `month`, and `taskCategory`, enabling Athena to query eval trend data with standard SQL.
5. THE system SHALL use Amazon Athena to execute ad-hoc trend analytics queries over the `eval-results` bucket, including: metric score averages by task category over configurable date ranges, regression detection across eval runs, and latency percentile trends.
6. THE Athena workgroup, Glue Data Catalog database and table, S3 query results bucket, and all associated IAM roles SHALL be provisioned and managed via the CloudFormation_Stack.
7. THE `golden-dataset` bucket SHALL be the authoritative source for the Evaluation_Pipeline, with the pipeline reading JSONL files directly from S3 at eval run time.

---

### Requirement 29: Chainlit Chat UI

**User Story:** As an internal team member, I want a web-based chat interface to interact with the agent, so that I can submit requests, see real-time execution status for each step, and receive structured output without using a raw API.

#### Acceptance Criteria

1. THE system SHALL provide a Chainlit-based chat UI deployed as a containerized service within the existing VPC, accessible to internal team members via a private load balancer endpoint.
2. WHEN a user submits a request via the Chainlit UI, THE UI SHALL forward the request to the Orchestrator and display a real-time step indicator for each plan step as it executes, showing the sub-agent name, tool invoked, and current status (running / completed / failed).
3. THE Chainlit UI SHALL render the Execution_Plan as a collapsible structured list before execution begins, allowing the user to approve, modify, or cancel the plan inline.
4. WHEN the Orchestrator prompts for missing inputs or user confirmation, THE Chainlit UI SHALL surface the prompt as an interactive message with a text input or confirmation buttons, and SHALL forward the user's response back to the Orchestrator.
5. THE Chainlit UI SHALL render final responses in structured format: markdown for narrative text, collapsible JSON blocks for raw tool outputs, tables for metric data, and inline citations (source title + URL) for all KB-sourced content.
6. THE Chainlit UI SHALL display a confidence indicator (high / medium / low) alongside each recommendation, and SHALL visually distinguish flagged low-confidence steps from normal steps.
7. THE Chainlit UI SHALL maintain full conversation history within a session, allowing the user to scroll back through prior requests, plans, and responses.
8. THE Chainlit UI SHALL integrate with AgentCore Identity for user authentication — users SHALL authenticate via the configured IdP (Okta or Azure Entra ID) before accessing the UI.
9. THE Chainlit UI container SHALL be provisioned and managed via the CloudFormation_Stack `observability` nested stack, deployed as an ECS Fargate task within the existing VPC private subnets.
10. THE Chainlit UI SHALL be included in the `docker-compose.yml` Local_Observability_Stack so developers can run it locally on port 8000 without AWS credentials.

---

### Requirement 30: Integration Sub-Agent Framework

**User Story:** As a platform operator, I want a well-defined contract that every Sub-Agent integration must satisfy, so that new integrations can be added by any team member without modifying the Orchestrator or any existing Sub-Agent.

#### Acceptance Criteria

1. THE system SHALL define a standard Sub-Agent interface contract that every integration MUST implement, consisting of: a `capabilityDescriptor` string (plain-language description of what the agent can do), a `supportedTools` list (tool names exposed via AgentCore Gateway), an `inputSchema` (JSON Schema for the `/invocations` request body), an `outputSchema` (JSON Schema for the `/invocations` response body), an `allowedActions` list (scoped permission set enforced by the Orchestrator), and a `category` field (one of the integration categories defined in Req 31).
2. EVERY Sub-Agent SHALL expose `POST /invocations` and `GET /ping` endpoints as defined by the AgentCore Runtime contract, with `/ping` returning `{"status": "Healthy"}`.
3. EVERY Sub-Agent SHALL implement its tools as `BaseTool` subclasses in `src/agents/<name>/tools.py` and build its `AgentExecutor` via the shared `base.py` factory in `src/agents/base.py`.
4. EVERY Sub-Agent SHALL return a response conforming to the standard output schema: `result` (tool output), `confidence_score` (0.0–1.0), `sources` (list of citations with title, URL, and timestamp), and `error` (structured `StepError` or null).
5. IF a Sub-Agent encounters an unrecoverable error, THEN THE Sub-Agent SHALL return a structured `StepError` with fields: `code`, `message`, `httpStatus` (if applicable), `retryAfter` (if rate-limited), `subAgent`, and `tool`.
6. EVERY Sub-Agent SHALL be registered in the `subagent-registry` DynamoDB table with all required fields (Req 27) before the Orchestrator will route plan steps to it.
7. THE Orchestrator SHALL contain no hardcoded references to specific Sub-Agent names, tool names, or integration categories; all routing decisions SHALL be made exclusively from data read from the `subagent-registry` at runtime.
8. WHEN a new Sub-Agent is deployed and registered in the `subagent-registry`, THE Orchestrator SHALL begin routing matching plan steps to it on the next request without requiring a restart or redeployment.

---

### Requirement 31: Integration Categories

**User Story:** As a platform operator, I want integrations organized into well-defined categories, so that the Orchestrator can reason about which type of system to query for a given plan step, and so that the catalog of available integrations is easy to navigate and extend.

#### Acceptance Criteria

1. THE `subagent-registry` SHALL classify every registered Sub-Agent under exactly one of the following integration categories:
   - `observability_monitoring` — tools that query metrics, logs, traces, and dashboards (e.g., CloudWatch, VictoriaMetrics, NewRelic, Datadog, Dynatrace)
   - `incident_management` — tools that manage incidents, alerts, and on-call workflows (e.g., PagerDuty, OpsGenie, VictoriaMetrics Alertmanager)
   - `communication_collaboration` — tools that send messages, create tickets, or retrieve team content (e.g., Confluence, Microsoft Teams, Slack, Jira)
   - `source_control_cicd` — tools that interact with code repositories, pull requests, pipelines, and deployments (e.g., GitHub, GitLab, Jenkins, ArgoCD)
   - `infrastructure_cloud` — tools that query or manage cloud infrastructure, IaC state, and cost data (e.g., AWS services, Terraform state, AWS Cost Explorer)
   - `knowledge_documentation` — tools that retrieve internal documentation, runbooks, wikis, and architectural records (e.g., Confluence, internal wikis, runbook stores)
2. WHEN the Orchestrator generates an Execution_Plan step, THE Orchestrator SHALL include the expected integration category in the step descriptor so that the capability matching algorithm (Req 30.7) can use category as a primary filter before evaluating `capabilityDescriptor` similarity.
3. THE `subagent-registry` DynamoDB table SHALL enforce that the `category` field is present and contains one of the six defined values on every write; records with an invalid or missing `category` SHALL be rejected.
4. The six integration categories are a **closed enum** enforced at write time (Req 31.3). New Sub-Agents within any existing category are unrestricted and require no schema or code changes — only a valid `subagent-registry` record with one of the six defined category values.

---

### Requirement 32: Integration Catalog and Extensibility Model

**User Story:** As a platform operator, I want a clear, documented model for adding new integrations, so that any team member can onboard a new tool (NewRelic, Dynatrace, OpsGenie, Microsoft Teams, Slack, Datadog, or any other) by following a four-step checklist with zero changes to the Orchestrator or any existing Sub-Agent.

#### Acceptance Criteria

1. THE system SHALL define and document the following four-step checklist as the complete and sufficient procedure for adding any new integration:
   - Step 1: Create `src/agents/<name>/tools.py` — implement each tool as a `BaseTool` subclass; no bare functions.
   - Step 2: Create `src/agents/<name>/agent.py` — build the `AgentExecutor` via the `base.py` factory.
   - Step 3: Create `cloudformation/stacks/application/agents/<name>.yaml` — use the `agent-runtime-endpoint` CloudFormation module; provisions AgentCore Runtime endpoint, scoped IAM role, and Gateway registration.
   - Step 4: Register the new agent in the `subagent-registry` DynamoDB table with all required fields including `capabilityDescriptor`, `supportedTools`, `inputSchema`, `outputSchema`, `allowedActions`, `category`, `version`, and `healthStatus`.
2. WHEN all four steps are complete, THE Orchestrator SHALL automatically discover and route to the new Sub-Agent on the next request without any code changes, configuration changes, or redeployments to the Orchestrator or any existing Sub-Agent.
3. THE `subagent-registry` DynamoDB table SHALL include the following fields on every record to support catalog management: `version` (semver string of the agent implementation), `healthStatus` (HEALTHY | DEGRADED | UNAVAILABLE, updated by the agent's health check), `category` (one of the six values from Req 31), `lastHealthCheck` (ISO-8601 timestamp), and `registeredAt` (ISO-8601 timestamp).
4. THE Orchestrator SHALL exclude Sub-Agents with `healthStatus` of `UNAVAILABLE` from plan step routing and SHALL log a warning when a previously available Sub-Agent transitions to `UNAVAILABLE`.
5. THE system SHALL support the following integration categories with the listed example integrations as candidates for future Sub-Agents (these are not required to be implemented but SHALL be architecturally supportable without code changes to the Orchestrator):
   - `observability_monitoring`: NewRelic, Datadog, Dynatrace, Grafana Cloud
   - `incident_management`: OpsGenie, VictoriaMetrics Alertmanager
   - `communication_collaboration`: Microsoft Teams, Slack, Jira
   - `source_control_cicd`: GitLab, Jenkins, ArgoCD
   - `infrastructure_cloud`: Terraform Cloud, Infracost *(CostExplorer_Agent is a catalog entry — see Req 8)*
   - `knowledge_documentation`: Notion, internal wiki systems
6. THE CloudFormation `agent-runtime-endpoint` module SHALL be the sole mechanism for provisioning new Sub-Agent infrastructure; no other stacks SHALL require modification when a new Sub-Agent is added.
14. IN local development, Langfuse SHALL capture every LLM prompt, completion, tool call, token count, latency, and RAG_Metric score. Langfuse is a local-only tool run via `docker-compose` and is NOT deployed to AWS.
15. IN local development, VictoriaMetrics SHALL serve as the Prometheus-compatible time-series metrics backend, replacing standalone Prometheus. VictoriaMetrics is a local-only tool run via `docker-compose` and is NOT deployed to AWS.
16. IN local development, Grafana SHALL provide pre-built dashboards pre-wired to VictoriaTraces, Langfuse, and VictoriaMetrics. Grafana is a local-only tool run via `docker-compose` and is NOT deployed to AWS.
17. THE repository SHALL include a `docker-compose.yml` at the repo root that starts a Local_Observability_Stack consisting of: a Chainlit UI (port 8000), an ADOT Collector, Langfuse, VictoriaTraces, VictoriaMetrics, and Grafana — all pre-configured to receive telemetry from locally running agents. Standalone Prometheus is NOT included — VictoriaMetrics handles all metrics scraping and storage.
18. WHEN running locally, THE agent containers SHALL emit ADOT telemetry to `http://localhost:4317` (the local ADOT Collector) with no code changes required relative to the production configuration.
19. THE ADOT exporter endpoint SHALL be configurable via the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable, with the `local` parameter set pointing to the local ADOT Collector and the `production` parameter set pointing to the AgentCore Observability endpoint.
20. A developer SHALL be able to start the full Local_Observability_Stack with a single `docker compose up` command and immediately see agent traces in VictoriaTraces, LLM traces in Langfuse, and metrics in Grafana without any additional configuration.
21. THE Local_Observability_Stack SHALL include pre-configured Grafana dashboards mirroring the structure of the production AgentCore Observability dashboards so that developers observe equivalent metrics and traces locally.
