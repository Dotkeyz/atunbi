from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel
from api.dependencies import get_db, get_current_user
from models import User
from services import memory_service

router = APIRouter(tags=["Chat"])

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None

@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        return StreamingResponse(
            memory_service.process_chat_stream(db, current_user.id, request.message, request.conversation_id),
            media_type="text/event-stream"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
