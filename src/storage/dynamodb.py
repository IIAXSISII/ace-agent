"""
DynamoDB storage helpers for all 7 tables.

All DynamoDB access in the system MUST go through these helpers.
Never instantiate boto3 clients directly in agent or tool code.

Tables:
  - execution-logs
  - subagent-registry
  - prompt-template-registry
  - guardrail-violations
  - eval-run-results
  - human-review-queue
  - session-state
"""

import os
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Mock store (used when MOCK_STORAGE=true)
# ---------------------------------------------------------------------------

# Seeded mock entries for subagent-registry (one per integration category)
MOCK_SUBAGENT_REGISTRY = [
    {
        "agentId": "mock-confluence-agent",
        "displayName": "Mock Confluence Agent",
        "capabilityDescriptor": "Search and retrieve Confluence documentation, runbooks, and knowledge base articles",
        "category": "knowledge_retrieval",
        "supportedTools": ["confluence_search", "confluence_get_page"],
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}, "confidence_score": {"type": "number"}}},
        "allowedActions": ["confluence_search", "confluence_get_page"],
        "version": "1.0.0",
        "status": "ACTIVE",
        "healthStatus": "HEALTHY",
    },
    {
        "agentId": "mock-cloudwatch-agent",
        "displayName": "Mock CloudWatch Agent",
        "capabilityDescriptor": "Query CloudWatch metrics, logs, and alarms for monitoring and incident investigation",
        "category": "monitoring_query",
        "supportedTools": ["get_metric_statistics", "insights_query", "describe_alarms"],
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}, "confidence_score": {"type": "number"}}},
        "allowedActions": ["get_metric_statistics", "insights_query", "describe_alarms"],
        "version": "1.0.0",
        "status": "ACTIVE",
        "healthStatus": "HEALTHY",
    },
    {
        "agentId": "mock-github-agent",
        "displayName": "Mock GitHub Agent",
        "capabilityDescriptor": "Search code, review pull requests, and inspect GitHub Actions workflow runs",
        "category": "code_review",
        "supportedTools": ["search_code", "get_file", "get_pr", "list_workflow_runs"],
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}, "confidence_score": {"type": "number"}}},
        "allowedActions": ["search_code", "get_file", "get_pr", "list_workflow_runs"],
        "version": "1.0.0",
        "status": "ACTIVE",
        "healthStatus": "HEALTHY",
    },
    {
        "agentId": "mock-infrastructure-agent",
        "displayName": "Mock Infrastructure Agent",
        "capabilityDescriptor": "Inspect and validate CloudFormation stacks, EC2 instances, and infrastructure resources",
        "category": "infrastructure_change",
        "supportedTools": ["describe_stack", "list_stack_resources", "describe_instances"],
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}, "confidence_score": {"type": "number"}}},
        "allowedActions": ["describe_stack", "list_stack_resources", "describe_instances"],
        "version": "1.0.0",
        "status": "ACTIVE",
        "healthStatus": "HEALTHY",
    },
    {
        "agentId": "mock-cost-agent",
        "displayName": "Mock Cost Analysis Agent",
        "capabilityDescriptor": "Analyze AWS cost and usage data, identify cost anomalies and optimization opportunities",
        "category": "cost_analysis",
        "supportedTools": ["get_cost_and_usage", "get_cost_forecast", "list_cost_anomalies"],
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}, "confidence_score": {"type": "number"}}},
        "allowedActions": ["get_cost_and_usage", "get_cost_forecast", "list_cost_anomalies"],
        "version": "1.0.0",
        "status": "ACTIVE",
        "healthStatus": "HEALTHY",
    },
    {
        "agentId": "mock-deployment-agent",
        "displayName": "Mock Deployment Agent",
        "capabilityDescriptor": "Manage and monitor application deployments, ECS services, and CodePipeline executions",
        "category": "deployment",
        "supportedTools": ["describe_service", "list_tasks", "get_pipeline_execution"],
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}, "confidence_score": {"type": "number"}}},
        "allowedActions": ["describe_service", "list_tasks", "get_pipeline_execution"],
        "version": "1.0.0",
        "status": "ACTIVE",
        "healthStatus": "HEALTHY",
    },
]

# Seeded mock entries for prompt-template-registry (one per task category)
MOCK_PROMPT_TEMPLATE_REGISTRY = [
    {
        "templateId": "incident_investigation-v1",
        "taskCategory": "incident_investigation",
        "version": "1.0.0",
        "status": "active",
        "systemPrompt": (
            "You are a senior cloud engineer specializing in incident investigation. "
            "Analyze the provided context and identify root causes, affected services, "
            "and recommended remediation steps. Always cross-reference metrics, logs, "
            "and runbooks before drawing conclusions."
        ),
        "humanTemplate": "{input}",
        "inputVariables": ["input"],
    },
    {
        "templateId": "infrastructure_change-v1",
        "taskCategory": "infrastructure_change",
        "version": "1.0.0",
        "status": "active",
        "systemPrompt": (
            "You are a senior cloud engineer specializing in infrastructure changes. "
            "Evaluate the requested change for safety, compliance, and blast radius. "
            "Validate against existing CloudFormation stacks and IAM policies before "
            "recommending any action."
        ),
        "humanTemplate": "{input}",
        "inputVariables": ["input"],
    },
    {
        "templateId": "cost_analysis-v1",
        "taskCategory": "cost_analysis",
        "version": "1.0.0",
        "status": "active",
        "systemPrompt": (
            "You are a senior cloud engineer specializing in AWS cost optimization. "
            "Analyze cost and usage data to identify anomalies, waste, and savings "
            "opportunities. Provide actionable recommendations with estimated impact."
        ),
        "humanTemplate": "{input}",
        "inputVariables": ["input"],
    },
    {
        "templateId": "deployment-v1",
        "taskCategory": "deployment",
        "version": "1.0.0",
        "status": "active",
        "systemPrompt": (
            "You are a senior cloud engineer specializing in application deployments. "
            "Assess deployment health, pipeline status, and ECS service state. "
            "Identify rollback candidates and surface deployment risks proactively."
        ),
        "humanTemplate": "{input}",
        "inputVariables": ["input"],
    },
    {
        "templateId": "monitoring_query-v1",
        "taskCategory": "monitoring_query",
        "version": "1.0.0",
        "status": "active",
        "systemPrompt": (
            "You are a senior cloud engineer specializing in observability and monitoring. "
            "Query metrics, logs, and alarms to answer operational questions. "
            "Correlate signals across services and highlight anomalies."
        ),
        "humanTemplate": "{input}",
        "inputVariables": ["input"],
    },
    {
        "templateId": "knowledge_retrieval-v1",
        "taskCategory": "knowledge_retrieval",
        "version": "1.0.0",
        "status": "active",
        "systemPrompt": (
            "You are a senior cloud engineer with deep knowledge of internal documentation. "
            "Retrieve and synthesize relevant runbooks, architecture docs, and knowledge "
            "base articles. Always cite your sources and flag gaps in documentation."
        ),
        "humanTemplate": "{input}",
        "inputVariables": ["input"],
    },
    {
        "templateId": "code_review-v1",
        "taskCategory": "code_review",
        "version": "1.0.0",
        "status": "active",
        "systemPrompt": (
            "You are a senior cloud engineer specializing in code and infrastructure review. "
            "Inspect pull requests, workflow runs, and code changes for correctness, "
            "security issues, and compliance with team standards."
        ),
        "humanTemplate": "{input}",
        "inputVariables": ["input"],
    },
]


def _build_mock_store() -> Dict[str, Dict[str, Any]]:
    """Build the initial in-memory mock store seeded with fixture data."""
    store: Dict[str, Dict[str, Any]] = {
        "execution-logs": {},
        "subagent-registry": {},
        "prompt-template-registry": {},
        "guardrail-violations": {},
        "eval-run-results": {},
        "human-review-queue": {},
        "session-state": {},
    }

    # Seed subagent-registry — keyed by agentId
    for entry in MOCK_SUBAGENT_REGISTRY:
        store["subagent-registry"][entry["agentId"]] = entry

    # Seed prompt-template-registry — keyed by templateId
    for entry in MOCK_PROMPT_TEMPLATE_REGISTRY:
        store["prompt-template-registry"][entry["templateId"]] = entry

    return store


# Module-level mock store — persists across calls within a process
_MOCK_STORE: Dict[str, Dict[str, Any]] = _build_mock_store()


def _is_mock() -> bool:
    return os.getenv("MOCK_STORAGE", "").lower() == "true"


# ---------------------------------------------------------------------------
# boto3 resource (lazy-initialised, only when not mocking)
# ---------------------------------------------------------------------------

_dynamodb_resource = None


def _get_resource():
    global _dynamodb_resource
    if _dynamodb_resource is None:
        import boto3

        region = os.getenv("AWS_REGION", "us-east-1")
        _dynamodb_resource = boto3.resource("dynamodb", region_name=region)
    return _dynamodb_resource


def _get_table(table_name: str):
    return _get_resource().Table(table_name)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_item(table_name: str, key: dict) -> Optional[dict]:
    """Return a single item from *table_name* matching *key*, or None."""
    if _is_mock():
        table = _MOCK_STORE.get(table_name, {})
        # Try each key value as a lookup key (supports single-key and composite-key tables)
        for k in key.values():
            item = table.get(k)
            if item is not None:
                return item
        return None

    response = _get_table(table_name).get_item(Key=key)
    return response.get("Item")


def put_item(table_name: str, item: dict) -> None:
    """Write *item* to *table_name*, overwriting any existing item with the same key."""
    if _is_mock():
        table = _MOCK_STORE.setdefault(table_name, {})
        # Use the first value in the item as the in-memory key (mirrors PK behaviour)
        pk = next(iter(item.values()))
        table[pk] = item
        return

    _get_table(table_name).put_item(Item=item)


def query(
    table_name: str,
    key_condition: str,
    expression_values: dict,
    index_name: Optional[str] = None,
) -> List[dict]:
    """
    Query *table_name* using a KeyConditionExpression string.

    Parameters
    ----------
    table_name:
        DynamoDB table name.
    key_condition:
        KeyConditionExpression string, e.g. ``"requestId = :rid"``.
    expression_values:
        ExpressionAttributeValues dict, e.g. ``{":rid": "abc-123"}``.
    index_name:
        Optional GSI name.
    """
    if _is_mock():
        table = _MOCK_STORE.get(table_name, {})
        # Simple mock: return all items whose scalar values match any expression value
        target_values = list(expression_values.values())
        results = []
        for item in table.values():
            for v in item.values():
                try:
                    if v in target_values:
                        results.append(item)
                        break
                except TypeError:
                    pass
        return results

    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": key_condition,
        "ExpressionAttributeValues": expression_values,
    }
    if index_name:
        kwargs["IndexName"] = index_name

    response = _get_table(table_name).query(**kwargs)
    return response.get("Items", [])


def update_item(
    table_name: str,
    key: dict,
    update_expression: str,
    expression_values: dict,
) -> dict:
    """
    Update an item in *table_name* and return the updated attributes.

    Parameters
    ----------
    table_name:
        DynamoDB table name.
    key:
        Primary key dict.
    update_expression:
        UpdateExpression string, e.g. ``"SET #s = :status"``.
    expression_values:
        ExpressionAttributeValues dict.
    """
    if _is_mock():
        table = _MOCK_STORE.setdefault(table_name, {})
        pk = next(iter(key.values()))
        item = table.get(pk, dict(key))
        # Naive mock: merge expression values (strip leading ':') into item
        for placeholder, value in expression_values.items():
            attr = placeholder.lstrip(":")
            item[attr] = value
        table[pk] = item
        return item

    response = _get_table(table_name).update_item(
        Key=key,
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_values,
        ReturnValues="ALL_NEW",
    )
    return response.get("Attributes", {})
