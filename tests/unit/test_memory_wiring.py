"""
Unit tests for src/orchestrator/memory.py

Tests:
  - test_memory_saver_when_env_unset
  - test_agentcore_memory_saver_when_env_set

Feature: feature-02-foundation-infra
"""
from __future__ import annotations

import importlib
import sys
from types import ModuleType



# ---------------------------------------------------------------------------
# Stub langgraph_checkpoint_aws so tests run without the real package.
# The stub exposes AgentCoreMemorySaver as a simple class we can isinstance-check.
# ---------------------------------------------------------------------------

class _FakeAgentCoreMemorySaver:
    def __init__(self, memory_store_id: str):
        self.memory_store_id = memory_store_id


if "langgraph_checkpoint_aws" not in sys.modules:
    _stub = ModuleType("langgraph_checkpoint_aws")
    _stub.AgentCoreMemorySaver = _FakeAgentCoreMemorySaver
    sys.modules["langgraph_checkpoint_aws"] = _stub
else:
    # Patch the existing module's class so isinstance checks work with our fake
    sys.modules["langgraph_checkpoint_aws"].AgentCoreMemorySaver = _FakeAgentCoreMemorySaver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_memory():
    """Reload memory module so env-var changes take effect."""
    import src.orchestrator.memory as mod
    importlib.reload(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetCheckpointer:
    def test_memory_saver_when_env_unset(self, monkeypatch):
        """When AGENTCORE_MEMORY_STORE_ID is not set, get_checkpointer() returns
        a MemorySaver instance."""
        monkeypatch.delenv("AGENTCORE_MEMORY_STORE_ID", raising=False)

        mod = _reload_memory()
        from langgraph.checkpoint.memory import MemorySaver

        result = mod.get_checkpointer()

        assert isinstance(result, MemorySaver), (
            f"Expected MemorySaver, got {type(result).__name__}"
        )

    def test_agentcore_memory_saver_when_env_set(self, monkeypatch):
        """When AGENTCORE_MEMORY_STORE_ID=store-123, get_checkpointer() returns
        an AgentCoreMemorySaver initialised with that store ID."""
        monkeypatch.setenv("AGENTCORE_MEMORY_STORE_ID", "store-123")

        mod = _reload_memory()

        result = mod.get_checkpointer()

        assert isinstance(result, _FakeAgentCoreMemorySaver), (
            f"Expected AgentCoreMemorySaver, got {type(result).__name__}"
        )
        assert result.memory_store_id == "store-123", (
            f"Expected memory_store_id='store-123', got '{result.memory_store_id}'"
        )

    def test_agentcore_memory_saver_uses_correct_store_id(self, monkeypatch):
        """The store ID passed to AgentCoreMemorySaver matches the env var exactly."""
        monkeypatch.setenv("AGENTCORE_MEMORY_STORE_ID", "prod-store-abc-456")

        mod = _reload_memory()
        result = mod.get_checkpointer()

        assert result.memory_store_id == "prod-store-abc-456"
