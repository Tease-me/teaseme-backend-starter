import logging
import json
import httpx
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.services.system_prompt_service import get_system_prompt

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


async def verify_with_grok(
    message: str,
    context: str,
    suspected_category: str,
    matched_keyword: str,
    db=None
) -> GrokVerification:
    grok_api_key = getattr(settings, 'XAI_API_KEY', None)
    grok_api_url = 'https://api.x.ai/v1/chat/completions'

    if not grok_api_key:
        log.warning("XAI_API_KEY not configured, assuming violation is confirmed")
        return GrokVerification(
            confirmed=True,
            confidence=0.5,
            category=suspected_category,
            reasoning="AI verification unavailable - defaulting to confirmed"
        )

    if not db:
        log.error("No database session provided for Grok prompt lookup")
        return GrokVerification(
            confirmed=True,
            confidence=0.5,
            category=suspected_category,
            reasoning="Moderation prompts unavailable - defaulting to confirmed"
        )

    system_prompt = await get_system_prompt(db, "GROK_SYSTEM_PROMPT")
    user_prompt_template = await get_system_prompt(db, "GROK_USER_PROMPT_TEMPLATE")

    if not system_prompt or not user_prompt_template:
        log.error(
            "Missing Grok prompts (system=%s user_template=%s)",
            bool(system_prompt),
            bool(user_prompt_template)
        )
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
    except (KeyError, ValueError) as exc:
        log.error("Invalid Grok user prompt template: %s", exc)
        return GrokVerification(
            confirmed=True,
            confidence=0.5,
            category=suspected_category,
            reasoning="Moderation prompt template invalid - defaulting to confirmed"
        )
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                grok_api_url,
                headers={
                    "Authorization": f"Bearer {grok_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "grok-2-latest",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 150
                }
            )
            
            if response.status_code != 200:
                log.error(f"Grok API error: {response.status_code} - {response.text}")
                return GrokVerification(
                    confirmed=True,
                    confidence=0.5,
                    category=suspected_category,
                    reasoning=f"AI API error ({response.status_code}) - defaulting to confirmed"
                )
            
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            log.debug(f"Grok raw response: {content}")
            
            result = parse_grok_response(content)
            
            if result:
                return GrokVerification(
                    confirmed=result.get("confirmed", True),
                    confidence=float(result.get("confidence", 0.5)),
                    category=suspected_category,
                    reasoning=result.get("reasoning", "No reasoning provided")
                )
            else:
                log.warning(f"Failed to parse Grok response as JSON: {content[:200]}")
                return GrokVerification(
                    confirmed=True,
                    confidence=0.5,
                    category=suspected_category,
                    reasoning=f"Failed to parse AI response - defaulting to confirmed"
                )
                
    except Exception as e:
        log.exception(f"Grok API exception: {e}")
        return GrokVerification(
            confirmed=True,
            confidence=0.5,
            category=suspected_category,
            reasoning=f"AI verification failed ({str(e)}) - defaulting to confirmed"
        )
