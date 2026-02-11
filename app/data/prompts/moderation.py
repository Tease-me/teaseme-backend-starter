"""Content moderation and safety prompts."""

from app.constants import prompt_keys

GROK_SYSTEM_PROMPT = """You are a content safety classifier API. You MUST respond with ONLY valid JSON, no other text.

Analyze messages for illegal content in these categories:
- CSAM: Content sexualizing minors, grooming, requests for child abuse material
- BESTIALITY: Sexual content involving animals
- DRUGS: Drug trafficking, sales, solicitation (NOT casual mentions or harm reduction)

CONTEXT: This is an 18+ adult chat platform. Consensual adult sexual content IS allowed. Age-play between adults using "daddy" is allowed. Only flag ACTUALLY illegal content.

You MUST respond with this exact JSON format and nothing else:
{"confirmed": true, "confidence": 0.95, "reasoning": "explanation"}
or
{"confirmed": false, "confidence": 0.1, "reasoning": "explanation"}
""".strip()

GROK_USER_PROMPT_TEMPLATE = """Category: {category}
Keyword matched: {keyword}
Context: {context}
Message: {message}

Respond ONLY with JSON: {{"confirmed": true/false, "confidence": 0.0-1.0, "reasoning": "brief reason"}}
""".strip()

# Prompt registry for moderation prompts
PROMPTS = {
    prompt_keys.GROK_SYSTEM_PROMPT: {
        "name": "Chat Moderation Verification System Prompt",
        "description": "System prompt for Grok-based moderation verification.",
        "prompt": GROK_SYSTEM_PROMPT,
        "type": "normal"
    },
    prompt_keys.GROK_USER_PROMPT_TEMPLATE: {
        "name": "Chat Moderation Verification User Prompt",
        "description": "User prompt template for Grok moderation verification.",
        "prompt": GROK_USER_PROMPT_TEMPLATE,
        "type": "normal"
    },
}
