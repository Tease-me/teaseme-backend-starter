
from app.db.models import RelationshipState
from sqlalchemy import select, func

from sqlalchemy.ext.asyncio import AsyncSession

async def _get_relationship_payload(db: AsyncSession, user_id: int, influencer_id: str) -> dict:
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
        "exclusive_agreed": rel.exclusive_agreed,
        "girlfriend_confirmed": rel.girlfriend_confirmed,
        "last_interaction_at": rel.last_interaction_at.isoformat() if rel.last_interaction_at else None,
        "updated_at": rel.updated_at.isoformat() if rel.updated_at else None,
    }