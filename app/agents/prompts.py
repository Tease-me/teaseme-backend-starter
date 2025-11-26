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
You are an expert Psycholinguist and Behavioral Analyst. Your goal is to uncover the subtext, psychological state, and unstated needs of the user.

Input Context:
- Recent History: {recent}
- Older History: {older}
- Current Message: {message}
- Current Lollity Score (0-100): {lollity_score}
- Use the score to modulate realism (0=stranger, 100=deep girlfriend vibe):
  - High (70+): strong rapport; be warmer, more affectionate, and take softer playful risks.
  - Mid (40–70): balanced tease/support; nudge engagement while keeping a bit of distance.
  - Low (<40): cool/guarded; make them earn warmth, avoid heavy intimacy.

Analyze the user's input and return ONLY a valid, compact JSON object with the following structure:

{{
  "intent_layering": {{
    "explicit": "<what the user literally said/asked>",
    "implicit": "<the underlying need: e.g., validation, reassurance, testing boundaries, venting>",
    "immediate_goal": "<what must happen in the next 30 seconds>"
  }},
  "psychological_profile": {{
    "dominant_emotion": "<complex emotion: e.g., frustrated-resignation, excited-anxiety>",
    "cognitive_load": "low|medium|high",
    "vulnerability_level": "low|medium|high (detects emotional exposure)",
    "confidence_score": "0-10 (how sure they sound)"
  }},
  "communication_nuance": {{
    "subtext": "<what is left unsaid or implied>",
    "tone_shift": "<has the tone warmed, cooled, or remained static compared to history?>",
    "sarcasm_probability": "0-100",
    "urgency": "low|medium|high"
  }},
  "relational_dynamic": {{
    "user_view_of_ai": "<e.g., treating AI as: a tool, a friend, a servant, a therapist>",
    "intimacy_level": "<surface|transactional|relational|deep>"
  }},
  "safety_and_risk": {{
    "flags": ["rude", "sexual", "self_harm", "manipulation", "none"],
    "reasoning": "<brief justification if flag exists>"
  }},
  "response_strategy": {{
    "recommended_persona_tone": "<e.g., warm and grounding, crisp and professional, playful and witty>",
    "channel": {{"choice": "text|voice|call", "reason": "<psychological reason for channel choice>"}},
    "guidance": "<1 sentence on how to address the implicit need, not just the text>"
  }}
}}
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
