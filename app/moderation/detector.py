import logging
from dataclasses import dataclass
from typing import Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.moderation.keywords import check_keywords, KeywordMatch
from app.moderation.grok import verify_with_grok

log = logging.getLogger("moderation.detector")


@dataclass
class ModerationResult:
    action: Literal["ALLOW", "FLAG"]
    category: Optional[str] = None
    severity: Optional[str] = None
    keyword: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    tier: str = "NONE"


async def moderate_message(
    message: str,
    context: str,
    db: AsyncSession,
    use_ai: bool = True
) -> ModerationResult:
    if not message or not message.strip():
        return ModerationResult(action="ALLOW", reason="Empty message")
    
    match = check_keywords(message)
    
    if not match:
        return ModerationResult(action="ALLOW", reason="No keyword match")
    
    log.info(
        f"Keyword match: pattern='{match.pattern}' "
        f"category={match.category} severity={match.severity}"
    )
    
    if match.severity == "CRITICAL":
        return ModerationResult(
            action="FLAG",
            category=match.category,
            severity=match.severity,
            keyword=match.pattern,
            confidence=1.0,
            reason=f"Critical keyword match: {match.matched_text}",
            tier="KEYWORD_ONLY"
        )
    
    if use_ai and match.severity in ("HIGH", "MEDIUM"):
        verification = await verify_with_grok(
            message=message,
            context=context,
            suspected_category=match.category,
            matched_keyword=match.pattern,
            db=db
        )
        
        if verification.confirmed:
            return ModerationResult(
                action="FLAG",
                category=match.category,
                severity=match.severity,
                keyword=match.pattern,
                confidence=verification.confidence,
                reason=verification.reasoning,
                tier="AI_CONFIRMED"
            )
        else:
            log.info(
                f"AI rejected flag: confidence={verification.confidence} "
                f"reason={verification.reasoning}"
            )
            return ModerationResult(
                action="ALLOW",
                category=match.category,
                severity=match.severity,
                keyword=match.pattern,
                confidence=verification.confidence,
                reason=f"AI rejected: {verification.reasoning}",
                tier="AI_REJECTED"
            )
    
    return ModerationResult(
        action="FLAG",
        category=match.category,
        severity=match.severity,
        keyword=match.pattern,
        confidence=0.5,
        reason=f"Keyword match (no AI verification): {match.matched_text}",
        tier="KEYWORD_ONLY"
    )
