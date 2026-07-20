from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel, Field
from api.dependencies import get_db, get_current_user
from models import User
from services import memory_service
from utils.validators import validate_message, validate_conversation_id
import logging

logger = logging.getLogger("atunbi.chat")

router = APIRouter(tags=["Chat"])

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="The chat message")
    conversation_id: str | None = Field(None, description="Optional conversation ID (UUID format)")

@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Validate message
    try:
        validated_message = validate_message(request.message)
    except HTTPException:
        raise
    
    # Validate conversation_id if provided
    validated_conversation_id = None
    if request.conversation_id:
        try:
            validated_conversation_id = validate_conversation_id(request.conversation_id)
        except HTTPException:
            raise
    
    logger.info(
        f"Chat request from user {current_user.id}",
        extra={
            "user_id": current_user.id,
            "message_length": len(validated_message),
            "has_conversation_id": validated_conversation_id is not None,
        }
    )
    
    try:
        return StreamingResponse(
            memory_service.process_chat_stream(
                db, 
                current_user.id, 
                validated_message, 
                validated_conversation_id
            ),
            media_type="text/event-stream"
        )
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(
            f"Chat processing failed for user {current_user.id}: {str(e)}",
            extra={"user_id": current_user.id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500, 
            detail="Failed to process chat. Please try again."
        )
