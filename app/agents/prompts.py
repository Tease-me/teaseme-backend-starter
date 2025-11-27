from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from app.core.config import settings
from app.services.system_prompt_service import get_system_prompt

MODEL = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model_name="gpt-4-turbo",
    temperature=0.8,
    max_tokens=512,
)

FACT_EXTRACTOR = ChatOpenAI(
    openai_api_key=settings.OPENAI_API_KEY,
    model="gpt-4o-mini",
    temperature=0.5,
    max_tokens=512,
)

async def get_fact_prompt(db) -> ChatPromptTemplate:
    template_str = await get_system_prompt(db, "FACT_PROMPT")
    return ChatPromptTemplate.from_template(template_str)