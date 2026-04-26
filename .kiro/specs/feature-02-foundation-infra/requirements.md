# Requirements Document

## Introduction

F02 deploys the AWS Cloud Engineering Agent to AWS for the first time. It provisions the complete CloudFormation foundation tier (`networking`, `identity`, `data`, `storage`) and platform tier (`guardrails`, `memory`, `gateway`), deploys the Orchestrator as an ARM64 container on AgentCore Runtime, activates Bedrock Guardrails on all LLM calls, wires AgentCore Memory to the Orchestrator, and configures AgentCore Identity with Secrets Manager. F01 already created `data.yaml` and `storage.yaml`; F02 creates all remaining templates and the container build.

Implements: Req 20, 21, 22, 24, 25, 27, 28 from vision.md.

---

## Glossary

- **Networking_Stack**: The CloudFormation stack (`networking.yaml`) that provisions the agent Security Group and exports VPC/subnet/endpoint references for consumption by downstream stacks. VPC Interface Endpoints and Gateway Endpoints are provisioned manually outside of CloudFormation and their IDs are passed in as parameters.
- **Identity_Stack**: The CloudFormation stack (`identity.yaml`) that provisions one scoped IAM execution role per agent and Secrets Manager secrets for external API credentials. In F02, only the Orchestrator role is provisioned. Each future agent stack provisions its own role — roles are never shared across agents.
- **Agent_Execution_Role**: A dedicated IAM role provisioned per agent, with a trust policy for `bedrock-agentcore.amazonaws.com` and an inline policy scoped to only the AWS actions that specific agent requires. The Orchestrator role, sub-agent roles, and any future agent roles are all distinct resources with non-overlapping permission sets.
- **Guardrails_Stack**: The CloudFormation stack (`guardrails.yaml`) that provisions the Bedrock Guardrails policy covering PII detection/masking, prompt injection detection, content safety filtering, and grounding checks.
- **Memory_Stack**: The CloudFormation stack (`memory.yaml`) that provisions the AgentCore Memory short-term and long-term stores.
- **Gateway_Stack**: The CloudFormation stack (`gateway.yaml`) that provisions the AgentCore Gateway endpoint with placeholder MCP tool registrations.
- **Orchestrator_Stack**: The CloudFormation stack (`orchestrator.yaml`) that provisions the AgentCore Runtime endpoint for the Orchestrator container.
- **Agent_Runtime_Module**: The reusable CloudFormation module (`agent-runtime-endpoint/module.yaml`) that encapsulates the AgentCore Runtime endpoint and Gateway registration pattern shared by all agent stacks. It does NOT create an IAM role — each calling stack provisions its own dedicated role and passes the ARN in.
- **Guardrails_Wrapper**: The Python module (`src/guardrails/bedrock.py`) that wraps `ChatBedrock` with `guardrailConfig` when `BEDROCK_GUARDRAIL_ID` is set, and passes through when unset.
- **VPC_Endpoint**: An AWS PrivateLink or Gateway endpoint that routes traffic to an AWS service without traversing the public internet.
- **PII**: Personally Identifiable Information — names, email addresses, phone numbers, API keys, and similar sensitive data detected and masked by Bedrock Guardrails.
- **Violation_Log_Entry**: A record written to the `guardrail-violations` DynamoDB table capturing violation type, severity, redacted content, request ID, policy version, UTC timestamp, and 90-day TTL.
- **AgentCore_Memory_Saver**: The `AgentCoreMemorySaver` class from `langgraph-checkpoint-aws` used as the LangGraph checkpointer for short-term (multi-turn) session memory in production.
- **AgentCore_Memory_Store**: The `AgentCoreMemoryStore` class from `langgraph-checkpoint-aws` used for long-term cross-session semantic memory retrieval in production.
- **Deploy_Script**: The shell script (`cloudformation/scripts/deploy.sh`) that deploys all stacks in the correct dependency order: networking → identity → data → storage → guardrails → memory → gateway → orchestrator.
- **Update_Agent_Script**: The shell script (`cloudformation/scripts/update-agent.sh`) that deploys a single agent stack as a fast-path update.

---

## Requirements

### Requirement 1: Networking Stack — Security Group and VPC Reference Exports

**User Story:** As a platform operator, I want the networking stack to provision the agent Security Group and export all VPC/subnet references, so that downstream stacks can consume them without hardcoding values. VPC Interface Endpoints and Gateway Endpoints are provisioned manually and are not managed by CloudFormation.

#### Acceptance Criteria

1. THE Networking_Stack SHALL accept `VpcId`, `SubnetIds`, and `VpcCidr` as required parameters and SHALL NOT create or modify the VPC, subnets, or any VPC/Gateway endpoints.
2. THE Networking_Stack SHALL provision a Security Group that allows HTTPS (port 443) egress to the VPC CIDR and denies all inbound traffic by default.
3. THE Networking_Stack SHALL export `VpcId`, `SubnetIds`, and the agent `SecurityGroupId` via `Outputs` using the naming convention `${AWS::StackName}-<ResourceName>`.
4. THE Networking_Stack SHALL publish `VpcId`, `SubnetIds`, and `SecurityGroupId` to SSM Parameter Store under `/${Application}/${Environment}/networking/<resource>`.
5. WHEN the Networking_Stack is deployed, THE Networking_Stack SHALL tag every resource with `Environment`, `Application`, `ManagedBy: CloudFormation`, and `Stack: !Ref AWS::StackName`.
6. VPC Interface Endpoints (bedrock-runtime, bedrock-agent-runtime, secretsmanager, xray, logs) and Gateway Endpoints (dynamodb, s3) SHALL be provisioned manually by the platform operator before deploying the networking stack — they are out of scope for CloudFormation management.

---

### Requirement 2: Per-Agent IAM Execution Roles and Secrets Manager

**User Story:** As a platform operator, I want each AgentCore Runtime to have its own dedicated IAM execution role with the minimum permissions it needs, so that a compromised agent cannot access resources it has no business reason to touch.

#### Acceptance Criteria

1. THE Identity_Stack SHALL provision one dedicated IAM execution role for the Orchestrator (`OrchestratorExecutionRole`) with an inline policy scoped exclusively to the actions the Orchestrator requires: `bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:Query`, `dynamodb:UpdateItem`, `s3:GetObject`, `s3:PutObject`, `s3:ListBucket`, `secretsmanager:GetSecretValue`, `xray:PutTraceSegments`, `xray:PutTelemetryRecords`, `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`.
2. THE Identity_Stack SHALL NOT provision roles for sub-agents — each sub-agent stack (F04+) SHALL provision its own dedicated role with permissions scoped only to the tools that sub-agent invokes.
3. EACH agent role SHALL have a trust policy that allows only `bedrock-agentcore.amazonaws.com` to assume it — no cross-agent role assumption is permitted.
4. NO two agents SHALL share an IAM execution role — the `OrchestratorExecutionRole` SHALL NOT be referenced by any sub-agent stack.
5. THE `agent-runtime-endpoint` CloudFormation module SHALL accept `ExecutionRoleArn` as a required parameter so each agent stack passes its own pre-provisioned role — the module SHALL NOT create a shared role internally.
6. THE Identity_Stack SHALL provision Secrets Manager secrets for external API credentials; each secret SHALL be encrypted with a dedicated KMS key provisioned in the same stack.
7. THE Identity_Stack SHALL export `OrchestratorExecutionRoleArn` and all `SecretsManagerArns` via `Outputs` using the naming convention `${AWS::StackName}-<ResourceName>`.
8. THE Identity_Stack SHALL publish all exported ARNs to SSM Parameter Store under `/${Application}/${Environment}/identity/<resource>`.
9. WHEN the Identity_Stack is deployed, THE Identity_Stack SHALL tag every resource with `Environment`, `Application`, `ManagedBy: CloudFormation`, and `Stack: !Ref AWS::StackName`.
10. THE Identity_Stack SHALL apply `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` to all KMS keys and Secrets Manager secrets.

---

### Requirement 3: Bedrock Guardrails Policy

**User Story:** As a platform operator, I want Bedrock Guardrails applied to all LLM inputs and outputs, so that PII is detected and masked, prompt injection is blocked, content safety is enforced, and hallucinated output is suppressed.

#### Acceptance Criteria

1. THE Guardrails_Stack SHALL provision a Bedrock Guardrails policy that enables PII detection and masking for the following entity types: `NAME`, `EMAIL`, `PHONE`, `ADDRESS`, `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `PASSWORD`, `USERNAME`.
2. THE Guardrails_Stack SHALL configure the Bedrock Guardrails policy to block and log prompt injection attempts with HIGH severity.
3. THE Guardrails_Stack SHALL configure the Bedrock Guardrails policy to enable content safety filtering for hate speech, violence, sexual content, and insults.
4. THE Guardrails_Stack SHALL configure the Bedrock Guardrails policy to enable grounding checks that suppress hallucinated output and request regeneration.
5. THE Guardrails_Stack SHALL export `GuardrailId` and `GuardrailArn` via `Outputs` using the naming convention `${AWS::StackName}-<ResourceName>`.
6. THE Guardrails_Stack SHALL publish `GuardrailId` and `GuardrailArn` to SSM Parameter Store under `/${Application}/${Environment}/guardrails/<resource>`.
7. WHEN the Guardrails_Stack is deployed, THE Guardrails_Stack SHALL tag every resource with `Environment`, `Application`, `ManagedBy: CloudFormation`, and `Stack: !Ref AWS::StackName`.

---

### Requirement 4: Guardrails Wrapper and Violation Logging

**User Story:** As a platform operator, I want all LLM calls to pass through the Bedrock Guardrails wrapper, so that violations are detected, blocked, and logged to the `guardrail-violations` DynamoDB table.

#### Acceptance Criteria

1. THE Guardrails_Wrapper SHALL read the `BEDROCK_GUARDRAIL_ID` environment variable and, WHEN the variable is set, SHALL apply `guardrailConfig` to every `ChatBedrock` invocation with `guardrailIdentifier`, `guardrailVersion`, and `trace: enabled`.
2. WHEN `BEDROCK_GUARDRAIL_ID` is not set, THE Guardrails_Wrapper SHALL pass through all LLM calls without modification.
3. WHEN a guardrail violation is detected, THE Guardrails_Wrapper SHALL write a Violation_Log_Entry to the `guardrail-violations` DynamoDB table via `src/storage/dynamodb.py` helpers containing: `violationId` (UUID), `violationType` (PII | INJECTION | CONTENT | GROUNDING), `severity` (HIGH | MEDIUM | LOW), `redactedContent` (masked text), `requestId`, `policyVersion`, `timestamp` (UTC ISO-8601), and `ttl` (90 days from now as Unix epoch).
4. WHEN a guardrail blocks a response, THE scan_output_guardrails node SHALL return the blocked response indicator to the caller rather than the raw LLM output.
5. THE Guardrails_Wrapper SHALL NOT instantiate boto3 clients directly; all DynamoDB writes SHALL use `src/storage/dynamodb.py` helpers.

---

### Requirement 5: PII Redaction Completeness

**User Story:** As a platform operator, I want PII to be reliably detected and masked in all LLM outputs, so that sensitive data is never surfaced to end users.

#### Acceptance Criteria

1. WHEN an LLM output contains a PII entity of any configured type, THE Guardrails_Wrapper SHALL replace the PII entity with a typed placeholder (e.g., `{NAME}`, `{EMAIL}`, `{API_KEY}`) before returning the response.
2. WHEN an LLM output contains multiple PII entities of different types, THE Guardrails_Wrapper SHALL mask all detected entities in a single pass.
3. WHEN an LLM output contains no PII entities, THE Guardrails_Wrapper SHALL return the output unchanged.

---

### Requirement 6: Prompt Injection Blocking

**User Story:** As a platform operator, I want prompt injection attempts to be detected and blocked before they reach the LLM, so that adversarial inputs cannot hijack agent behavior.

#### Acceptance Criteria

1. WHEN an input contains a prompt injection pattern (e.g., "ignore previous instructions", "you are now", jailbreak sequences), THE Guardrails_Wrapper SHALL block the request and return a blocked response indicator.
2. WHEN a prompt injection attempt is blocked, THE Guardrails_Wrapper SHALL write a Violation_Log_Entry with `violationType: INJECTION` and `severity: HIGH` to the `guardrail-violations` table.
3. WHEN an input does not contain a prompt injection pattern, THE Guardrails_Wrapper SHALL pass the input to the LLM without modification.

---

### Requirement 7: AgentCore Memory Stores

**User Story:** As a platform operator, I want AgentCore Memory wired to the Orchestrator, so that multi-turn session context is preserved and cross-session knowledge is available for retrieval.

#### Acceptance Criteria

1. THE Memory_Stack SHALL provision an AgentCore Memory store for short-term (session) memory and export its store ID as `ShortTermMemoryStoreId`.
2. THE Memory_Stack SHALL provision an AgentCore Memory store for long-term (cross-session) memory and export its store ID as `LongTermMemoryStoreId`.
3. THE Memory_Stack SHALL publish both store IDs to SSM Parameter Store under `/${Application}/${Environment}/memory/<resource>`.
4. WHEN `AGENTCORE_MEMORY_STORE_ID` is set, THE `get_checkpointer()` function in `src/orchestrator/memory.py` SHALL return an `AgentCoreMemorySaver` instance initialized with the store ID.
5. WHEN `AGENTCORE_MEMORY_STORE_ID` is not set, THE `get_checkpointer()` function SHALL return a `MemorySaver` instance.
6. WHEN the Memory_Stack is deployed, THE Memory_Stack SHALL tag every resource with `Environment`, `Application`, `ManagedBy: CloudFormation`, and `Stack: !Ref AWS::StackName`.

---

### Requirement 8: AgentCore Gateway

**User Story:** As a platform operator, I want an AgentCore Gateway provisioned, so that sub-agents can register MCP tool endpoints and the Orchestrator can discover tools at runtime.

#### Acceptance Criteria

1. THE Gateway_Stack SHALL provision an AgentCore Gateway endpoint.
2. THE Gateway_Stack SHALL export `GatewayEndpointUrl` via `Outputs` using the naming convention `${AWS::StackName}-GatewayEndpointUrl`.
3. THE Gateway_Stack SHALL publish `GatewayEndpointUrl` to SSM Parameter Store under `/${Application}/${Environment}/gateway/endpoint-url`.
4. WHEN the Gateway_Stack is deployed, THE Gateway_Stack SHALL tag every resource with `Environment`, `Application`, `ManagedBy: CloudFormation`, and `Stack: !Ref AWS::StackName`.

---

### Requirement 9: Orchestrator AgentCore Runtime Deployment

**User Story:** As a platform operator, I want the Orchestrator deployed as an ARM64 container on AgentCore Runtime, so that it is reachable within the VPC and can serve requests.

#### Acceptance Criteria

1. THE Orchestrator_Stack SHALL provision an AgentCore Runtime endpoint for the Orchestrator container image built for ARM64.
2. THE Orchestrator_Stack SHALL reference the Orchestrator IAM execution role via `Fn::ImportValue` from the Identity_Stack — never hardcode the role ARN.
3. THE Orchestrator_Stack SHALL reference networking outputs (VpcId, SubnetIds, SecurityGroupId) via `Fn::ImportValue` from the Networking_Stack.
4. THE Orchestrator_Stack SHALL reference guardrail, memory, and gateway outputs via `Fn::ImportValue` from their respective stacks.
5. THE Orchestrator_Stack SHALL set the `BEDROCK_GUARDRAIL_ID`, `AGENTCORE_MEMORY_STORE_ID`, `AGENTCORE_LONG_TERM_MEMORY_STORE_ID`, and `AGENTCORE_GATEWAY_URL` environment variables on the Runtime endpoint from imported stack outputs.
6. THE Orchestrator_Stack SHALL set `DISABLE_ADOT_OBSERVABILITY` to prevent the AgentCore Runtime's built-in ADOT from conflicting with the agent's own OTEL instrumentation.
7. THE Orchestrator_Stack SHALL export `RuntimeEndpointArn` via `Outputs` using the naming convention `${AWS::StackName}-RuntimeEndpointArn`.
8. WHEN the Orchestrator endpoint is deployed, THE endpoint SHALL respond to `GET /ping` with `{"status": "Healthy"}` within the VPC.

---

### Requirement 10: Reusable Agent Runtime CloudFormation Module

**User Story:** As a platform engineer, I want a reusable CloudFormation module for the AgentCore Runtime pattern, so that every future agent stack can be provisioned consistently without duplicating template logic — and each agent always gets its own isolated role.

#### Acceptance Criteria

1. THE Agent_Runtime_Module SHALL encapsulate the following resources: AgentCore Runtime endpoint and AgentCore Gateway registration.
2. THE Agent_Runtime_Module SHALL accept `ExecutionRoleArn` as a required parameter — the calling agent stack is responsible for provisioning its own dedicated role and passing the ARN in. THE module SHALL NOT create or share an IAM role internally.
3. THE Agent_Runtime_Module SHALL accept the following parameters: `AgentName`, `ContainerImageUri`, `ExecutionRoleArn`, `VpcId`, `SubnetIds`, `SecurityGroupId`, `GatewayEndpointUrl`, `Environment`, `Application`.
4. THE Agent_Runtime_Module SHALL export `RuntimeEndpointArn` as a module output.
5. THE Agent_Runtime_Module SHALL tag all provisioned resources with `Environment`, `Application`, `ManagedBy: CloudFormation`, and `Stack: !Ref AWS::StackName`.

---

### Requirement 11: ARM64 Container Build

**User Story:** As a platform engineer, I want the Orchestrator packaged as an ARM64 multi-stage Docker image, so that it can be deployed to AgentCore Runtime.

#### Acceptance Criteria

1. THE Dockerfile SHALL use a multi-stage build targeting the `linux/arm64` platform.
2. THE Dockerfile SHALL install all dependencies from `pyproject.toml` in the build stage and copy only the runtime artifacts to the final stage.
3. THE Dockerfile SHALL expose port 8080 and set the default `CMD` to run `uvicorn src.orchestrator.main:app --host 0.0.0.0 --port 8080`.
4. WHEN the container starts, THE container SHALL respond to `GET /ping` with `{"status": "Healthy"}` within 30 seconds.

---

### Requirement 12: Deployment Scripts and Makefile Targets

**User Story:** As a platform engineer, I want deployment scripts that deploy stacks in the correct dependency order, so that a single command brings up the full foundation and platform tiers.

#### Acceptance Criteria

1. THE Deploy_Script SHALL deploy stacks in the following order: networking → identity → data → storage → guardrails → memory → gateway → orchestrator.
2. THE Deploy_Script SHALL accept an `ENV` argument and use the corresponding parameter file from `cloudformation/parameters/${ENV}.json`.
3. THE Update_Agent_Script SHALL accept an `AGENT` argument and deploy only the specified agent stack.
4. THE `cloudformation/Makefile` SHALL include `deploy-platform` and `deploy-agents` targets that invoke the Deploy_Script for the platform and application/agents tiers respectively.
5. WHEN `ENV=production`, THE Deploy_Script SHALL create a CloudFormation change set and display the diff before executing — it SHALL NOT deploy directly without a change set.
6. THE Deploy_Script SHALL run `cfn-lint` on all templates in the target tier before any deployment begins and SHALL abort if any errors are found.

---

### Requirement 13: CloudFormation Template Validation

**User Story:** As a platform engineer, I want all new CloudFormation templates validated with cfn-lint before deployment, so that template errors are caught before they cause deployment failures.

#### Acceptance Criteria

1. THE following templates SHALL pass `cfn-lint` with zero errors: `networking.yaml`, `identity.yaml`, `guardrails.yaml`, `memory.yaml`, `gateway.yaml`, `orchestrator.yaml`, `agent-runtime-endpoint/module.yaml`.
2. WHEN cfn-lint reports a warning on any template, THE warning SHALL be documented with a justification comment in the template.
3. THE `cloudformation/parameters/production.json` file SHALL include parameter entries for all new parameters introduced by F02 templates: `VpcId`, `SubnetIds`, `BedrockModelId`, `OrchestratorImageUri`.
