from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from app.core.config import settings

from langchain_core.prompts import (
    ChatPromptTemplate,
)

MODEL = ChatOpenAI(
    api_key=settings.OPENAI_API_KEY,
    model_name="gpt-4-turbo",
    temperature=0.8,
    max_tokens=512,
)

FACT_EXTRACTOR = ChatOpenAI(
    openai_api_key=settings.OPENAI_API_KEY,
    model="gpt-3.5-turbo"
)

FACT_PROMPT = ChatPromptTemplate.from_template("""
From this conversation, extract any *facts* or *personal info* the AI should remember 
(name, favorites, relationships, secrets…). If nothing new, output 'No new memories.'

User message: {msg}
Context: {ctx}
Bullet points:
""")