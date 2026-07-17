from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from api.dependencies import get_db, get_current_user
from models.models import User
from services.dream_service import get_stats as compute_stats
from core.events import event_bus
import asyncio
import json

router = APIRouter(tags=["Stats"])

@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await compute_stats(db, current_user.id)


@router.get("/stats/stream")
async def stream_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """SSE endpoint — pushes stats on every memory mutation. No polling needed."""

    async def event_generator():
        user_id = current_user.id
        queue = event_bus.subscribe(user_id)
        try:
            # Send initial snapshot
            stats = await compute_stats(db, user_id)
            yield f"data: {json.dumps(stats)}\n\n"

            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive ping
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(user_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
