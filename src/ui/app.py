import os
import uuid
import httpx
import chainlit as cl
from src.ui.renderers import render_plan, render_citations, render_confidence
from src.ui.handlers import ChainlitStepHandler

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8080")


@cl.on_chat_start
async def on_chat_start():
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    await cl.Message(
        content="👋 Welcome to the AWS Cloud Engineering Agent! How can I help you today?"
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")

    # Show a thinking step
    async with cl.Step(name="Processing", type="run") as step:
        step.input = message.content

        # Call orchestrator via HTTP
        async with httpx.AsyncClient(timeout=300.0) as client:
            try:
                response = await client.post(
                    f"{ORCHESTRATOR_URL}/invocations",
                    json={
                        "raw_request": message.content,
                        "session_id": session_id,
                        "user_id": "local-user",
                    },
                )
                result = response.json()
            except Exception as e:
                await cl.Message(content=f"❌ Error: {str(e)}").send()
                return

        step.output = "Done"

    # Render final response
    final_response = result.get("final_response", "No response generated.")
    citations = result.get("citations", [])
    confidence = result.get("confidence_score", 0.0)
    error = result.get("error")

    if error:
        await cl.Message(
            content=f"⚠️ Error: {error.get('message', str(error))}"
        ).send()
        return

    # Build response with confidence indicator
    confidence_badge = render_confidence(confidence)
    citations_text = render_citations(citations)

    response_text = f"{confidence_badge}\n\n{final_response}"
    if citations_text:
        response_text += f"\n\n---\n**Sources:**\n{citations_text}"

    await cl.Message(content=response_text).send()
