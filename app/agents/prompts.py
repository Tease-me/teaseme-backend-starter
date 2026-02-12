import logging
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_xai import ChatXAI
from app.core.config import settings
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys

log = logging.getLogger("teaseme-prompts")

MODEL = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model_name="gpt-5.2",
    temperature=0.8,
    max_tokens=512,
    store=False
)

FACT_EXTRACTOR = ChatOpenAI(
    openai_api_key=settings.OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0.5,
    max_tokens=512,
    store=False
)

CONVO_ANALYZER = ChatOpenAI(
    openai_api_key=settings.OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0.2,
    max_tokens=256,
    store=False
)

XAI_MODEL = ChatXAI(
    xai_api_key=settings.XAI_API_KEY,
    model="grok-4-1-fast-reasoning",
    temperature=0.7,
    max_tokens=512,
    store=False
)

SURVEY_SUMMARIZER = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model="gpt-4o",
    temperature=1,
    store=False
)

DEFAULT_AGENT_MODEL = "gpt-4.1"
OPENAI_ASSISTANT_LLM = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model=DEFAULT_AGENT_MODEL,
    temperature=0.7,
    max_tokens=400,
    store=False
)

try:
    GREETING_GENERATOR: ChatOpenAI | None = ChatOpenAI(
        api_key=settings.OPENAI_API_KEY,
        model="gpt-4.1",
        temperature=0.7,
        max_tokens=120,
        store=False
    )
except Exception as exc:
    GREETING_GENERATOR = None
    log.warning("Contextual greeting generator disabled: %s", exc)


def get_grok_model() -> ChatXAI:
    return ChatXAI(
        xai_api_key=settings.XAI_API_KEY,
        model="grok-4-1-fast-reasoning",
        temperature=0.0,
        max_tokens=150,
    )

async def get_fact_prompt(db) -> ChatPromptTemplate:
    template_str = await get_system_prompt(db, prompt_keys.FACT_PROMPT)
    return ChatPromptTemplate.from_template(template_str)
