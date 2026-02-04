from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.utils.deps import get_current_user
from app.db.models import RelationshipState, Influencer
from app.services.relationship_dimension_service import (
    get_dimension_descriptions,
    get_stage_requirements
)

router = APIRouter(prefix="/relationship", tags=["relationship"])

@router.get("/{influencer_id}")
async def get_relationship(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    # Validate influencer exists
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail=f"Influencer '{influencer_id}' not found")
    
    rel = await db.scalar(
        select(RelationshipState).where(
            RelationshipState.user_id == user.id,
            RelationshipState.influencer_id == influencer_id,
        )
    )

    if not rel:
        return {
            "user_id": user.id,
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


@router.get("/{influencer_id}/dimensions")
async def get_relationship_dimensions(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Get relationship dimension descriptions based on current relationship stage.
    Returns stage-specific explanations for trust, closeness, attraction, and safety.
    
    Response includes:
    - Current values for each dimension
    - Stage-specific descriptions and guidance
    - Requirements for next relationship stage
    """
    # Validate influencer exists
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail=f"Influencer '{influencer_id}' not found")
    
    # Get current relationship state
    rel = await db.scalar(
        select(RelationshipState).where(
            RelationshipState.user_id == user.id,
            RelationshipState.influencer_id == influencer_id,
        )
    )
    
    # Default values for new relationships
    if not rel:
        current_stage = "STRANGERS"
        current_values = {
            "trust": 10.0,
            "closeness": 10.0,
            "attraction": 5.0,
            "safety": 95.0
        }
    else:
        current_stage = rel.state
        current_values = {
            "trust": rel.trust,
            "closeness": rel.closeness,
            "attraction": rel.attraction,
            "safety": rel.safety
        }
    
    # Get dimension descriptions for current stage
    dimensions = await get_dimension_descriptions(db, current_stage, current_values)
    
    # Get requirements for next stage
    stage_info = await get_stage_requirements(current_stage)
    
    return {
        "current_stage": current_stage,
        "dimensions": dimensions,
        "next_stage": stage_info.get("next_stage"),
        "next_stage_requirements": stage_info.get("requirements", {}),
        "next_stage_description": stage_info.get("description", ""),
        "stage_points": rel.stage_points if rel else 0.0,
        "sentiment_score": rel.sentiment_score if rel else 0.0
    }