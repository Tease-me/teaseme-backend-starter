from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import Influencer
from app.schemas.influencer import InfluencerCreate, InfluencerOut, InfluencerUpdate
from typing import List
from sqlalchemy.future import select

router = APIRouter(prefix="/influencer", tags=["influencer"])

@router.get("/", response_model=List[InfluencerOut])
async def list_influencers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Influencer))
    return result.scalars().all()

@router.get("/{id}", response_model=InfluencerOut)
async def get_influencer(id: str, db: AsyncSession = Depends(get_db)):
    influencer = await db.get(Influencer, id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    return influencer

@router.post("/", response_model=InfluencerOut, status_code=201)
async def create_influencer(data: InfluencerCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Influencer, data.id):
        raise HTTPException(400, "Influencer with this id already exists")
    influencer = Influencer(**data.model_dump())
    db.add(influencer)
    await db.commit()
    await db.refresh(influencer)
    return influencer

@router.patch("/{id}", response_model=InfluencerOut)
async def update_influencer(id: str, data: InfluencerUpdate, db: AsyncSession = Depends(get_db)):
    influencer = await db.get(Influencer, id)
    if not influencer:
        raise HTTPException(404, "Influencer not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(influencer, key, value)
    db.add(influencer)
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