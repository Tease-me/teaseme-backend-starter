from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.utils.auth.dependencies import get_current_user
from app.db.models import RelationshipState, Influencer
from app.services.relationship_dimension_service import (
    get_dimension_descriptions,
    get_stage_requirements
)

router = APIRouter(prefix="/relationship", tags=["relationship"])


def calculate_stage_progress(stage_points: float, state: str) -> float:
    """
    Calculate percentage progress within the current relationship stage.
    
    Stage ranges:
    - HATE: -∞ to -11
    - DISLIKE: -10 to -1 (10 point range)
    - STRANGERS: 0 to 24 (24 point range)
    - FRIENDS: 25 to 49 (24 point range)
    - FLIRTING: 50 to 74 (24 point range)
    - DATING: 75 to 89 (14 point range)
    - GIRLFRIEND: 90 to 100 (10 point range)
    
    Returns percentage (0-100) of progress through current stage.
    """
    stage_ranges = {
        "HATE": (-20.0, -11.0),  # Using -20 as lower bound (from code min)
        "DISLIKE": (-10.0, -1.0),
        "STRANGERS": (0.0, 24.0),
        "FRIENDS": (25.0, 49.0),
        "FLIRTING": (50.0, 74.0),
        "DATING": (75.0, 89.0),
        "GIRLFRIEND": (90.0, 100.0),
    }
    
    if state not in stage_ranges:
        return 0.0
    
    min_points, max_points = stage_ranges[state]
    range_size = max_points - min_points
    
    if range_size <= 0:
        return 100.0
    
    # Calculate progress within the range
    progress_in_range = stage_points - min_points
    percentage = (progress_in_range / range_size) * 100.0
    
    # Clamp between 0 and 100
    return max(0.0, min(100.0, percentage))

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
        state = "STRANGERS"
        stage_points = 0.0
        return {
            "user_id": user.id,
            "influencer_id": influencer_id,
            "trust": 10.0,
            "closeness": 10.0,
            "attraction": 5.0,
            "safety": 95.0,
            "state": state,
            "stage_points": stage_points,
            "stage_progress": calculate_stage_progress(stage_points, state),
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
        "stage_progress": calculate_stage_progress(rel.stage_points, rel.state),
        "sentiment_score": rel.sentiment_score,
        "sentiment_delta": rel.sentiment_delta,
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