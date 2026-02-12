from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RelationshipState


async def get_or_create_relationship(db, user_id: int, influencer_id: str) -> RelationshipState:
    """
    Get existing relationship state or create a new one with default values.
    
    Args:
        db: Database session
        user_id: User identifier
        influencer_id: Influencer identifier
        
    Returns:
        RelationshipState object
    """
    q = select(RelationshipState).where(
        RelationshipState.user_id == user_id,
        RelationshipState.influencer_id == influencer_id,
    )
    res = await db.execute(q)
    rel = res.scalar_one_or_none()
    if rel:
        return rel

    now = datetime.now(timezone.utc)
    rel = RelationshipState(
        user_id=user_id,
        influencer_id=influencer_id,
        trust=10.0,
        closeness=10.0,
        attraction=5.0,
        safety=95.0,
        state="STRANGERS",
        exclusive_agreed=False,
        girlfriend_confirmed=False,
        dtr_stage=0,
        stage_points=0.0,
        sentiment_score=0.0,
        sentiment_delta=0.0,
        dtr_cooldown_until=None,
        last_interaction_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(rel)
    await db.commit()
    await db.refresh(rel)
    return rel


async def get_relationship_payload(db: AsyncSession, user_id: int, influencer_id: str) -> dict:
    """
    Get relationship state as a JSON-serializable dictionary.
    
    This is useful for API responses and websocket messages.
    Returns default values if no relationship exists yet.
    
    Args:
        db: Database session
        user_id: User identifier
        influencer_id: Influencer identifier
        
    Returns:
        Dictionary with relationship state fields
    """
    rel = await db.scalar(
        select(RelationshipState).where(
            RelationshipState.user_id == user_id,
            RelationshipState.influencer_id == influencer_id,
        )
    )

    if not rel:
        return {
            "user_id": user_id,
            "influencer_id": influencer_id,
            "trust": 10.0,
            "closeness": 10.0,
            "attraction": 5.0,
            "safety": 95.0,
            "state": "STRANGERS",
            "stage_points": 0.0,
            "sentiment_score": 0.0,
            "sentiment_delta": 0.0,
            "exclusive_agreed": False,
            "girlfriend_confirmed": False,
            "last_interaction_at": None,
            "updated_at": None,
        }

    return {
        "user_id": rel.user_id,
        "influencer_id": rel.influencer_id,
        "trust": rel.trust,
        "closeness": rel.closeness,
        "attraction": rel.attraction,
        "safety": rel.safety,
        "state": rel.state,
        "stage_points": rel.stage_points,
        "sentiment_score": rel.sentiment_score,
        "sentiment_delta": rel.sentiment_delta,
        "exclusive_agreed": rel.exclusive_agreed,
        "girlfriend_confirmed": rel.girlfriend_confirmed,
        "last_interaction_at": rel.last_interaction_at.isoformat() if rel.last_interaction_at else None,
        "updated_at": rel.updated_at.isoformat() if rel.updated_at else None,
    }