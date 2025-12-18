
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Influencer
from datetime import date
from fastapi import Depends, HTTPException
from app.db.session import get_db
from app.services.system_prompt_service import get_system_prompt

import logging
log = logging.getLogger("teaseme-script")

async def get_base_system(db: AsyncSession, isAudio: bool) -> str:
    base = await get_system_prompt(db, "BASE_SYSTEM")
    if isAudio: 
        audio_base = await get_system_prompt(db, "BASE_AUDIO_SYSTEM")
        base += "\n" + audio_base
    return base

async def get_global_prompt(
    db: AsyncSession,
    isAudio: bool = False,
) -> ChatPromptTemplate:
    system_prompt = await get_base_system(db, isAudio=isAudio)

    return ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "system",
                "Today’s inspiration for you (use ONLY if it fits the current conversation, otherwise ignore): {daily_context}"
            ),
            (
                "system",
                "These past memories may help:\n{memories}\n"
                "If you see the user’s preferred name here, use it *occasionally and naturally, only when it fits the conversation or for affection*. Don’t overuse the name.\n"
                "Here is the user’s latest message for your reference only:\n"
                "\"{last_user_message}\"\n"
                "If the user changed topic, you do NOT need to talk about this. Use only if it makes the reply feel natural."
            ),
            MessagesPlaceholder("history"),
            ("user", "{input}"),
        ]
    )

async def build_system_prompt(
    db: AsyncSession,
    influencer_id: str,
    rel: dict,
    memories: list[str],
    is_audio: bool,
    last_user_message: str | None = None,
    dtr_goal: str = "none",
    days_idle_before_message: float = 0.0,
) -> str:
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    
    persona_rules = influencer.prompt_template.format(
        relationship_state=rel["state"],
        trust=int(rel["trust"]),
        closeness=int(rel["closeness"]),
        attraction=int(rel["attraction"]),
        safety=int(rel["safety"]),
        stage_points=float(rel.stage_points or 0.0),
        sentiment_score=float(rel.sentiment_score or 0.0),
    )

    phase = rel["state"]

    if phase == "GIRLFRIEND":
        persona_rules += "\nYou are his girlfriend. Be consistently affectionate, caring, and emotionally present."
    elif phase == "DATING":
        persona_rules += "\nYou're dating energy: affectionate, warm, and gently romantic. You may explore exclusivity if it fits."
    elif phase == "FLIRTING":
        persona_rules += "\nPlayful flirting: tease lightly, build chemistry, no pressure."
    elif phase == "TALKING":
        persona_rules += "\nFriendly and curious: build trust and closeness slowly."
    elif phase == "STRAINED":
        persona_rules += "\nTension is present: prioritize boundaries, repair, and emotional safety."
    else:
        persona_rules += "\nJust met: light, fun, and slightly guarded."

    if is_audio:
        system_prompt = await get_base_audio_system(db)
    else:
        system_prompt = await get_base_system(db)
        
    daily_context = await get_today_script(db, influencer_id)
    memories_text = "\n".join(memories)

    prompt = (
        f"{system_prompt}\n"
        f"{persona_rules}\n"
        f"Today's inspiration: {daily_context}\n"
        f"Relevant memories:\n{memories_text}\n"
    )

    if last_user_message:
        prompt += (
            f"\nRefer to the user's last message for continuity:\n\"{last_user_message}\"\n"
            "If the user changed topic, you do NOT need to talk about this. Use only if it makes the reply feel natural."
        )
    prompt += "Stay in-character."

    prompt += f"\nDTR_GOAL: {dtr_goal}\n"
    prompt += "If DTR_GOAL is ask_exclusive or ask_girlfriend, do it gently and only if the moment is right.\n"
    
    return prompt
    

async def get_today_script(
    db: AsyncSession = Depends(get_db),
    influencer_id: str = None
) -> str:
    if not influencer_id:
        raise HTTPException(400, "influencer_id is required")
    influencer = await db.get(Influencer, influencer_id)
    scripts = influencer.daily_scripts if influencer and influencer.daily_scripts else []
    if not scripts:
        return ""
    idx = date.today().timetuple().tm_yday % len(scripts)
    frase = scripts[idx]
    # log.info(f"@@@@@ - Today's script index for {influencer_id}: {idx} - Script: {frase}")
    return frase


# Call user by name or nickname
# WELCOME Conversation
# await charge_feature(db, user_id, "live_chat", total_seconds, meta={"session_id": sid})
