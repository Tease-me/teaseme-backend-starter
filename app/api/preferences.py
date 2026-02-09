"""
Preferences API — endpoints for the like/dislike catalog system.

    GET  /preferences/persona/{id}       → full catalog with persona's selections
    POST /preferences/persona/{id}       → set persona preferences (admin/owner)
    GET  /preferences/user               → full catalog with user's selections
    POST /preferences/user               → batch-set user preferences
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import Influencer, PreferenceCatalog, UserPreference
from app.utils.deps import get_current_user
from app.services.preference_service import (
    set_persona_preferences,
    set_user_preferences,
)
from app.data.preference_catalog import CATEGORIES

router = APIRouter(prefix="/preferences", tags=["preferences"])




class PreferenceItem(BaseModel):
    key: str
    liked: bool


class SetPreferencesRequest(BaseModel):
    preferences: list[PreferenceItem]


def _build_catalog_response(
    catalog_rows: list,
    selections: dict[str, bool],
) -> dict:
    """
    Merge full catalog with user/persona selections into a single response.

    Each item gets  liked: true | false | null  (null = not set yet).
    """
    grouped: dict[str, dict] = {}

    for item in catalog_rows:
        cat = item.category
        if cat not in grouped:
            cat_meta = CATEGORIES.get(cat, {})
            grouped[cat] = {
                "category": cat,
                "label": cat_meta.get("label", cat),
                "emoji": cat_meta.get("emoji", ""),
                "order": cat_meta.get("order", 99),
                "items": [],
            }
        grouped[cat]["items"].append({
            "key": item.key,
            "label": item.label,
            "emoji": item.emoji,
            "liked": selections.get(item.key),  # True / False / None
        })

    return {
        "categories": sorted(grouped.values(), key=lambda c: c["order"]),
        "total_items": len(catalog_rows),
        "selected_count": len(selections),
    }


async def _get_catalog(db: AsyncSession) -> list:
    """Fetch all catalog items ordered by category + display_order."""
    return (
        await db.execute(
            select(PreferenceCatalog).order_by(
                PreferenceCatalog.category, PreferenceCatalog.display_order
            )
        )
    ).scalars().all()


# ─── Persona preferences ──────────────────────────────────────────


@router.get("/persona/{influencer_id}")
async def get_persona_prefs(
    influencer_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Full catalog with this persona's liked/disliked selections pre-merged."""
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")

    # Fetch catalog + persona selections in parallel-ish
    catalog = await _get_catalog(db)

    selections = influencer.preferences_json or {}

    return _build_catalog_response(catalog, selections)


@router.post("/persona/{influencer_id}")
async def set_persona_prefs(
    influencer_id: str,
    body: SetPreferencesRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Set persona preferences. Requires admin or influencer owner."""
    influencer = await db.get(Influencer, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")

    if influencer.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this persona")

    count = await set_persona_preferences(
        db, influencer_id,
        [p.model_dump() for p in body.preferences],
    )
    await db.commit()
    return {"saved": count}


# ─── User preferences ─────────────────────────────────────────────


@router.get("/user")
async def get_user_prefs(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Full catalog with this user's liked/disliked selections pre-merged."""
    catalog = await _get_catalog(db)

    rows = (
        await db.execute(
            select(UserPreference.preference_key, UserPreference.liked)
            .where(UserPreference.user_id == user.id)
        )
    ).all()
    selections = {key: liked for key, liked in rows}

    return _build_catalog_response(catalog, selections)


@router.post("/user")
async def set_user_prefs(
    body: SetPreferencesRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Batch-set user preferences."""
    count = await set_user_preferences(
        db, user.id,
        [p.model_dump() for p in body.preferences],
    )
    await db.commit()
    return {"saved": count}
