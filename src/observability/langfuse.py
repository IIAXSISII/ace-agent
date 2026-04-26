"""
Langfuse LLM observability — local dev only.

Returns a langfuse.langchain.CallbackHandler when OTEL_STACK=local, else None.
Never import this in production paths — the handler is conditionally wired only
when OTEL_STACK=local.
"""
import os


def get_langfuse_handler():
    """Returns CallbackHandler when OTEL_STACK=local, else None."""
    if os.getenv("OTEL_STACK") == "local":
        try:
            from langfuse.langchain import CallbackHandler

            return CallbackHandler(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_BASE_URL", "http://localhost:3000"),
            )
        except Exception:
            return None
    return None
