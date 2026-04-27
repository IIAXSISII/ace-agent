"""
Langfuse LLM observability — local dev only.

Returns a langfuse.langchain.CallbackHandler when OTEL_STACK=local, else None.
Supports both Langfuse SDK v3 (public_key/secret_key args) and v4 (env-var only).
Never import this in production paths — the handler is conditionally wired only
when OTEL_STACK=local.
"""
import os
import logging

logger = logging.getLogger(__name__)


def get_langfuse_handler():
    """Returns CallbackHandler when OTEL_STACK=local, else None."""
    if os.getenv("OTEL_STACK") != "local":
        return None
    try:
        from langfuse.langchain import CallbackHandler

        # Langfuse v4: credentials are read from env vars automatically
        # (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST)
        # Langfuse v3: accepts public_key/secret_key/host constructor args
        import langfuse as _lf
        version = tuple(int(x) for x in _lf.__version__.split(".")[:2])

        if version >= (4, 0):
            # v4: env vars only — LANGFUSE_HOST maps to LANGFUSE_BASE_URL fallback
            host = os.getenv("LANGFUSE_BASE_URL", "http://localhost:3000")
            os.environ.setdefault("LANGFUSE_HOST", host)
            handler = CallbackHandler()
        else:
            # v3: explicit constructor args
            handler = CallbackHandler(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_BASE_URL", "http://localhost:3000"),
            )

        return handler
    except Exception as exc:
        logger.warning("Failed to initialize Langfuse handler: %s", exc)
        return None
