from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from api.dependencies import get_db, get_current_user
from models.models import User
from services.dream_service import run_dream_phase, run_dream_phase_stream
from core.config import INTERNAL_API_KEY

router = APIRouter(tags=["Dream"])

@router.post("/dream")
async def dream(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    summary = await run_dream_phase(db, current_user.id)
    return summary


@router.post("/dream/stream")
async def dream_stream(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Streaming dream phase — SSE events for each step."""
    return StreamingResponse(
        run_dream_phase_stream(db, current_user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@router.post("/internal/dream")
async def internal_dream(
    db: AsyncSession = Depends(get_db),
    x_api_key: str = Header(alias="X-API-Key"),
):
    """Internal endpoint — called by Function Compute on a cron schedule.
    Runs dream phase for ALL users who are due."""
    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")

    results = []
    users = (await db.execute(select(User))).scalars().all()
    for user in users:
        try:
            summary = await run_dream_phase(db, user.id)
            results.append({"user_id": user.id, "status": summary.get("status", "ok")})
        except Exception as e:
            results.append({"user_id": user.id, "status": "error", "detail": str(e)})

    return {"dream_triggered_for": len(users), "results": results}
