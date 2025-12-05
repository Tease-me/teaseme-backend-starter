import logging
import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from sqlalchemy.future import select

from app.api.elevenlabs import update_elevenlabs_prompt
from app.db.models import Influencer
from app.db.session import get_db
from app.schemas.elevenlabs import UpdatePromptBody
from app.schemas.influencer import InfluencerCreate, InfluencerOut, InfluencerUpdate
from app.core.config import settings
from app.utils.s3 import save_influencer_audio_to_s3, get_influencer_audio_download_url,list_influencer_audio_keys, generate_presigned_url

log = logging.getLogger(__name__)

router = APIRouter(prefix="/influencer", tags=["influencer"])

async def _sync_influencer_integrations(
    *,
    influencer: Influencer,
    db: AsyncSession,
    voice_prompt_changed: bool,
) -> None:
    """Ensure GPT + ElevenLabs agents stay in sync before committing."""
    instructions = getattr(influencer, "prompt_template", None)

    if instructions is None:
        raise HTTPException(400, "prompt_template is required to sync influencer assistants.")

    if not getattr(influencer, "voice_id", None) and settings.ELEVENLABS_VOICE_ID:
        influencer.voice_id = settings.ELEVENLABS_VOICE_ID

    voice_prompt_value = getattr(influencer, "voice_prompt", None)
    agent_id = getattr(influencer, "influencer_agent_id_third_part", None)
    resolved_voice_id = getattr(influencer, "voice_id", None) or settings.ELEVENLABS_VOICE_ID
    has_agent_or_voice = bool(agent_id or resolved_voice_id)
    if voice_prompt_changed and voice_prompt_value and has_agent_or_voice:
        body = UpdatePromptBody(
            agent_id=agent_id,
            influencer_id=influencer.id if influencer.id else None,
            voice_prompt=voice_prompt_value,
        )
        await update_elevenlabs_prompt(body=body, db=db, auto_commit=False)
    elif voice_prompt_changed and voice_prompt_value and not has_agent_or_voice:
        log.info(
            "Skipped ElevenLabs sync for influencer %s (missing voice_id and agent id; no default voice configured).",
            getattr(influencer, "id", None),
        )

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
    await db.flush()  # ensure PK row exists before syncing external systems
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

@router.post("/influencer-audio/{influencer_id}")
async def upload_influencer_audio(
    influencer_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Empty file")

    key = await save_influencer_audio_to_s3(
        io.BytesIO(file_bytes),
        file.filename,
        file.content_type or "audio/webm",
        influencer_id,
    )

    url = get_influencer_audio_download_url(key)
    return {"key": key, "url": url}



@router.post("/influencer-audio/{influencer_id}")
async def upload_influencer_audio(
    influencer_id: str,
    file: UploadFile = File(...),
):
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Empty file")

    key = await save_influencer_audio_to_s3(
        io.BytesIO(file_bytes),
        file.filename,
        file.content_type or "audio/webm",
        influencer_id,
    )

    url = generate_presigned_url(key)
    return {"key": key, "url": url}


@router.get("/influencer-audio/{influencer_id}")
async def list_influencer_audio(influencer_id: str):
    keys = await list_influencer_audio_keys(influencer_id)

    if not keys:
        raise HTTPException(status_code=404, detail="Influencer has no audio file stored")

    files = [
        {
            "key": key,
            "download_url": generate_presigned_url(key),
        }
        for key in keys
    ]

    return {
        "influencer_id": influencer_id,
        "count": len(files),
        "files": files,
    }