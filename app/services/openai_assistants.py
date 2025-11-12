"""OpenAI assistant helpers."""
from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import Tuple

from fastapi import HTTPException
from openai import NotFoundError, OpenAI

from app.core.config import settings

log = logging.getLogger("openai.assistants")

_client = OpenAI(api_key=settings.OPENAI_API_KEY)
DEFAULT_AGENT_MODEL = "gpt-4o-mini"


async def _run_sync(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


async def upsert_influencer_agent(
    *,
    name: str,
    instructions: str,
    assistant_id: str | None = None,
    model: str = DEFAULT_AGENT_MODEL,
) -> str:
    def _create():
        return _client.beta.assistants.create(
            model=model,
            instructions=instructions,
            name=name[:256] if name else None,
        )

    def _update(existing_id: str):
        try:
            return _client.beta.assistants.update(
                existing_id,
                instructions=instructions,
                model=model,
                name=name[:256] if name else None,
            )
        except NotFoundError:
            log.warning("Assistant %s not found when updating, creating a new one.", existing_id)
            return _client.beta.assistants.create(
                model=model,
                instructions=instructions,
                name=name[:256] if name else None,
            )

    if assistant_id:
        assistant = await _run_sync(_update, assistant_id)
    else:
        assistant = await _run_sync(_create)
    return assistant.id


async def _create_thread() -> str:
    thread = await _run_sync(_client.beta.threads.create)
    thread_id = getattr(thread, "id", None)
    if not thread_id:
        raise HTTPException(500, "Failed to create OpenAI thread.")
    return thread_id


async def send_agent_message(
    *,
    assistant_id: str,
    message: str,
    context: str | None = None,
    thread_id: str | None = None,
) -> Tuple[str, str]:
    if not assistant_id:
        raise HTTPException(500, "Assistant ID missing for influencer.")

    async def _append_message(tid: str) -> None:
        await _run_sync(
            _client.beta.threads.messages.create,
            thread_id=tid,
            role="user",
            content=[{"type": "text", "text": message}],
        )

    thread_id = thread_id or await _create_thread()

    try:
        await _append_message(thread_id)
    except NotFoundError:
        thread_id = await _create_thread()
        await _append_message(thread_id)

    run_kwargs = {
        "thread_id": thread_id,
        "assistant_id": assistant_id,
    }
    if context:
        run_kwargs["additional_instructions"] = context

    try:
        run = await _run_sync(_client.beta.threads.runs.create, **run_kwargs)
    except NotFoundError:
        thread_id = await _create_thread()
        await _append_message(thread_id)
        run_kwargs["thread_id"] = thread_id
        run = await _run_sync(_client.beta.threads.runs.create, **run_kwargs)

    run = await _wait_for_run(thread_id, run.id)

    messages = await _run_sync(_client.beta.threads.messages.list, thread_id=thread_id, order="desc", limit=10)
    reply_text = ""
    for msg in getattr(messages, "data", []):
        if getattr(msg, "role", None) == "assistant" and getattr(msg, "run_id", None) == run.id:
            reply_text = _extract_text(msg)
            if reply_text:
                break

    if not reply_text:
        raise HTTPException(502, "Assistant responded without text.")

    return reply_text, thread_id


async def _wait_for_run(thread_id: str, run_id: str, timeout: float = 60.0, poll: float = 0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = await _run_sync(_client.beta.threads.runs.retrieve, thread_id=thread_id, run_id=run_id)
        status = getattr(run, "status", "")
        if status == "completed":
            return run
        if status in {"failed", "cancelled", "expired"}:
            raise HTTPException(502, f"Assistant run {status}.")
        await asyncio.sleep(poll)
    raise HTTPException(504, "Assistant response timed out.")


def _extract_text(message) -> str:
    contents = getattr(message, "content", [])
    for block in contents:
        if getattr(block, "type", None) == "text":
            text_obj = getattr(block, "text", None)
            if text_obj and getattr(text_obj, "value", None):
                return text_obj.value.strip()
    return ""
