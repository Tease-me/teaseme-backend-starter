from datetime import datetime, timezone
from sqlalchemy import select

from app.db.models import RelationshipState

async def get_or_create_relationship(db, user_id: int, influencer_id: str) -> RelationshipState:
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
        dtr_cooldown_until=None,
        last_interaction_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(rel)
    await db.commit()
    await db.refresh(rel)
    return rel