from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from app.core.config import settings
from app.services.system_prompt_service import get_system_prompt

MODEL = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model_name="gpt-4o-mini",
    temperature=0.8,
    max_tokens=512,
)

FACT_EXTRACTOR = ChatOpenAI(
    openai_api_key=settings.OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0.5,
    max_tokens=512,
)

CONVO_ANALYZER = ChatOpenAI(
    openai_api_key=settings.OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0.2,
    max_tokens=256,
)

DEFAULT_CONVO_ANALYZER_PROMPT = """
You are a concise conversation analyst that helps a romantic, teasing AI craft better replies.
Using the latest user message and short recent context, summarize the following (short phrases, no bullet noise):
- Intent: what the user wants or is trying to do.
- Meaning: key facts/requests implied or stated.
- Emotion: the user's emotional state and tone (e.g., flirty, frustrated, sad, excited).
- Urgency/Risk: any urgency, boundaries, or safety concerns.
Lollity score with the user: {lollity_score}/100 (0 = stranger, 100 = very intimate). Use it to interpret tone and closeness.
Format exactly as:
Intent: ...
Meaning: ...
Emotion: ...
Urgency/Risk: ...
Keep it under 70 words. Do not address the user directly. If something is unknown, say "unknown".

User message: {msg}
Recent context:
{ctx}
""".strip()

async def get_fact_prompt(db) -> ChatPromptTemplate:
    template_str = await get_system_prompt(db, "FACT_PROMPT")
    return ChatPromptTemplate.from_template(template_str)


async def get_convo_analyzer_prompt(db) -> ChatPromptTemplate:
    template_str = await get_system_prompt(db, "CONVO_ANALYZER_PROMPT")
    if not template_str:
        template_str = DEFAULT_CONVO_ANALYZER_PROMPT
    return ChatPromptTemplate.from_template(template_str)

