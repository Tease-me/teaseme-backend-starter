import logging
import json
from dataclasses import dataclass
from typing import Optional

from langchain_xai import ChatXAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.core.config import settings
from app.services.system_prompt_service import get_system_prompt
from app.constants import prompt_keys

log = logging.getLogger("moderation.grok")


@dataclass
class GrokVerification:
    confirmed: bool
    confidence: float
    category: str
    reasoning: str


def parse_grok_response(content: str) -> Optional[dict]:
    content = content.strip()
    
    if "```" in content:
        parts = content.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                try:
                    return json.loads(part)
                except:
                    continue
    
    start = content.find("{")
    end = content.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(content[start:end])
        except:
            pass
    
    try:
        return json.loads(content)
    except:
        pass
    
    return None


def get_grok_model():
    return ChatXAI(
        xai_api_key=settings.XAI_API_KEY,
        model="grok-4-1-fast-reasoning",
        temperature=0.0,
        max_tokens=150,
    )


async def verify_with_grok(
    message: str,
    context: str,
    suspected_category: str,
    matched_keyword: str,
    db=None
) -> GrokVerification:

    if not db:
        return GrokVerification(
            confirmed=True,
            confidence=0.5,
            category=suspected_category,
            reasoning="Moderation prompts unavailable - defaulting to confirmed"
        )

    system_prompt = await get_system_prompt(db, prompt_keys.GROK_SYSTEM_PROMPT)
    user_prompt_template = await get_system_prompt(db, prompt_keys.GROK_USER_PROMPT_TEMPLATE)

    if not system_prompt or not user_prompt_template:
        return GrokVerification(
            confirmed=True,
            confidence=0.5,
            category=suspected_category,
            reasoning="Moderation prompts missing - defaulting to confirmed"
        )

    try:
        user_prompt = user_prompt_template.format(
            category=suspected_category,
            keyword=matched_keyword,
            context=context[:500] if context else "(no context)",
            message=message[:500]
        )
    except (KeyError, ValueError):
        return GrokVerification(
            confirmed=True,
            confidence=0.5,
            category=suspected_category,
            reasoning="Moderation prompt template invalid - defaulting to confirmed"
        )
    
    try:
        grok_model = get_grok_model()
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await grok_model.ainvoke(messages)
        content = response.content
        
        result = parse_grok_response(content)
        
        if result:
            return GrokVerification(
                confirmed=result.get("confirmed", True),
                confidence=float(result.get("confidence", 0.5)),
                category=suspected_category,
                reasoning=result.get("reasoning", "No reasoning provided")
            )
        else:
            return GrokVerification(
                confirmed=True,
                confidence=0.5,
                category=suspected_category,
                reasoning="Failed to parse AI response - defaulting to confirmed"
            )
                
    except Exception as e:
        log.exception("Grok API exception")
        return GrokVerification(
            confirmed=True,
            confidence=0.5,
            category=suspected_category,
            reasoning=f"AI verification failed - defaulting to confirmed"
        )
