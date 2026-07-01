from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from api.dependencies import get_db, get_current_user
from models.models import User
from schemas.schemas import ChatRequest
from services import memory_service

router = APIRouter(tags=["Chat"])

@router.post("/chat")
async def chat(
    request: ChatRequest, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation_id, retrieved = await memory_service.process_chat(db, current_user.id, request.message)
    return {
        "status": "success",
        "conversation_id": conversation_id,
        "retrieved_memories": retrieved
    }
