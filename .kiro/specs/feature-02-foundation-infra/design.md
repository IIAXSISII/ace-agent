# Design Document: F02 — Foundation Infrastructure

## Overview

F02 deploys the AWS Cloud Engineering Agent to AWS for the first time. It builds on F01's locally-runnable Orchestrator by adding the CloudFormation infrastructure that hosts it in production: a Security Group for private AWS service access (VPC endpoints are provisioned manually), IAM execution roles, Bedrock Guardrails, AgentCore Memory, AgentCore Gateway, and the Orchestrator's AgentCore Runtime endpoint. The Python guardrails wrapper (`src/guardrails/bedrock.py`) is also fully implemented, wiring `ChatBedrock` with `guardrailConfig` and writing violation log entries to DynamoDB.

References: `architecture.md` §Networking, §Guardrails, §AgentCore Memory, §AgentCore Runtime, §CloudFormation Conventions.

---

## Architecture

### Stack Dependency Graph

```
networking ──┐
identity   ──┤
data       ──┤──► guardrails ──┐
storage    ──┘                  ├──► orchestrator
                memory    ──────┤
                gateway   ──────┘
```

Deployment order enforced by `cloudformation/scripts/deploy.sh`:
1. `networking` — Security Group (VPC endpoints provisioned manually before this step)
2. `identity` — IAM roles, Secrets Manager, KMS
3. `data` — DynamoDB tables (already deployed in F01)
4. `storage` — S3 buckets (already deployed in F01)
5. `guardrails` — Bedrock Guardrails policy
6. `memory` — AgentCore Memory stores
7. `gateway` — AgentCore Gateway
8. `orchestrator` — AgentCore Runtime endpoint

### Cross-Stack Reference Pattern

All cross-stack values flow via `Fn::ImportValue`. The export naming convention is `${AWS::StackName}-<ResourceName>` on every `Outputs` entry. Key outputs are also published to SSM Parameter Store so application code can read them without `Fn::ImportValue` coupling.

```yaml
# Consumer pattern (orchestrator.yaml)
VpcId:
  Fn::ImportValue: !Sub "ace-agent-foundation-networking-${Environment}-VpcId"
```

---

## CloudFormation Templates

### 1. `cloudformation/stacks/foundation/networking.yaml`

Provisions only the agent Security Group. VPC endpoints are provisioned manually by the platform operator — they are not managed by this stack.

**Resources:**
- `AgentSecurityGroup` — Security Group: HTTPS (port 443) egress to VPC CIDR, no inbound

**Parameters:** `Environment`, `Application`, `VpcId`, `SubnetIds` (CommaDelimitedList), `VpcCidr`

**Outputs (all exported + SSM):**
- `VpcId` → `/${Application}/${Environment}/networking/vpc-id`
- `SubnetIds` → `/${Application}/${Environment}/networking/subnet-ids`
- `AgentSecurityGroupId` → `/${Application}/${Environment}/networking/agent-security-group-id`

**Design notes:**
- VPC Interface Endpoints (bedrock-runtime, bedrock-agent-runtime, secretsmanager, xray, logs) and Gateway Endpoints (dynamodb, s3) must be created manually in the AWS console or via CLI before deploying this stack. They are intentionally excluded from CloudFormation to avoid idempotency issues with pre-existing endpoints.
- The Security Group egress rule targets the VPC CIDR so traffic to all VPC endpoints stays within the VPC without needing to enumerate individual endpoint IDs.
- `DeletionPolicy: Retain` is not required on Security Groups (they are not stateful), but the Security Group should not be deleted while agent containers are running.

---

### 2. `cloudformation/stacks/foundation/identity.yaml`

Provisions the Orchestrator's dedicated IAM execution role and Secrets Manager secrets. This stack owns **only the Orchestrator role** — every sub-agent stack (F04+) provisions its own role with its own scoped permissions. Roles are never shared.

**Per-agent role pattern:**
- Each agent stack provisions its own `AWS::IAM::Role` with a trust policy for `bedrock-agentcore.amazonaws.com`
- Each role's inline policy is scoped to only the actions that specific agent needs
- The `agent-runtime-endpoint` module accepts `ExecutionRoleArn` as a required input — it never creates a role internally
- This means adding a new sub-agent = new role in that agent's stack, not a change to `identity.yaml`

**Orchestrator permissions (what it needs, nothing more):**
| Action group | Reason |
|---|---|
| `bedrock:InvokeModel`, `bedrock:ApplyGuardrail` | LLM calls + guardrail checks |
| `dynamodb:GetItem/PutItem/Query/UpdateItem` | All 7 tables (execution-logs, session-state, registries, etc.) |
| `s3:GetObject/PutObject/ListBucket` | golden-dataset, eval-results, artifacts buckets |
| `secretsmanager:GetSecretValue` | External API credentials |
| `xray:PutTraceSegments/PutTelemetryRecords` | ADOT trace export |
| `logs:CreateLogGroup/CreateLogStream/PutLogEvents` | Container log output |

Sub-agent roles (F04+) will have narrower sets — e.g. a VictoriaMetrics agent needs no DynamoDB write access beyond its own registry entry.

**Resources:**
- `OrchestratorKmsKey` — KMS key for Secrets Manager encryption (rotation enabled)
- `OrchestratorKmsKeyAlias`
- `OrchestratorExecutionRole` — IAM Role with trust policy for `bedrock-agentcore.amazonaws.com`; inline policy scoped to the Orchestrator's required actions on specific resource ARNs (never wildcards on resource)
- `ExternalApiCredentialsSecret` — Secrets Manager secret encrypted with `OrchestratorKmsKey` (placeholder for F04+ integrations)

**Parameters:** `Environment`, `Application`

**Outputs (all exported + SSM):**
- `OrchestratorExecutionRoleArn` → `/${Application}/${Environment}/identity/orchestrator-execution-role-arn`
- `ExternalApiCredentialsSecretArn` → `/${Application}/${Environment}/identity/external-api-credentials-secret-arn`

**Design notes:**
- Resource ARNs in the inline policy use `Fn::Sub` with `${AWS::AccountId}` and `${AWS::Region}` — never `*` on resource.
- `DeletionPolicy: Retain` on KMS key and secret.

---

### 3. `cloudformation/stacks/platform/guardrails.yaml`

Provisions the Bedrock Guardrails policy. This is the single guardrail used by all agents in the environment.

**Resources:**
- `OrchestratorGuardrail` — `AWS::Bedrock::Guardrail` with:
  - `SensitiveInformationPolicyConfig`: PII entities (NAME, EMAIL, PHONE, ADDRESS, AWS_ACCESS_KEY, AWS_SECRET_KEY, PASSWORD, USERNAME) with action `ANONYMIZE`
  - `ContentPolicyConfig`: hate, violence, sexual, insults — all at `HIGH` filter strength for both input and output
  - `ContextualGroundingPolicyConfig`: grounding threshold 0.75, relevance threshold 0.75
  - `WordPolicyConfig`: prompt injection patterns blocked

**Parameters:** `Environment`, `Application`

**Outputs (all exported + SSM):**
- `GuardrailId` → `/${Application}/${Environment}/guardrails/guardrail-id`
- `GuardrailArn` → `/${Application}/${Environment}/guardrails/guardrail-arn`
- `GuardrailVersion` → `/${Application}/${Environment}/guardrails/guardrail-version`

**Design notes:**
- Bedrock Guardrails uses `AWS::Bedrock::Guardrail` (CloudFormation resource type). The `GuardrailVersion` output is `DRAFT` until a version is explicitly published — the Orchestrator uses `DRAFT` in development and a pinned version in production.
- The `GuardrailId` is passed to the Orchestrator container as `BEDROCK_GUARDRAIL_ID` env var.

---

### 4. `cloudformation/stacks/platform/memory.yaml`

Provisions AgentCore Memory stores for short-term and long-term memory.

**Resources:**
- `ShortTermMemoryStore` — `AWS::BedrockAgentCore::MemoryStore` for session-scoped multi-turn checkpointing
- `LongTermMemoryStore` — `AWS::BedrockAgentCore::MemoryStore` for cross-session semantic retrieval

**Parameters:** `Environment`, `Application`

**Outputs (all exported + SSM):**
- `ShortTermMemoryStoreId` → `/${Application}/${Environment}/memory/short-term-store-id`
- `LongTermMemoryStoreId` → `/${Application}/${Environment}/memory/long-term-store-id`

**Design notes:**
- `AGENTCORE_MEMORY_STORE_ID` env var on the Orchestrator Runtime is set to `ShortTermMemoryStoreId`. The `get_checkpointer()` function in `memory.py` reads this var to switch between `AgentCoreMemorySaver` (production) and `MemorySaver` (local).
- Long-term store ID is passed as `AGENTCORE_LONG_TERM_MEMORY_STORE_ID` for future use by the `retrieve_knowledge` node.

---

### 5. `cloudformation/stacks/platform/gateway.yaml`

Provisions the AgentCore Gateway. MCP tool registrations are placeholders in F02 — populated by F04+ when real sub-agents are deployed.

**Resources:**
- `AgentCoreGateway` — `AWS::BedrockAgentCore::Gateway` with OAuth2 authentication configuration

**Parameters:** `Environment`, `Application`

**Outputs (all exported + SSM):**
- `GatewayEndpointUrl` → `/${Application}/${Environment}/gateway/endpoint-url`
- `GatewayId` → `/${Application}/${Environment}/gateway/gateway-id`

---

### 6. `cloudformation/stacks/application/agents/orchestrator.yaml`

Provisions the Orchestrator AgentCore Runtime endpoint. Consumes all upstream stack outputs via `Fn::ImportValue`. Also provisions the Orchestrator's own execution role — imported from `identity.yaml` via `Fn::ImportValue` (the role is defined there because it depends on the data/storage stack ARNs).

**Resources:**
- `OrchestratorRuntimeEndpoint` — `AWS::BedrockAgentCore::AgentRuntimeEndpoint` with:
  - `ContainerConfiguration.ImageUri`: `!Ref OrchestratorImageUri` parameter
  - `NetworkConfiguration`: VpcId, SubnetIds, SecurityGroupId from networking stack
  - `ExecutionRoleArn`: imported from identity stack — this is the Orchestrator's dedicated role, not shared with any sub-agent
  - `Environment` variables: `BEDROCK_GUARDRAIL_ID`, `AGENTCORE_MEMORY_STORE_ID`, `AGENTCORE_LONG_TERM_MEMORY_STORE_ID`, `AGENTCORE_GATEWAY_URL`, `BEDROCK_MODEL_ID`, `DISABLE_ADOT_OBSERVABILITY=true`, `OTEL_STACK=production`

**Parameters:** `Environment`, `Application`, `OrchestratorImageUri`, `BedrockModelId`, `NetworkingStackName`, `IdentityStackName`, `GuardrailsStackName`, `MemoryStackName`, `GatewayStackName`

**Outputs (all exported + SSM):**
- `RuntimeEndpointArn` → `/${Application}/${Environment}/agents/orchestrator/runtime-endpoint-arn`
- `RuntimeEndpointUrl` → `/${Application}/${Environment}/agents/orchestrator/runtime-endpoint-url`

**Design notes:**
- The Orchestrator role is provisioned in `identity.yaml` (not inline here) because it needs to reference DynamoDB table ARNs and S3 bucket ARNs from the data/storage stacks. Future sub-agent stacks provision their own roles inline within their own stack file.

---

### 7. `cloudformation/modules/agent-runtime-endpoint/module.yaml`

Reusable CloudFormation module encapsulating the AgentCore Runtime endpoint + Gateway registration pattern. Used by `orchestrator.yaml` and all future agent stacks.

**The module does NOT create an IAM role.** Each calling stack provisions its own dedicated role and passes the ARN in. This enforces the per-agent isolation contract at the module boundary — it is impossible to accidentally share a role by using this module.

**Module Parameters:** `AgentName`, `ContainerImageUri`, `ExecutionRoleArn` (required — caller must provision), `VpcId`, `SubnetIds`, `SecurityGroupId`, `GatewayEndpointUrl`, `Environment`, `Application`, `EnvironmentVariables` (JSON string)

**Module Outputs:** `RuntimeEndpointArn`, `RuntimeEndpointUrl`

**Usage pattern for every agent stack:**
```yaml
# Each agent stack (orchestrator.yaml, victoriametrics-agent.yaml, etc.) follows this pattern:
Resources:
  # 1. Agent's own dedicated role — scoped to THIS agent's required actions only
  AgentExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Statement:
          - Effect: Allow
            Principal: {Service: bedrock-agentcore.amazonaws.com}
            Action: sts:AssumeRole
      Policies:
        - PolicyName: AgentPolicy
          PolicyDocument:
            Statement:
              # Only the actions THIS agent needs — nothing more

  # 2. Runtime endpoint — receives the role ARN, never creates one
  AgentRuntime:
    Type: AWS::CloudFormation::Stack  # or module reference
    Properties:
      Parameters:
        ExecutionRoleArn: !GetAtt AgentExecutionRole.Arn
        # ... other params
```

---

## Python Implementation

### `src/guardrails/bedrock.py` — Guardrails Wrapper

The guardrails wrapper provides a `get_guardrailed_llm()` factory and a `log_violation()` helper. It is the single place where `guardrailConfig` is applied to `ChatBedrock`.

```python
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from langchain_aws import ChatBedrock
from src.storage.dynamodb import put_item


def get_guardrailed_llm(model_id: Optional[str] = None) -> ChatBedrock:
    """
    Returns a ChatBedrock instance.
    When BEDROCK_GUARDRAIL_ID is set, guardrailConfig is applied.
    When unset, returns a plain ChatBedrock (passthrough).
    """
    guardrail_id = os.getenv("BEDROCK_GUARDRAIL_ID", "")
    model = model_id or os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")

    kwargs = {"model_id": model}
    if guardrail_id:
        kwargs["guardrails"] = {
            "guardrailIdentifier": guardrail_id,
            "guardrailVersion": os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT"),
            "trace": "enabled",
        }
    return ChatBedrock(**kwargs)


def log_violation(
    violation_type: str,
    severity: str,
    redacted_content: str,
    request_id: str,
    policy_version: str = "DRAFT",
) -> None:
    """
    Writes a Violation_Log_Entry to the guardrail-violations DynamoDB table.
    violation_type: PII | INJECTION | CONTENT | GROUNDING
    severity: HIGH | MEDIUM | LOW
    """
    now = datetime.now(timezone.utc)
    ttl = int(now.timestamp()) + (90 * 24 * 60 * 60)  # 90 days

    put_item(
        table="guardrail-violations",
        item={
            "violationId": str(uuid.uuid4()),
            "violationType": violation_type,
            "severity": severity,
            "redactedContent": redacted_content,
            "requestId": request_id,
            "policyVersion": policy_version,
            "timestamp": now.isoformat(),
            "ttl": ttl,
        },
    )
```

**Key design decisions:**
- `get_guardrailed_llm()` is the single factory — all nodes that need an LLM call import this instead of instantiating `ChatBedrock` directly.
- `log_violation()` uses `src/storage/dynamodb.py` helpers — never boto3 directly.
- When `BEDROCK_GUARDRAIL_ID` is unset (local dev), the function returns a plain `ChatBedrock` with no guardrail config — zero code path difference for callers.

### `src/orchestrator/nodes/scan_output_guardrails.py` — Updated

The existing `scan_output_guardrails` node is updated to use `get_guardrailed_llm()` from `bedrock.py` and call `log_violation()` when a block is detected.

```python
from src.guardrails.bedrock import get_guardrailed_llm, log_violation

def scan_output_guardrails(state: "OrchestratorState") -> "OrchestratorState":
    guardrail_id = os.getenv("BEDROCK_GUARDRAIL_ID", "")
    if not guardrail_id:
        return state  # passthrough in local dev

    final_response = state.get("final_response", "") or ""
    if not final_response:
        return state

    llm = get_guardrailed_llm()
    try:
        response = llm.invoke([HumanMessage(content=final_response)])
        response_content = response.content if hasattr(response, "content") else str(response)
        if not response_content or response_content.strip() == "":
            log_violation(
                violation_type="CONTENT",
                severity="HIGH",
                redacted_content=final_response[:500],
                request_id=state.get("session_id", "unknown"),
            )
            return {**state, "final_response": _GUARDRAIL_BLOCKED_RESPONSE}
        return {**state, "final_response": response_content}
    except Exception as exc:
        error_str = str(exc).lower()
        if "guardrail" in error_str or "blocked" in error_str or "intervention" in error_str:
            log_violation(
                violation_type="INJECTION",
                severity="HIGH",
                redacted_content=final_response[:500],
                request_id=state.get("session_id", "unknown"),
            )
            return {**state, "final_response": _GUARDRAIL_BLOCKED_RESPONSE}
        raise
```

### `src/orchestrator/memory.py` — Verified Complete

The existing `get_checkpointer()` implementation is already correct for F02. No changes needed — it already switches on `AGENTCORE_MEMORY_STORE_ID`.

### `Dockerfile` — ARM64 Multi-Stage Build

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=linux/arm64 python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir build \
    && pip install --no-cache-dir .

FROM --platform=linux/arm64 python:3.12-slim AS runtime

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ ./src/

EXPOSE 8080
CMD ["uvicorn", "src.orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## Deployment Scripts

### `cloudformation/scripts/deploy.sh`

Deploys all stacks in dependency order. Accepts `ENV` as first argument.

```bash
#!/usr/bin/env bash
set -euo pipefail

ENV=${1:-local}
REGION=${AWS_DEFAULT_REGION:-us-east-1}
PROFILE=${AWS_PROFILE:-default}

cd "$(dirname "$0")/.."

make -f Makefile deploy-foundation ENV=$ENV REGION=$REGION PROFILE=$PROFILE
make -f Makefile deploy-platform   ENV=$ENV REGION=$REGION PROFILE=$PROFILE
make -f Makefile deploy-agents     ENV=$ENV REGION=$REGION PROFILE=$PROFILE
```

### `cloudformation/scripts/update-agent.sh`

Fast path for single agent stack update.

```bash
#!/usr/bin/env bash
set -euo pipefail

AGENT=${1:?Usage: update-agent.sh <agent-name> [env]}
ENV=${2:-local}

cd "$(dirname "$0")/.."
make -f Makefile deploy-agent AGENT=$AGENT ENV=$ENV
```

---

## Makefile Updates

The existing `cloudformation/Makefile` already has `deploy-platform` and `deploy-agents` targets. F02 updates `deploy-platform` to remove `knowledge.yaml` and `observability.yaml` (deferred to F03 and F05) and adds the `deploy-foundation` ordering to include `networking` and `identity` before `data` and `storage`.

Updated `deploy-foundation` target:
```makefile
.PHONY: deploy-foundation
deploy-foundation:
	$(call lint-templates,$(STACKS_DIR)/foundation/*.yaml)
	$(call deploy-stack,$(call stack-name,foundation,networking),$(STACKS_DIR)/foundation/networking.yaml)
	$(call deploy-stack,$(call stack-name,foundation,identity),$(STACKS_DIR)/foundation/identity.yaml)
	$(call deploy-stack,$(call stack-name,foundation,data),$(STACKS_DIR)/foundation/data.yaml)
	$(call deploy-stack,$(call stack-name,foundation,storage),$(STACKS_DIR)/foundation/storage.yaml)
```

Updated `deploy-platform` target (F02 scope — excludes knowledge and observability):
```makefile
.PHONY: deploy-platform
deploy-platform:
	$(call lint-templates,$(STACKS_DIR)/platform/guardrails.yaml $(STACKS_DIR)/platform/memory.yaml $(STACKS_DIR)/platform/gateway.yaml)
	$(call deploy-stack,$(call stack-name,platform,guardrails),$(STACKS_DIR)/platform/guardrails.yaml)
	$(call deploy-stack,$(call stack-name,platform,memory),$(STACKS_DIR)/platform/memory.yaml)
	$(call deploy-stack,$(call stack-name,platform,gateway),$(STACKS_DIR)/platform/gateway.yaml)
```

---

## Parameter File Updates

`cloudformation/parameters/production.json` gains the following new entries for F02:

```json
{ "ParameterKey": "VpcCidr",              "ParameterValue": "<REPLACE_WITH_VPC_CIDR>" },
{ "ParameterKey": "BedrockModelId",       "ParameterValue": "anthropic.claude-3-5-sonnet-20241022-v2:0" },
{ "ParameterKey": "OrchestratorImageUri", "ParameterValue": "<REPLACE_WITH_ECR_IMAGE_URI>" },
{ "ParameterKey": "NetworkingStackName",  "ParameterValue": "ace-agent-foundation-networking-production" },
{ "ParameterKey": "IdentityStackName",    "ParameterValue": "ace-agent-foundation-identity-production" },
{ "ParameterKey": "GuardrailsStackName",  "ParameterValue": "ace-agent-platform-guardrails-production" },
{ "ParameterKey": "MemoryStackName",      "ParameterValue": "ace-agent-platform-memory-production" },
{ "ParameterKey": "GatewayStackName",     "ParameterValue": "ace-agent-platform-gateway-production" }
```

---

## Correctness Properties

Based on the prework analysis, the following properties are testable for F02:

### Property 30: PII Redaction Completeness

For any LLM output string containing one or more PII entities of a configured type, the guardrails wrapper must replace every PII entity with a typed placeholder. No raw PII must appear in the returned string.

**Test approach:** Property-based test using `hypothesis`. Generate strings containing injected PII patterns (names, emails, API keys). Mock the `ChatBedrock` response to simulate Bedrock's guardrail masking behavior. Assert that the returned string contains `{NAME}`, `{EMAIL}`, or `{API_KEY}` placeholders and does not contain the original PII values.

```python
# tests/unit/test_pbt_guardrails.py
# Feature: feature-02-foundation-infra, Property 30: PII Redaction Completeness
@given(pii_text=pii_containing_text())
def test_pii_redaction_completeness(pii_text):
    """For any output containing PII, the wrapper must mask all PII entities."""
    with mock_guardrail_active():
        result = invoke_with_guardrails(pii_text)
    assert_no_raw_pii(result, pii_text)
```

### Property 31: Prompt Injection Blocking

For any input string matching a prompt injection pattern, the guardrails wrapper must block the request and return the blocked response indicator. The original LLM must not be invoked.

**Test approach:** Property-based test using `hypothesis`. Generate strings containing injection patterns (ignore previous instructions, jailbreak sequences). Mock `ChatBedrock` to raise a guardrail intervention exception. Assert that the returned state contains the blocked response indicator and that `log_violation` was called with `violationType=INJECTION`.

```python
# Feature: feature-02-foundation-infra, Property 31: Prompt Injection Blocking
@given(injection_text=injection_pattern_text())
def test_prompt_injection_blocking(injection_text):
    """For any injection pattern input, the wrapper must block and log."""
    with mock_guardrail_active(), mock_dynamodb():
        result_state = scan_output_guardrails({**base_state, "final_response": injection_text})
    assert result_state["final_response"] == _GUARDRAIL_BLOCKED_RESPONSE
    assert_violation_logged(violation_type="INJECTION")
```

### Property 32: Guardrail Violation Log Completeness

For every guardrail block event (PII mask or injection block), exactly one Violation_Log_Entry must be written to the `guardrail-violations` DynamoDB table. The entry must contain all required fields: `violationId`, `violationType`, `severity`, `redactedContent`, `requestId`, `policyVersion`, `timestamp`, `ttl`.

**Test approach:** Property-based test using `hypothesis`. Generate arbitrary block events with varying violation types and severities. Mock `put_item` to capture calls. Assert that exactly one `put_item` call was made per block event and that the captured item contains all required fields with correct types.

```python
# Feature: feature-02-foundation-infra, Property 32: Guardrail Violation Log Completeness
@given(violation=violation_event())
def test_violation_log_completeness(violation):
    """Every block event must produce exactly one complete log entry."""
    captured = []
    with mock_put_item(captured):
        log_violation(**violation)
    assert len(captured) == 1
    entry = captured[0]
    assert_all_required_fields_present(entry)
    assert entry["ttl"] > int(time.time())  # TTL is in the future
```

### Unit Tests (example-based)

- `test_guardrails_passthrough_when_env_unset`: When `BEDROCK_GUARDRAIL_ID` is not set, `get_guardrailed_llm()` returns a `ChatBedrock` with no `guardrails` kwarg.
- `test_guardrails_config_when_env_set`: When `BEDROCK_GUARDRAIL_ID=test-id`, `get_guardrailed_llm()` returns a `ChatBedrock` with `guardrails.guardrailIdentifier == "test-id"`.
- `test_memory_saver_local`: When `AGENTCORE_MEMORY_STORE_ID` is unset, `get_checkpointer()` returns a `MemorySaver` instance.
- `test_memory_saver_production`: When `AGENTCORE_MEMORY_STORE_ID=store-123`, `get_checkpointer()` returns an `AgentCoreMemorySaver` instance with `memory_store_id="store-123"`.
- `test_cfn_lint_networking`: `cfn-lint cloudformation/stacks/foundation/networking.yaml` exits 0.
- `test_cfn_lint_identity`: `cfn-lint cloudformation/stacks/foundation/identity.yaml` exits 0.
- `test_cfn_lint_guardrails`: `cfn-lint cloudformation/stacks/platform/guardrails.yaml` exits 0.
- `test_cfn_lint_memory`: `cfn-lint cloudformation/stacks/platform/memory.yaml` exits 0.
- `test_cfn_lint_gateway`: `cfn-lint cloudformation/stacks/platform/gateway.yaml` exits 0.
- `test_cfn_lint_orchestrator`: `cfn-lint cloudformation/stacks/application/agents/orchestrator.yaml` exits 0.
- `test_cfn_lint_module`: `cfn-lint cloudformation/modules/agent-runtime-endpoint/module.yaml` exits 0.
