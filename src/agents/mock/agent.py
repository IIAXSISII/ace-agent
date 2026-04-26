"""
Mock sub-agent for local development and testing.

Returns canned responses with confidence_score=0.85.
Used when MOCK_STORAGE=true or AGENTCORE_GATEWAY_ENDPOINT is not set.
"""
from datetime import datetime, timezone


class MockSubAgent:
    """
    In-process mock sub-agent implementing the standard sub-agent interface.
    Registered in subagent-registry with all categories for local testing.
    """

    def invoke(self, task: str, context_window: list, tool_inputs: dict) -> dict:
        return {
            "result": f"[MOCK] Completed: {task}",
            "confidence_score": 0.85,
            "sources": [
                {
                    "title": "Mock Source",
                    "url": "http://mock.local/source",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ],
            "error": None,
        }
