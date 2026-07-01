from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from api.dependencies import get_db, get_current_user
from models.models import User
from services import memory_service

router = APIRouter(tags=["Dream"])

@router.post("/dream")
async def dream(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    summary = await memory_service.run_dream_phase(db, current_user.id)
    return summary
