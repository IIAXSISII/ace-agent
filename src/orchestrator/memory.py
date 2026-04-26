import os
from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer():
    """
    Returns MemorySaver locally (AGENTCORE_MEMORY_STORE_ID unset).
    Returns AgentCoreMemorySaver in production (F02+).
    """
    if os.getenv("AGENTCORE_MEMORY_STORE_ID"):
        from langgraph_checkpoint_aws import AgentCoreMemorySaver
        return AgentCoreMemorySaver(memory_store_id=os.getenv("AGENTCORE_MEMORY_STORE_ID"))
    return MemorySaver()
