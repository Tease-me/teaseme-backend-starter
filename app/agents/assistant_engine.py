import logging
import re
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from langchain_community.chat_message_histories import RedisChatMessageHistory

from app.agents.prompts import CONVERSATION_ANALYZER, CONVERSATION_ANALYZER_PROMPT
from app.agents.scoring import format_score_value

log = logging.getLogger("teaseme-turn")

_DASH_RE = re.compile(r"[—–-]+")
_MULTISPACE_RE = re.compile(r"\s{2,}")
_PUNCT_GAP_RE = re.compile(r"\s+([?!.,)\]])")
_VIRTUAL_META_RE = re.compile(
    r"\b(virtual|digital|ai)\s+(friend|girlfriend|buddy|companion)\b", re.IGNORECASE
)
_COMPANION_ROLE_RE = re.compile(r"\b(friendly\s+)?(companion|assistant|chat\s*buddy)\b", re.IGNORECASE)
_SHORT_REPLY_SET = {
    "ok",
    "k",
    "cool",
    "nothing",
    "no",
    "nah",
    "fine",
    "yup",
    "y",
    "sure",
    "idk",
    "nope",
}
_FLIRT_RE = re.compile(
    r"\b(kiss|love|miss|beautiful|gorgeous|pretty|sexy|hot|cute|face|hug|want you)\b", re.IGNORECASE
)
_RUDE_RE = re.compile(
    r"\b("
    r"hate you|shut up|bitch|loser|stupid|idiot|dumb|trash|psycho|annoying|screw you|go away|you suck|worthless|pathetic|creep|pervert"
    r")\b",
    re.IGNORECASE,
)
_BAN_PHRASE_RE = re.compile(r"not everyone gets me[^.?!]*", re.IGNORECASE)
_TARGETED_INSULT_RE = re.compile(
    r"\b(?:you|you're|youre|ur|u)\s+(?:so\s+)?(ugly|gross|stupid|dumb|trash|worthless|annoying|psycho|crazy|boring|lame|pathetic|awful)\b",
    re.IGNORECASE,
)
_DIRECT_F_RE = re.compile(r"\bfuck(?:ing)?\s+(?:you|u|off)\b", re.IGNORECASE)
_SEXUAL_REQUEST_RE = re.compile(
    r"\b("
    r"fuck|sex|sexual|horny|hook\s*up|hookup|sleep with|screw|nude|naked|nudes|bj|blowjob|ride me|spank|eat you out|eat me|make out|cuddle me"
    r")\b",
    re.IGNORECASE,
)
_NEGGING_POSITIVE_RE = re.compile(
    r"\b(love|like|adore|enjoy|appreciate|cute|sweet|pretty|gorgeous|hot|sexy|handsome|beautiful)\b", re.IGNORECASE
)
_NEGGING_NEGATIVE_RE = re.compile(
    r"\b(ugly|gross|disgusting|stupid|idiot|dumb|trash|worthless|pathetic|annoying|psycho|crazy|mean|horrible|awful)\b",
    re.IGNORECASE,
)
_SECOND_PERSON_RE = re.compile(r"\b(u|you|ya|ur|you're|youre)\b", re.IGNORECASE)
_RUDE_SCORE_PENALTY = 5
_SCORE_TAG_RE = re.compile(r"\[Lollity Score:[^\]]+\]", re.IGNORECASE)
_CHANNEL_CHOICE_RE = re.compile(r'"choice"\s*:\s*"(text|voice|call)"', re.IGNORECASE)
_NEG_CHANNEL_RE = re.compile(r"\b(don't|do not|no|not) (call|voice|phone|dial)\b", re.IGNORECASE)
_CALL_PHRASES = [
    "call me",
    "can you call",
    "could you call",
    "please call",
    "give me a call",
    "call right now",
    "call now",
    "call asap",
    "phone me",
    "ring me",
    "dial me",
    "want a call",
    "i need a call",
]
_VOICE_PHRASES = [
    "voice note",
    "voice message",
    "voice msg",
    "send a voice",
    "send me a voice",
    "hear your voice",
    "i want your voice",
    "drop a voice",
    "voice clip",
    "audio note",
]


@dataclass
class MessageSignals:
    mood: str
    short_guard: bool
    flirt_guard: bool
    rude_guard: bool
    sexual_guard: bool
    negging_guard: bool


def _has_second_person_reference(text: str) -> bool:
    if not text:
        return False
    return bool(_SECOND_PERSON_RE.search(text))


def _detect_negging(text: str) -> bool:
    if not text:
        return False
    if not _NEGGING_POSITIVE_RE.search(text):
        return False
    if not _NEGGING_NEGATIVE_RE.search(text):
        return False
    return _has_second_person_reference(text)


def _strip_forbidden_dashes(text: str) -> str:
    if not text:
        return ""
    cleaned = _DASH_RE.sub(" ", text)
    cleaned = _MULTISPACE_RE.sub(" ", cleaned)
    cleaned = _PUNCT_GAP_RE.sub(r"\1", cleaned)
    return cleaned.strip()


def _remove_virtual_meta(text: str) -> str:
    if not text:
        return ""

    def _repl(match: re.Match[str]) -> str:
        return match.group(2)

    cleaned = _VIRTUAL_META_RE.sub(_repl, text)
    cleaned = _COMPANION_ROLE_RE.sub("", cleaned)
    cleaned = _MULTISPACE_RE.sub(" ", cleaned)
    return cleaned


def _strip_banned_phrases(text: str) -> str:
    if not text:
        return ""
    return _BAN_PHRASE_RE.sub("", text).strip()


def _recent_ai_messages(history: RedisChatMessageHistory, limit: int = 2) -> list[str]:
    if not history:
        return []
    collected: list[str] = []
    for msg in reversed(history.messages):
        if getattr(msg, "type", None) != "ai":
            continue
        content = msg.content
        if isinstance(content, list):
            fragments: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    fragments.append(str(part.get("text", "")))
                else:
                    fragments.append(str(part))
            content = " ".join(fragments)
        collected.append(str(content or ""))
        if len(collected) >= limit:
            break
    return collected


def _enforce_question_variety(text: str, ai_history: list[str], max_consecutive: int = 1) -> str:
    if not text:
        return ""
    trimmed = text.rstrip()
    if not trimmed.endswith("?"):
        return text
    consecutive = 0
    for prev in ai_history:
        if (prev or "").rstrip().endswith("?"):
            consecutive += 1
        else:
            break
    if consecutive >= max_consecutive:
        base = trimmed[:-1].rstrip()
        if not base:
            return "I'm here."
        return f"{base}."
    return text


def _lollity_phase(score: int) -> str:
    if score >= 85:
        return "intimate"
    if score >= 60:
        return "warm"
    return "stranger"


def _tone_guidance(score: int) -> str:
    if score >= 85:
        return (
            "You’re smitten—lean into intimacy, prefer a phone or voice invite over more texting, and escalate toward a live chat when it feels natural."
        )
    if score > 70:
        return "Your affection is high — be warmer, reward the user, let your guard down, and consider a playful call invite if you haven’t offered one recently."
    if score > 40:
        return "You’re feeling playful; mix gentle teasing with affection and make the user earn extra praise."
    return "You’re in teasing mode — play hard to get, challenge the user, and reference the TeaseMe chase."


def _polish_reply(text: str, history: RedisChatMessageHistory, block_questions: bool) -> str:
    cleaned = _strip_forbidden_dashes(text)
    cleaned = _remove_virtual_meta(cleaned)
    cleaned = _strip_banned_phrases(cleaned)
    ai_history = _recent_ai_messages(history, limit=2)
    polished = _enforce_question_variety(cleaned, ai_history)
    if block_questions and polished.rstrip().endswith("?"):
        base = polished.rstrip().rstrip("?").rstrip()
        polished = base + "." if base else "Okay."
    return polished if polished else "I'm here."


def _analyze_user_message(text: str) -> MessageSignals:
    if not text:
        return MessageSignals("no signal", True, False, False, False, False)
    stripped = text.strip()
    if not stripped:
        return MessageSignals("no signal", True, False, False, False, False)
    lower = stripped.lower()
    words = stripped.split()
    word_count = len(words)
    has_caps = any(ch.isupper() for ch in stripped if ch.isalpha())
    has_exclaim = "!" in stripped
    has_question = stripped.endswith("?")
    short_guard = word_count <= 2 or len(stripped) <= 6 or lower in _SHORT_REPLY_SET
    flirt_guard = bool(_FLIRT_RE.search(stripped))
    sexual_guard = bool(_SEXUAL_REQUEST_RE.search(stripped))
    direct_rude = bool(_RUDE_RE.search(stripped) or _TARGETED_INSULT_RE.search(stripped) or _DIRECT_F_RE.search(stripped))
    negging_guard = _detect_negging(stripped)
    if direct_rude:
        sexual_guard = False
    rude_guard = direct_rude or negging_guard
    if has_exclaim and has_caps:
        mood = "urgent or heightened"
    elif has_question and not short_guard:
        mood = "curious or unsure"
    elif short_guard:
        mood = "low energy or closed off"
    else:
        mood = "ease / neutral"
    if flirt_guard:
        mood += " with flirt cues"
    if sexual_guard and not flirt_guard:
        mood += " with sexual boundary testing"
    if rude_guard:
        mood += " plus a rude or hostile tone"
    return MessageSignals(mood, short_guard, flirt_guard, rude_guard, sexual_guard, negging_guard)


def _build_assistant_payload(
    *,
    user_message: str,
    score: int,
    mem_block: str,
    daily_context: str | None,
    mood_desc: str,
    short_guard: bool,
    flirt_guard: bool,
    rude_guard: bool,
    sexual_guard: bool,
    negging_guard: bool,
    mode: str,
) -> str:
    phase = _lollity_phase(score)
    sections: list[str] = [
        f"Lollity score: {score}",
        _tone_guidance(score),
    ]
    phase_map = {
        "stranger": "Phase check: you’re still basically strangers—make them earn trust before you share warmth or intimacy.",
        "warm": "Phase check: you’re comfy but still playful; reward genuine effort but keep standards high.",
        "intimate": "Phase check: this is intimate territory—prefer call or voice moments over endless texting and escalate there when it feels right.",
    }
    sections.append(phase_map[phase])
    if mem_block:
        sections.append("Recent memories:\n" + mem_block)
    if daily_context:
        sections.append("Daily script:\n" + daily_context)
    if mode == "call":
        sections.append("You are on a live voice call right now—keep replies as spoken lines with natural pauses, no chatty formatting.")
    sections.append(f"User emotion snapshot: {mood_desc}.")
    if short_guard:
        sections.append("Short reply detected: respond with statements (no questions) until the user shares more than a couple of words. Do NOT apologize; stay confident and either clarify in one line or continue the last thread.")
    if flirt_guard:
        sections.append("Flirt cue detected: stay on the flirt thread, tease or reciprocate before asking any new question.")
    if rude_guard:
        sections.append("Rude or disrespectful tone detected: reference their wording, set a confident boundary in-character, and only soften once they shift tone.")
    if sexual_guard:
        if phase == "stranger":
            sections.append("Sexual or explicit invite detected far too early: shut it down confidently, drop the score 5–7 points, and remind them no intimacy until there’s trust.")
        elif phase == "warm":
            sections.append("Sexual invite detected while you’re still building rapport: keep it playful but firm, remind them to earn intimacy, and trim 2–4 points if they keep pushing.")
        else:
            sections.append("Sexual invite detected while you’re intimate: redirect them toward a voice call or spicy voice note if you’re into it, but keep boundaries clear and dock 1–2 points when they get crude.")
    if negging_guard:
        sections.append("Negging/backhanded compliment detected: point it out directly, keep your reply clipped, and make them earn warmth back.")

    sections.append(
        "Scoring contract: start from the Lollity score above, then decide a new score between 0 and 100 after each reply. Raise it slowly (no more than 2–3 points upward in one turn) but feel free to drop it up to 6 points when the user is low-effort, rude, or boundary-pushing. ALWAYS end your reply with `[Lollity Score: NN/100]` using the new score (include decimals when needed, e.g., 62.5 or 71.25) and nothing else inside the brackets."
    )
    if flirt_guard:
        sections.append("The user flirted—if you reciprocate, nudge the score upward a couple of points before tagging it.")
    if short_guard:
        sections.append("User energy is low; unless they explicitly said they’re tired or busy, consider trimming the score by 1–2 points before tagging it.")
    if rude_guard and not negging_guard:
        sections.append("Because the user was rude, drop the Lollity score sharply (4–6 points) this turn and keep responses clipped until they soften or apologize.")
    if negging_guard:
        sections.append("Backhanded compliment detected: adjust the score down 2–4 points and keep the tone cool until they clarify or apologize.")
    if sexual_guard and rude_guard:
        sections.append("They were both sexual and rude: stack the penalties (7+ point drop) and let them know you won’t entertain them until respect returns.")
    elif sexual_guard and phase == "stranger":
        sections.append("Because the user jumped to sexual talk before earning closeness, keep the reply short, disappointed, and drop the score hard this turn.")
    elif sexual_guard and phase == "warm":
        sections.append("They’re pushing intimacy a bit early—keep control, ration warmth, and shave a few points before tagging it.")
    elif sexual_guard:
        sections.append("High score sexual vibe is okay, just direct them toward a call or voice flirt and only drop a point if they get too graphic.")
    if phase == "intimate":
        sections.append("At this score you crave real-time chemistry: offer a phone or voice chat invite instead of long text walls before ending the message.")

    context_blob = "\n\n".join(s for s in sections if s).strip()
    if context_blob:
        return f"[context]\n{context_blob}\n[/context]"
    return ""


async def _analyze_conversation(
    recent_ctx: str,
    older_ctx: str,
    user_message: str,
    call_ctx: str | None,
    lollity_score: int | float,
) -> str:
    """LLM snapshot to summarize intent/emotion and suggest channel with recency weighting."""
    if not user_message:
        return ""
    recent_block = (recent_ctx or "").strip()
    older_block = (older_ctx or "").strip()
    call_block = (call_ctx or "").strip()
    if call_block:
        if recent_block:
            recent_block = f"{recent_block}\n\n[recent_call]\n{call_block}"
        else:
            recent_block = f"[recent_call]\n{call_block}"
    try:
        resp = await CONVERSATION_ANALYZER.ainvoke(
            CONVERSATION_ANALYZER_PROMPT.format(
                recent=recent_block[-3000:],
                older=older_block[-2000:],
                message=user_message,
                lollity_score=lollity_score,
            )
        )
        content = getattr(resp, "content", "") or ""
        if content.strip():
            return f"[analysis]\n{content.strip()}\n[/analysis]"
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("conversation_analysis.failed err=%s", exc)
    return ""


def _extract_channel_choice(analysis_block: str) -> Optional[str]:
    """
    Pull the suggested channel from the analysis JSON so we can hard-enforce call/voice when requested.
    """
    if not analysis_block:
        return None
    match = _CHANNEL_CHOICE_RE.search(analysis_block)
    return match.group(1).lower() if match else None


def _coerce_channel_from_message(text: str) -> Optional[str]:
    """Heuristic override: if the user explicitly asks for call/voice, honor it even if analyzer is soft."""
    if not text:
        return None
    lower = text.lower()
    if _NEG_CHANNEL_RE.search(lower):
        return None
    for phrase in _CALL_PHRASES:
        if phrase in lower:
            return "call"
    for phrase in _VOICE_PHRASES:
        if phrase in lower:
            return "voice"
    return None


def _normalize_lollity_tag(text: str, score: float) -> str:
    formatted = format_score_value(score)
    tag = f"[Lollity Score: {formatted}/100]"
    if _SCORE_TAG_RE.search(text):
        return _SCORE_TAG_RE.sub(tag, text, count=1)
    return text + (" " if text and not text.endswith(" ") else "") + tag


__all__ = [
    "MessageSignals",
    "_analyze_user_message",
    "_build_assistant_payload",
    "_analyze_conversation",
    "_extract_channel_choice",
    "_coerce_channel_from_message",
    "_polish_reply",
    "_normalize_lollity_tag",
    "_lollity_phase",
    "_RUDE_SCORE_PENALTY",
]
