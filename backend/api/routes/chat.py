from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from api.dependencies import get_db, get_current_user
from models import User
from schemas import ChatRequest
from services import memory_service

router = APIRouter(tags=["Chat"])

@router.post("/chat")
async def chat(
    request: ChatRequest, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    conversation_id, retrieved, ai_response = await memory_service.process_chat(db, current_user.id, request.message)
    return {
        "status": "success",
        "conversation_id": conversation_id,
        "reply": ai_response,
        "retrieved_memories": retrieved
    }

@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return StreamingResponse(
        memory_service.process_chat_stream(db, current_user.id, request.message),
        media_type="text/event-stream"
    )
