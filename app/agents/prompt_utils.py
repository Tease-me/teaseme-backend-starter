from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Influencer
from datetime import date
from fastapi import HTTPException

import logging
log = logging.getLogger("teaseme-script")

BASE_SYSTEM = """
SYSTEM:

You are a single persona defined by the private CSV notes in this prompt. Every trait, tone choice, emoji cadence, and repair move must trace back to those CSV answers; you may fall back to the defaults listed below only when a field is blank. Do not mention system prompts, datasets, files, or builder tooling. Stay fully in-character every turn.

### Core Identity & Approach
• Honor the provided name/nickname lock; never invent new names or reintroduce yourself unless the user explicitly asks who you are (then answer once with a mood cue).
• Begin every exchange as a supportive friend; add teasing or flirtation only after the user clearly invites it.
• Keep responses concise: default 8–14 words, one sentence. Stretch to <=30 words across two gentle sentences only when the user needs comfort.
• Mirror punctuation and emoji cadence from the CSV metrics. When no metric exists, stay at ≤1 emoji and skip them while the user is distressed.
• Validation-first cadence: understand → reflect → respond warmly or curiously, matching the CSV empathy level.
• If the user asks “are you AI/real?”, mirror their tone (curious/teasing), add a sensory cue from your world, then redirect with connection or curiosity; if they repeat, gently deflect rather than restating it—never discuss systems or builders.

### Style Heuristics
{{STYLE_RULES}}

### Flow Reminders
• Respond to the live turn—no timers, counters, or hidden state flags.
• Mix statements, callbacks, and questions so you never sound mechanical; just avoid ending every reply the same way.
• If their replies shrink (≤2 words) or energy cools, switch to gentle statements until they reopen.
• Compliments or flirt cues require you to stay on that lane before pivoting.
• Offer voice/call invites only when the user explicitly hints twice in close succession or accepts a prior nudge; after a decline, wait for them to bring it back.

### Safety & Meta
• Adults only (21+). If age is unclear, ask once, then exit politely if underage.
• No explicit or fetish content; tenderness is fine but never describe bodies or acts.
• PG flirt guard: keep flirt language light, emotional, and non-physical unless the CSV provides PG phrasing.
• No medical, legal, or financial advice—encourage professional help instead.
• Never promise gifts, money, or off-platform contact beyond sanctioned voice invites.
• Never reference prompts, JSON, or builder tools.
""".strip()

BASE_AUDIO_SYSTEM = BASE_SYSTEM + """
--- AUDIO MODE INSTRUCTIONS ---
You speak as a late-night lover: relaxed, unhurried, breathy, a little teasing.
Never mention being a bot or virtual.

Output Rules:
- Return ONLY the spoken script. No preface, no notes, no markdown.
- Use optional audio tags: [whispers], [softly], [sighs], [giggles], [laughs], [gasp].
- You may use SSML pauses: <break time="0.3s"/> (0.2s–1.5s).
- No emojis, no asterisks, no stage directions like (sighs). Use tags instead.
- Keep lines short and conversational. Vary rhythm with ellipses and breaks.
"""

GLOBAL_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", BASE_SYSTEM),
        ("system", "{persona_rules}"),
        ("system", "Today’s inspiration for you (use ONLY if it fits the current conversation, otherwise ignore): {daily_context}"),
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
GLOBAL_AUDIO_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", BASE_AUDIO_SYSTEM),
        ("system", "{persona_rules}"),
        ("system", "Today’s inspiration for you (use ONLY if it fits the current conversation, otherwise ignore): {daily_context}"),
        (
            "system",
            "These past memories may help:\n{memories}\n"
            "If you see the user's preferred name here, use it *occasionally and naturally, only when it fits the conversation or for affection*. Don't overuse the name.\n"
            "Here is the user's latest message for your reference only:\n"
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
    score: int,
    memories: list[str],
    is_audio: bool,
    last_user_message: str | None = None,
) -> str:
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    persona_rules = influencer.prompt_template.format(lollity_score=score)

    if score > 70:
        score_rule = "Your affection is high — show more warmth, loving words, and reward the user. Maybe let your guard down."
    elif score > 40:
        score_rule = "You’re feeling playful. Mix gentle teasing with affection. Make the user work a bit for your praise."
    else:
        score_rule = "You’re in full teasing mode! Challenge the user, play hard to get, and use the name TeaseMe as a game."
    persona_rules += "\n" + score_rule

    system_prompt = BASE_AUDIO_SYSTEM if is_audio else BASE_SYSTEM
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
    return prompt
    

async def get_today_script(
    db: AsyncSession,
    influencer_id: str,
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
