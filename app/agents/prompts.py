from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_xai import ChatXAI
from app.core.config import settings
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys

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

XAI_MODEL = ChatXAI(
    xai_api_key=settings.XAI_API_KEY,
    model="grok-4-1-fast-reasoning",
    temperature=0.7,
    max_tokens=512,
)

async def get_fact_prompt(db) -> ChatPromptTemplate:
    template_str = await get_system_prompt(db, prompt_keys.FACT_PROMPT)
    return ChatPromptTemplate.from_template(template_str)