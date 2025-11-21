from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from sqlalchemy.future import select

from app.api.elevenlabs import update_elevenlabs_prompt
from app.db.models import Influencer
from app.db.session import get_db
from app.schemas.elevenlabs import UpdatePromptBody
from app.schemas.influencer import InfluencerCreate, InfluencerOut, InfluencerUpdate
from app.services.openai_assistants import upsert_influencer_agent

router = APIRouter(prefix="/influencer", tags=["influencer"])


async def _sync_influencer_integrations(
    *,
    influencer: Influencer,
    db: AsyncSession,
    voice_prompt_changed: bool,
) -> None:
    """Ensure GPT + ElevenLabs agents stay in sync before committing."""
    instructions = getattr(influencer, "prompt_template", None)
    display_name = getattr(influencer, "display_name", None) or influencer.id

    if instructions is None:
        raise HTTPException(400, "prompt_template is required to sync influencer assistants.")

    assistant_id = await upsert_influencer_agent(
        name=display_name,
        instructions=instructions,
        assistant_id=getattr(influencer, "influencer_gpt_agent_id", None),
    )
    influencer.influencer_gpt_agent_id = assistant_id

    if (
        voice_prompt_changed
        and getattr(influencer, "voice_prompt", None)
        and getattr(influencer, "influencer_agent_id_third_part", None)
    ):
        body = UpdatePromptBody(
            agent_id=influencer.influencer_agent_id_third_part,
            influencer_id=influencer.id if inspect(influencer).persistent else None,
            voice_prompt=influencer.voice_prompt,
        )
        await update_elevenlabs_prompt(body=body, db=db, auto_commit=False)

@router.get("", response_model=List[InfluencerOut])
async def list_influencers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Influencer))
    return result.scalars().all()

@router.get("/{id}", response_model=InfluencerOut)
async def get_influencer(id: str, db: AsyncSession = Depends(get_db)):
    influencer = await db.get(Influencer, id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    return influencer

@router.post("", response_model=InfluencerOut, status_code=201)
async def create_influencer(data: InfluencerCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Influencer, data.id):
        raise HTTPException(400, "Influencer with this id already exists")
    influencer = Influencer(**data.model_dump())
    db.add(influencer)
    await _sync_influencer_integrations(
        influencer=influencer,
        db=db,
        voice_prompt_changed=bool(influencer.voice_prompt),
    )
    await db.commit()
    await db.refresh(influencer)
    return influencer

@router.patch("/{id}", response_model=InfluencerOut)
async def update_influencer(id: str, data: InfluencerUpdate, db: AsyncSession = Depends(get_db)):
    influencer = await db.get(Influencer, id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    update_payload = data.model_dump(exclude_unset=True)
    voice_prompt_changed = "voice_prompt" in update_payload
    for key, value in update_payload.items():
        setattr(influencer, key, value)
    db.add(influencer)
    await _sync_influencer_integrations(
        influencer=influencer,
        db=db,
        voice_prompt_changed=voice_prompt_changed,
    )
    await db.commit()
    await db.refresh(influencer)
    return influencer

@router.delete("/{id}")
async def delete_influencer(id: str, db: AsyncSession = Depends(get_db)):
    influencer = await db.get(Influencer, id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    await db.delete(influencer)
    await db.commit()
    return {"ok": True}
