"""
Fire-and-forget API usage tracking service.

All tracking is non-blocking — failures are logged but never propagate to callers.
Usage is persisted to the `api_usage_logs` table for analytics.

Supported Providers:
- OpenAI: GPT models (gpt-5.2, gpt-4.1, gpt-4o, gpt-4o-mini),
          embeddings (text-embedding-3-small),
          Whisper transcription
- XAI: Grok models (grok-4-1-fast-reasoning)
- ElevenLabs: ConvAI voice calls, TTS (eleven_v3)

Categories:
- "text": Regular chat messages
- "18_chat": Adult chat messages
- "call": Voice calls (ElevenLabs ConvAI)
- "18_voice": Adult voice messages (TTS)
- "embedding": Text embeddings for vector search
- "moderation": Content moderation and safety checks
- "transcription": Audio-to-text conversion (Whisper)
- "analysis": Conversation analysis, survey summarization
- "extraction": Fact extraction from user messages
- "assistant": OpenAI assistants functionality

Usage Example:
    from app.services.token_tracker import track_usage_bg

    # After LLM call:
    usage = getattr(response, "usage_metadata", None) or {}
    track_usage_bg(
        category="text",
        provider="openai",
        model="gpt-5.2",
        purpose="main_reply",
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_ms=timer.ms,
        user_id=user_id,
        chat_id=chat_id,
    )
"""

import asyncio
import logging
import time
from typing import Optional

from app.db.models.api_usage import ApiUsageLog
from app.db.session import SessionLocal

log = logging.getLogger("token-tracker")


# ── Model Pricing (micro-dollars per token) ──────────────────────
# 1 micro-dollar = $0.000001
# Last updated: 2026-02-13
#
# Sources:
# - OpenAI: https://openai.com/api/pricing/
# - XAI: https://docs.x.ai/developers/models
# - ElevenLabs: https://elevenlabs.io/pricing/api
_PRICING_INPUT = {
    # OpenAI
    "gpt-5.2":                  2_500,   # $2.50 / 1M input tokens
    "gpt-4.1":                  2_000,   # $2.00 / 1M input tokens
    "gpt-4o":                   2_500,   # $2.50 / 1M input tokens
    "gpt-4o-mini":                150,   # $0.15 / 1M input tokens
    "text-embedding-3-small":      20,   # $0.02 / 1M input tokens
    # XAI
    "grok-4-1-fast-reasoning":  3_000,   # $3.00 / 1M input tokens (estimated)
}

_PRICING_OUTPUT = {
    # OpenAI
    "gpt-5.2":                 10_000,   # $10.00 / 1M output tokens
    "gpt-4.1":                  8_000,   # $8.00 / 1M output tokens
    "gpt-4o":                  10_000,   # $10.00 / 1M output tokens 
    "gpt-4o-mini":                600,   # $0.60 / 1M output tokens
    "text-embedding-3-small":       0,   # embeddings have no output tokens
    # XAI
    "grok-4-1-fast-reasoning": 15_000,   # $15.00 / 1M output tokens (estimated)
}

# ElevenLabs: charged per character or per minute for ConvAI
# Official: $0.10/min for ConvAI, ~$0.18/1000 chars for TTS
_ELEVENLABS_CONVAI_COST_PER_SEC = 1_667    # $0.001667/sec = $0.10/min in microdollars
_ELEVENLABS_TTS_COST_PER_SEC    = 3_000    # ~$0.003/sec estimate for TTS

# Whisper: charged per minute of audio
_WHISPER_COST_PER_MINUTE = 6_000  # $0.006/min in microdollars


def _estimate_cost(
    model: str,
    provider: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    duration_secs: Optional[float],
    purpose: str,
) -> Optional[int]:
    """
    Estimate cost in raw units (not micro-dollars despite column name).

    Returns raw cost value where:
    - 1,000,000 units = 1 micro-dollar
    - 1,000,000,000,000 units = 1 USD

    This preserves precision for small API calls that would otherwise round to zero.
    Convert to USD at display time by dividing by 1 trillion.
    """
    # Handle ElevenLabs time-based pricing
    if provider == "elevenlabs" and duration_secs is not None:
        rate = (
            _ELEVENLABS_CONVAI_COST_PER_SEC
            if purpose == "call_conversation"
            else _ELEVENLABS_TTS_COST_PER_SEC
        )
        return int(duration_secs * rate)

    # Handle Whisper time-based pricing
    if model == "whisper-1" and duration_secs is not None:
        duration_mins = duration_secs / 60.0
        return int(duration_mins * _WHISPER_COST_PER_MINUTE)

    # Handle token-based pricing
    # Pricing constants store microdollars per token (before division)
    # Calculation: accumulate (tokens × rate), then divide once at the end
    cost = 0
    has_pricing = False

    if input_tokens:
        if model in _PRICING_INPUT:
            cost += input_tokens * _PRICING_INPUT[model]
            has_pricing = True
        else:
            log.warning(
                "Unknown model '%s' (provider=%s) - no input pricing available. "
                "Add pricing to _PRICING_INPUT in token_tracker.py",
                model, provider
            )

    if output_tokens:
        if model in _PRICING_OUTPUT:
            cost += output_tokens * _PRICING_OUTPUT[model]
            has_pricing = True
        else:
            log.warning(
                "Unknown model '%s' (provider=%s) - no output pricing available. "
                "Add pricing to _PRICING_OUTPUT in token_tracker.py",
                model, provider
            )

    # Return raw cost value (don't divide yet to preserve precision for small calls)
    # The column name is estimated_cost_micros but it stores raw units where 1M units = 1 microdollar
    # Division by 1M happens at display time to convert to microdollars
    return cost if has_pricing else None


async def track_usage(
    category: str,
    provider: str,
    model: str,
    purpose: str,
    *,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    duration_secs: Optional[float] = None,
    latency_ms: Optional[int] = None,
    user_id: Optional[int] = None,
    influencer_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None,
) -> None:
    """
    Track API usage with cost estimation.

    This function NEVER raises — all errors are logged and swallowed
    so it can't disrupt the main request flow.

    Note: estimated_cost_micros stores raw cost units (1 trillion units = 1 USD)
    to preserve precision for small API calls. Convert to USD at display time.

    Args:
        category: "text" | "call" | "18_chat" | "18_voice" | "embedding" | "moderation" | "transcription" | "analysis" | "extraction" | "assistant"
        provider: "openai" | "xai" | "elevenlabs"
        model: Model name (e.g. "gpt-5.2", "grok-4-1-fast-reasoning", "whisper-1")
        purpose: Purpose of call (e.g. "main_reply", "moderation", "tts", "transcription")
        input_tokens: Number of input tokens (for LLMs)
        output_tokens: Number of output tokens (for LLMs)
        total_tokens: Total tokens (input + output)
        duration_secs: Duration in seconds (for audio services like Whisper, ElevenLabs)
        latency_ms: API call latency in milliseconds
        user_id: User ID for attribution (optional)
        influencer_id: Influencer ID for attribution (optional)
        chat_id: Chat ID for attribution (optional)
        conversation_id: Conversation ID for attribution (optional)
        success: Whether the API call succeeded (default: True)
        error_message: Error message if success=False (truncated to 500 chars)
    """
    try:
        # Auto-compute total_tokens if not provided
        if total_tokens is None and input_tokens is not None:
            total_tokens = (input_tokens or 0) + (output_tokens or 0)

        estimated_cost = _estimate_cost(
            model, provider, input_tokens, output_tokens, duration_secs, purpose,
        )

        row = ApiUsageLog(
            category=category,
            provider=provider,
            model=model,
            purpose=purpose,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_micros=estimated_cost,
            duration_secs=duration_secs,
            latency_ms=latency_ms,
            user_id=user_id,
            influencer_id=influencer_id,
            chat_id=chat_id,
            conversation_id=conversation_id,
            success=success,
            error_message=error_message[:500] if error_message else None,
        )

        async with SessionLocal() as db:
            db.add(row)
            await db.commit()

    except Exception as exc:
        log.warning("track_usage failed: %s", exc, exc_info=False)


def track_usage_bg(
    category: str,
    provider: str,
    model: str,
    purpose: str,
    **kwargs,
) -> None:
    """
    Schedule track_usage as a background task (fire-and-forget).

    Use this when you don't want to await the tracking call.
    """
    try:
        asyncio.create_task(
            track_usage(category, provider, model, purpose, **kwargs)
        )
    except RuntimeError:
        # No running event loop — skip silently
        log.debug("track_usage_bg: no event loop, skipping")


class UsageTimer:
    """Context manager to measure latency for API calls.
    
    Usage:
        timer = UsageTimer()
        timer.start()
        result = await llm.ainvoke(...)
        timer.stop()
        
        await track_usage(..., latency_ms=timer.ms)
    """

    def __init__(self) -> None:
        self._start: float = 0
        self._end: float = 0

    def start(self) -> "UsageTimer":
        self._start = time.perf_counter()
        return self

    def stop(self) -> "UsageTimer":
        self._end = time.perf_counter()
        return self

    @property
    def ms(self) -> int:
        return int((self._end - self._start) * 1000)
