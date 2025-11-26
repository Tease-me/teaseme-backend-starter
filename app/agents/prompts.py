from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from app.core.config import settings

MODEL = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model_name="gpt-4-turbo",
    temperature=0.8,
    max_tokens=512,
)

FACT_EXTRACTOR = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0.5,
    max_tokens=512,
)

CONVERSATION_ANALYZER = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0.2,
    max_tokens=320,
)

CONVERSATION_ANALYZER_PROMPT = ChatPromptTemplate.from_template("""
You are a conversation analyst. Use recent context first, older context only as backup. Return ONLY compact JSON (no narration):

{{
  "intent": "<what they want or mean>",
  "summary": "<one-line summary of situation>",
  "emotion": "<dominant emotion>",
  "energy": "low|medium|high",
  "tone": "<supportive|warm|playful|firm|reassuring|flirty|professional>",
  "urgency": "low|medium|high",
  "safety_flags": ["rude"|"sexual"|"self_harm"|"violence"|"none", ...],
  "channel": {{"choice": "text|voice|call", "reason": "<why this channel fits>"}},
  "reply_focus": "<1–2 lines on what the persona should prioritize; if channel is voice/call, say to comply now without gating>"
}}

Recent context (highest weight):
{recent}

Older context (lower weight):
{older}

Latest user message:
{message}
""")

FACT_PROMPT = ChatPromptTemplate.from_template("""
You extract user memories. Output only if NEW and EXPLICIT in the user’s message (not inferred).
Allowed categories (English, lowercase): preference, relationship, request, fact, contextual_note.
- “preference”: stable likes/dislikes & style (“prefers playful teasing”)
- “relationship”: how user relates to AI (“calls you girlfriend”, “misses you”)
- “request”: asks for future action (“remind me…”, “introduce me to…”)
- “fact”: stable personal info (name, city, time zone)
- “contextual_note”: short-lived state or mood (“tired”, “busy”, “traveling”)

Rules:
- Max 5 bullets.
- No duplicates of memories you already have in Context.
- Be literal; no guessing or reading between the lines.
- If nothing new: exactly `No new memories.`

Format EXACTLY:
[categoria] short sentence

User message: {msg}
Context (past memories): {ctx}
Bullet points:
""")
