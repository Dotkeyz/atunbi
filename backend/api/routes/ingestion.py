"""
Omnichannel Ingestion API — upload files (audio, text, PDF) into memory.
"""

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from api.dependencies import get_db, get_current_user
from models import User
from services import ingestion_service

router = APIRouter(tags=["Ingestion"])

@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    conversation_id: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Upload a file (audio, text, PDF) to be ingested into memory."""
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read uploaded file")
    
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    
    # Limit file size to 25MB for safety
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 25MB)")
    
    result = await ingestion_service.ingest_file(
        db, current_user.id, content, file.filename or "upload", conversation_id
    )
    
    return result
