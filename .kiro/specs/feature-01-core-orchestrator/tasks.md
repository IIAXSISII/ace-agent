# Tasks: F01 — Core Orchestrator

> Implements requirements in `requirements.md`. All tasks are locally runnable — no AWS deployment required except Bedrock API for LLM inference.

---

## Task List

- [x] 1. Project scaffold and dependencies
  - [x] 1.1 Create `src/` directory structure with all `__init__.py` files matching `structure.md` layout
  - [x] 1.2 Create `pyproject.toml` with all F01 dependencies pinned
  - [x] 1.3 Create `.env.example` with all required local environment variables documented
  - [x] 1.4 Create `Makefile` at repo root with targets: `dev`, `test`, `lint`, `docker-up`, `docker-down`

- [x] 2. OrchestratorState and graph skeleton
  - [x] 2.1 Define `OrchestratorState` TypedDict in `src/orchestrator/graph.py` with all fields from design
  - [x] 2.2 Wire `StateGraph` with all 12 nodes registered and all conditional edges
  - [x] 2.3 Implement all safety edge checks: hop limit (10), cycle detection, token budget
  - [x] 2.4 Compile graph with `MemorySaver` checkpointer via `get_checkpointer()` from `memory.py`

- [x] 3. Memory module
  - [x] 3.1 Implement `get_checkpointer()` in `src/orchestrator/memory.py` — returns `MemorySaver` when `AGENTCORE_MEMORY_STORE_ID` unset, `AgentCoreMemorySaver` otherwise

- [x] 4. Storage helpers
  - [x] 4.1 Implement `src/storage/dynamodb.py` with helpers: `get_item`, `put_item`, `query`, `update_item` for all 7 tables
  - [x] 4.2 Implement `src/storage/s3.py` with helpers: `get_object`, `put_object`, `list_objects` for all 3 buckets
  - [x] 4.3 Add local mock mode: when `MOCK_STORAGE=true`, helpers return in-memory fixtures instead of calling AWS

- [x] 5. Prompt template loader
  - [x] 5.1 Implement `load_prompt_template(task_category, version)` in `src/orchestrator/prompts.py` — loads from `prompt-template-registry` DynamoDB and returns `ChatPromptTemplate`
  - [x] 5.2 Implement local mock fallback: when `MOCK_PROMPTS=true`, load templates from `src/orchestrator/mock_templates/` YAML files; when `MOCK_PROMPTS=false` and DynamoDB is unavailable, raise `PromptTemplateLoadError` with diagnostic message including table name and missing key
  - [x] 5.3 Create mock template YAML files for all 7 task categories under `src/orchestrator/mock_templates/`
  - [x] 5.4 Implement rendered-prompt validation in `load_prompt_template()` after rendering: raise `UnresolvedPlaceholderError` with template ID and missing variable name if any `{variable}` remains unresolved after all slots are filled

- [x] 6. Graph nodes — classification and planning
  - [x] 6.1 Implement `classify_request` node: LLM call → `task_category`, `entities`, `confidence_score`; sets `clarifying_question` when confidence < 0.7
  - [x] 6.2 Implement `retrieve_knowledge` node: local mock returns 2–3 fixture documents (title, url, content) so property 21 is testable locally; reads `KNOWLEDGE_BASE_ID` env var to switch to `AmazonKnowledgeBasesRetriever` when set
  - [x] 6.3 Implement `detect_missing_inputs` node: LLM call → populates `missing_inputs` from plan step schemas
  - [x] 6.4 Implement `generate_plan` node: LLM call → `execution_plan` with per-step `confidence_score`; flags steps < 0.75
  - [x] 6.5 Implement `present_plan` node: sets `pending_approval = True`; emits plan to Chainlit via callback; waits for user confirm/modify signal

- [x] 7. Graph nodes — execution and validation
  - [x] 7.1 Implement `validate_step_pre` node: checks inputs present, sub-agent available in registry, action within `allowedActions`
  - [x] 7.2 Implement `invoke_subagent` node: queries `subagent-registry`, runs two-phase capability match, invokes selected agent, enforces 120s timeout, tracks `hop_count` and `visited_steps`
  - [x] 7.3 Implement `validate_step_post` node: checks output schema, confidence threshold; increments retry counter; routes to retry or escalate
  - [x] 7.4 Implement `aggregate_results` node: LLM call → unified response; cross-references ≥2 sources; computes final confidence; flags uncertainty when < 0.8; flags output as "unverified against current state" when no live sub-agent data used (Req 14.3)
  - [x] 7.5 Implement `scan_output_guardrails` node: local passthrough; reads `GUARDRAIL_ID` env var to activate `ChatBedrock` guardrailConfig when set
  - [x] 7.6 Implement `write_execution_log` node: writes `ExecutionLogEntry` to `execution-logs` DynamoDB table via storage helper; sets 90-day TTL
  - [x] 7.7 Implement `prompt_user` node: consolidates `missing_inputs` into single prompt; validates user response; re-prompts on invalid input

- [x] 8. Mock sub-agents
  - [x] 8.1 Implement `MockSubAgent` in `src/agents/mock/agent.py` with standard sub-agent interface (invoke returns canned result with confidence_score=0.85)
  - [x] 8.2 Seed `subagent-registry` mock data in-memory when `MOCK_STORAGE=true` — one entry per integration category (6 entries total) with all required fields
  - [x] 8.3 Implement `src/agents/base.py` with `build_agent_executor()` factory and conditional Langfuse `CallbackHandler` wiring

- [x] 9. FastAPI entrypoint
  - [x] 9.1 Implement `src/orchestrator/main.py` with `GET /ping` → `{"status": "Healthy"}` and `POST /invocations` → graph invocation
  - [x] 9.2 Wire ADOT `TracerProvider` initialization (`init_tracer()`) at app startup
  - [x] 9.3 Add request/response logging middleware for lifecycle events (request received, plan generated, plan completed)

- [x] 10. Observability
  - [x] 10.1 Implement `src/observability/otel.py`: `init_tracer()` with `AwsXRayIdGenerator`, `BatchSpanProcessor`, `OTLPSpanExporter` pointed at `OTEL_EXPORTER_OTLP_ENDPOINT`
  - [x] 10.2 Implement `src/observability/langfuse.py`: `get_langfuse_handler()` returns `langfuse.langchain.CallbackHandler` when `OTEL_STACK=local`, else `None`
  - [x] 10.3 Add Prometheus-compatible `/metrics` endpoint to FastAPI app exposing: request volume, avg execution time, step failure rate, confidence_score distribution

- [x] 11. Chainlit UI
  - [x] 11.1 Implement `src/ui/app.py` with `@cl.on_chat_start` and `@cl.on_message` satisfying all 7 Req 29 acceptance criteria
  - [x] 11.2 Implement `src/ui/handlers.py`: `ChainlitStepHandler(BaseCallbackHandler)` — `on_chain_start` opens `cl.Step`, `on_tool_start` streams tool name + inputs, `on_chain_end` closes step
  - [x] 11.3 Implement `src/ui/renderers.py`: `render_plan()`, `render_citations()`, `render_confidence()` helpers
  - [x] 11.4 Implement `src/ui/auth.py`: no-op when `CHAINLIT_AUTH_SECRET` unset; OAuth callback stub when set
  - [x] 11.5 Create `chainlit.md` welcome message and `chainlit.toml` config (theme, project name)

- [x] 12. Local observability stack
  - [x] 12.1 Create `docker-compose.yml` with all 8 services: `chainlit` (8000), `orchestrator` (8080), `adot-collector` (4317/4318), `victoriatraces` (9428), `langfuse` (3000), `langfuse-db`, `victoriametrics` (9091), `grafana` (3001)
  - [x] 12.2 Create `otel-collector-config.yaml`: traces → VictoriaTraces, metrics → VictoriaMetrics via `prometheusremotewrite`; W3C TraceContext propagation
  - [x] 12.3 Create `grafana/dashboards/` with pre-built dashboard JSON pre-wired to VictoriaTraces, Langfuse, and VictoriaMetrics datasources
  - [x] 12.4 Create `grafana/provisioning/` datasource and dashboard provisioning configs so Grafana auto-loads on startup

- [x] 13. CloudFormation foundation templates
  - [x] 13.1 Create `cloudformation/stacks/foundation/data.yaml`: all 7 DynamoDB tables with on-demand billing, PITR, KMS encryption, TTL on `execution-logs` and `guardrail-violations`, DynamoDB Streams on `eval-run-results`, all GSIs; every resource tagged `Environment`, `Application`, `ManagedBy: CloudFormation`; `DeletionPolicy: Retain` on all tables
  - [x] 13.2 Create `cloudformation/stacks/foundation/storage.yaml`: all 3 S3 buckets with KMS encryption, public access blocked, VPC-only bucket policy, S3 Versioning on `golden-dataset`, Glue Data Catalog table over `eval-results` (partitioned by year/month/taskCategory), Athena workgroup; `DeletionPolicy: Retain` on all buckets
  - [x] 13.3 Create `cloudformation/parameters/local.json` and `cloudformation/parameters/production.json` with all required parameter values; `production.json` must include `VpcId` and `SubnetIds` placeholders — never hardcoded
  - [x] 13.4 Create root `Makefile` targets (or `cloudformation/Makefile`): `deploy-foundation`, `deploy-platform`, `deploy-agents`, `deploy-agent`, `preview`, `drift-detect`, `destroy` — each wrapping the appropriate `aws cloudformation` commands with change-set creation for production
  - [x] 13.5 Run `cfn-lint` on `data.yaml` and `storage.yaml`; fix all errors until both templates pass with zero errors

- [x] 14. Tests
  - [x] 14.1 Write unit tests for `classify_request`, `retrieve_knowledge`, `detect_missing_inputs`, `generate_plan`, and `present_plan` nodes (tasks 6.1–6.5) — pure function tests with mocked LLM responses and minimal state fixtures; verify properties 1–11 from design
  - [x] 14.2 Write unit tests for all graph routing functions in `src/orchestrator/graph.py`: `_route_classify_request`, `_route_detect_missing_inputs`, `_route_present_plan`, `_route_validate_step_pre`, `_route_validate_step_post` — assert correct node names returned for every branch condition
  - [x] 14.3 Write property-based tests using `hypothesis` for all 23 correctness properties defined in `design.md`. Implement `hypothesis` strategies for: requests (arbitrary strings + valid JSON objects), plans (ordered steps with random confidence scores in [0.0, 1.0]), entities (service names from realistic pool, time ranges, environment names), tool inputs (valid and invalid per schema), context windows (LangChain `Document` objects). Tag each test: `# Feature: feature-01-core-orchestrator, Property N: <property_text>`
  - [x] 14.4 Write integration tests for full graph runs using `MemorySaver` and mock LLM responses: (a) happy path — request → classify → plan → execute → aggregate → log, (b) low-confidence path — classify routes to `prompt_user`, (c) missing-inputs path — `detect_missing_inputs` blocks execution, (d) hop-limit path — graph halts at 10 hops, (e) retry path — `validate_step_post` retries up to 2× then escalates
  - [x] 14.5 Write integration tests for the FastAPI app: (a) `GET /ping` returns `{"status": "Healthy"}`, (b) `POST /invocations` with `MOCK_STORAGE=true` and `MOCK_PROMPTS=true` produces a non-empty `final_response` and at least one `execution-logs` entry, (c) `GET /metrics` returns Prometheus text with `orchestrator_requests_total` present
