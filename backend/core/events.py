"""
In-memory SSE event bus for real-time stats push to browsers.
Each user gets their own fan-out — no cross-user stats leakage.
"""
import asyncio
import json
import logging
from typing import Dict, Set

logger = logging.getLogger("atunbi.events")


class StatsEventBus:
    """Per-user in-memory fan-out for SSE stats subscribers."""

    def __init__(self):
        self._queues: Dict[int, Set[asyncio.Queue]] = {}

    def subscribe(self, user_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._queues.setdefault(user_id, set()).add(q)
        return q

    def unsubscribe(self, user_id: int, q: asyncio.Queue):
        user_queues = self._queues.get(user_id)
        if user_queues:
            user_queues.discard(q)
            if not user_queues:
                del self._queues[user_id]

    async def broadcast(self, user_id: int, payload: dict):
        """Push stats snapshot to every SSE client for this user."""
        user_queues = self._queues.get(user_id)
        if not user_queues:
            return

        dead = set()
        payload_json = json.dumps(payload)
        for q in user_queues:
            try:
                q.put_nowait(payload_json)
            except asyncio.QueueFull:
                logger.warning(f"SSE queue full for user {user_id}, dropping subscriber")
                dead.add(q)
        user_queues -= dead

# Singleton
event_bus = StatsEventBus()


async def broadcast_stats(stats: dict):
    """Push fresh stats to SSE clients. Errors are logged, never raised.
    Takes the stats dict directly to avoid circular imports with dream_service."""
    # Determine user_id from the first working memory if possible, otherwise broadcast is scoped
    # We need user_id to scope the broadcast — extract from stats if available
    user_id = stats.get("user_id")
    if user_id is not None:
        try:
            await event_bus.broadcast(user_id, stats)
        except Exception:
            logger.exception("broadcast_stats failed")

