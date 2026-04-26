"""
Shared agent factory for building LLM instances with optional Langfuse callback.

Usage:
    from src.agents.base import build_agent_executor

    executor = build_agent_executor()
    llm = executor["llm"]
    callbacks = executor["callbacks"]

    # Pass callbacks per-invocation (local dev only when OTEL_STACK=local):
    response = llm.invoke(messages, config={"callbacks": callbacks})
"""
import os

from langchain_aws import ChatBedrock

from src.observability.langfuse import get_langfuse_handler


def build_agent_executor(model_id: str = None, **kwargs) -> dict:
    """
    Factory for building agent LLM instances with optional Langfuse callback.

    Returns a dict with:
      - "llm": ChatBedrock instance
      - "callbacks": list of callbacks (includes Langfuse handler when OTEL_STACK=local)
    """
    model_id = model_id or os.getenv(
        "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
    )
    llm = ChatBedrock(model_id=model_id, **kwargs)

    callbacks = []
    handler = get_langfuse_handler()
    if handler:
        callbacks.append(handler)

    return {"llm": llm, "callbacks": callbacks}
