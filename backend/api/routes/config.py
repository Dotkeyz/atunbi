from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from api.dependencies import get_db, get_current_user
from models.models import User
from schemas.schemas import ConfigUpdate
from services import config_service

router = APIRouter(tags=["Config"])

@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await config_service.get_config(db)

@router.put("/config")
async def update_config(
    update: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await config_service.update_config(db, update)
