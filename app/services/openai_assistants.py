"""Simplified OpenAI chat helper (no Assistants API)."""
from __future__ import annotations

import logging
from typing import Tuple

from fastapi import HTTPException
from app.agents.prompts import OPENAI_ASSISTANT_LLM, DEFAULT_AGENT_MODEL as PROMPTS_DEFAULT_AGENT_MODEL

log = logging.getLogger("openai.assistants")

DEFAULT_AGENT_MODEL = PROMPTS_DEFAULT_AGENT_MODEL


async def upsert_influencer_agent(
    *,
    name: str,
    instructions: str,
    assistant_id: str | None = None,
    model: str = DEFAULT_AGENT_MODEL,
) -> str:
    return assistant_id or "legacy-chat-model"


async def send_agent_message(
    *,
    assistant_id: str,
    message: str,
    context: str | None = None,
    thread_id: str | None = None,
    max_attempts: int = 2,
) -> Tuple[str, str | None]:
    if not message:
        raise HTTPException(400, "Message is required.")

    sys_prompt = context.strip() if context else ""
    messages = []
    if sys_prompt:
        messages.append({"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": message})

    try:
        resp = await OPENAI_ASSISTANT_LLM.ainvoke(messages)
        reply_text = getattr(resp, "content", "") or ""
    except Exception as exc:
        log.error("Chat completion failed: %s", exc, exc_info=True)
        raise HTTPException(502, "Assistant chat failed.")

    if not reply_text:
        raise HTTPException(502, "Assistant responded without text.")

    return reply_text, None
