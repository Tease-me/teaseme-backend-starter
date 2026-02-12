"""
Fire-and-forget API usage tracking service.

All tracking is non-blocking — failures are logged but never propagate to callers.
Usage is persisted to the `api_usage_logs` table for analytics.

Usage:
    from app.services.token_tracker import track_usage

    await track_usage(
        category="text",
        provider="openai",
        model="gpt-5.2",
        purpose="main_reply",
        input_tokens=350,
        output_tokens=120,
        latency_ms=820,
        user_id=42,
        influencer_id="luna",
        chat_id="luna_42",
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
# Update these when model pricing changes.
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
# ~$0.30/min for ConvAI, ~$0.18/1000 chars for TTS
_ELEVENLABS_CONVAI_COST_PER_SEC = 5_000    # $0.005/sec = $0.30/min in microdollars
_ELEVENLABS_TTS_COST_PER_SEC    = 3_000    # ~$0.003/sec estimate for TTS


def _estimate_cost(
    model: str,
    provider: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    duration_secs: Optional[float],
    purpose: str,
) -> Optional[int]:
    """Estimate cost in micro-dollars."""
    if provider == "elevenlabs" and duration_secs is not None:
        rate = (
            _ELEVENLABS_CONVAI_COST_PER_SEC
            if purpose == "call_conversation"
            else _ELEVENLABS_TTS_COST_PER_SEC
        )
        return int(duration_secs * rate)

    cost = 0
    if input_tokens and model in _PRICING_INPUT:
        cost += input_tokens * _PRICING_INPUT[model]  # already in microdollars per 1M
        cost = cost // 1_000_000  # normalize back
    if output_tokens and model in _PRICING_OUTPUT:
        out_cost = output_tokens * _PRICING_OUTPUT[model]
        cost += out_cost // 1_000_000

    return cost if cost > 0 else None


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
    Fire-and-forget API usage tracking.

    This function NEVER raises — all errors are logged and swallowed
    so it can't disrupt the main request flow.

    Args:
        category: "text" | "call" | "18_chat" | "18_voice" | "system"
        provider: "openai" | "xai" | "elevenlabs"
        model: The model name (e.g. "gpt-5.2", "grok-4-1-fast-reasoning")
        purpose: What the call was for (e.g. "main_reply", "fact_extraction")
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
