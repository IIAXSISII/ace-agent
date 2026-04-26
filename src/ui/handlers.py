import asyncio
import json
from typing import Any, Dict
import chainlit as cl
from langchain_core.callbacks import BaseCallbackHandler


class ChainlitStepHandler(BaseCallbackHandler):
    """Surfaces LangGraph node executions as cl.Step in the Chainlit UI."""

    def __init__(self):
        super().__init__()
        self._steps: Dict[str, cl.Step] = {}

    def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs
    ) -> None:
        """Open a cl.Step when a LangGraph node starts."""
        run_id = str(kwargs.get("run_id", ""))
        name = serialized.get("name", "Node") if serialized else "Node"
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._open_step(run_id, name, inputs))
        except Exception:
            pass

    async def _open_step(self, run_id: str, name: str, inputs: dict):
        step = cl.Step(name=name, type="run")
        step.input = json.dumps(inputs, default=str)[:500]
        await step.__aenter__()
        self._steps[run_id] = step

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs
    ) -> None:
        """Stream tool name + inputs into the current step."""
        run_id = str(kwargs.get("run_id", ""))
        tool_name = serialized.get("name", "tool") if serialized else "tool"
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self._update_step(run_id, f"🔧 {tool_name}: {input_str[:200]}")
                )
        except Exception:
            pass

    async def _update_step(self, run_id: str, content: str):
        step = self._steps.get(run_id)
        if step:
            await cl.Message(content=content, parent_id=step.id).send()

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs) -> None:
        """Close the step when a LangGraph node completes."""
        run_id = str(kwargs.get("run_id", ""))
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._close_step(run_id, outputs))
        except Exception:
            pass

    async def _close_step(self, run_id: str, outputs: dict):
        step = self._steps.pop(run_id, None)
        if step:
            step.output = json.dumps(outputs, default=str)[:500]
            await step.__aexit__(None, None, None)
