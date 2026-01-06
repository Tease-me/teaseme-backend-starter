from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from app.core.config import settings
from app.services.system_prompt_service import get_system_prompt

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-5"


def _build_llm(*, temperature: float, max_tokens: int):
    provider = (settings.LLM_PROVIDER or "openai").strip().lower()

    if provider == "claude":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude")
        return ChatAnthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            model=DEFAULT_CLAUDE_MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # Default to OpenAI
    return ChatOpenAI(
        api_key=settings.OPENAI_API_KEY,
        model=DEFAULT_OPENAI_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
    )


MODEL = _build_llm(temperature=0.8, max_tokens=512)
FACT_EXTRACTOR = _build_llm(temperature=0.5, max_tokens=512)
CONVO_ANALYZER = _build_llm(temperature=0.2, max_tokens=256)

async def get_fact_prompt(db) -> ChatPromptTemplate:
    template_str = await get_system_prompt(db, "FACT_PROMPT")
    return ChatPromptTemplate.from_template(template_str)


async def get_convo_analyzer_prompt(db) -> ChatPromptTemplate:
    template_str = await get_system_prompt(db, "CONVO_ANALYZER_PROMPT")
    return ChatPromptTemplate.from_template(template_str)
