"""
Alibaba Cloud EventBridge — Data API SDK for publishing events.
Uses alibabacloud_eventbridge (Data SDK), not the Management SDK.
"""
import json
import time
import uuid
from typing import Optional, Dict, Any
from datetime import datetime

from alibabacloud_eventbridge.client import Client as EBClient
from alibabacloud_eventbridge import models as eb_models
from alibabacloud_tea_util.client import Client as UtilClient
from core.config import ALIBABA_ACCESS_KEY_ID, ALIBABA_ACCESS_KEY_SECRET, EVENTBRIDGE_ENDPOINT, EVENTBRIDGE_BUS_NAME
import logging

logger = logging.getLogger("atunbi.eventbridge")


class EventType:
    MEMORY_CREATED      = "atunbi.memory.created"
    MEMORY_PRUNED       = "atunbi.memory.pruned"
    MEMORY_ARCHIVED     = "atunbi.memory.archived"
    EPISODE_CREATED     = "atunbi.episode.created"
    FACT_EXTRACTED      = "atunbi.fact.extracted"
    DREAM_PHASE_COMPLETE = "atunbi.dream.complete"


_client: Optional[EBClient] = None
# Dead letter queue for failed events
_dead_letter_queue: list[Dict[str, Any]] = []
MAX_DEAD_LETTER_QUEUE_SIZE = 100


def _get_client() -> Optional[EBClient]:
    global _client
    if _client is not None:
        return _client

    if not ALIBABA_ACCESS_KEY_ID or not ALIBABA_ACCESS_KEY_SECRET:
        logger.warning("[EventBridge] Credentials not configured")
        return None

    try:
        config = eb_models.Config(
            access_key_id=ALIBABA_ACCESS_KEY_ID,
            access_key_secret=ALIBABA_ACCESS_KEY_SECRET,
            endpoint=EVENTBRIDGE_ENDPOINT,
        )
        _client = EBClient(config)
        logger.info("[EventBridge] Client initialized successfully")
        return _client
    except Exception as e:
        logger.error(f"[EventBridge] Failed to initialize client: {e}")
        return None


async def publish_event(
    event_type: str,
    subject: str,
    data: dict,
    source: str = "atunbi.memory-service",
    retry_count: int = 0,
) -> bool:
    """
    Publish an event to EventBridge.
    
    Args:
        event_type: Type of the event (e.g., EventType.MEMORY_CREATED)
        subject: Subject identifier for the event
        data: Event payload data
        source: Event source identifier
        retry_count: Number of retry attempts (for internal use)
        
    Returns:
        True if event was published successfully, False otherwise
    """
    client = _get_client()
    if client is None:
        # Don't treat missing client as failure - it's optional
        logger.debug(f"[EventBridge] Client not available, skipping event: {event_type}")
        return False

    event_id = str(uuid.uuid4())
    
    try:
        event = eb_models.CloudEvent(
            datacontenttype="application/json",
            data=UtilClient.to_bytes(json.dumps(data, default=str)),
            id=event_id,
            source=source,
            specversion="1.0",
            type=event_type,
            time=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            subject=subject,
            extensions={
                "aliyuneventbusname": EVENTBRIDGE_BUS_NAME,
            },
        )

        await client.put_events_async([event])
        logger.info(f"[EventBridge] Event published: {event_type} (id={event_id})")
        return True
        
    except Exception as e:
        error_msg = f"[EventBridge] Publish failed for {event_type}: {e}"
        
        # Retry logic with exponential backoff
        if retry_count < 3:
            retry_delay = (2 ** retry_count) * 0.5  # 0.5s, 1s, 2s
            logger.warning(f"{error_msg}. Retrying in {retry_delay}s (attempt {retry_count + 1}/3)")
            await asyncio.sleep(retry_delay)
            return await publish_event(event_type, subject, data, source, retry_count + 1)
        
        # Max retries exceeded - add to dead letter queue
        logger.error(f"{error_msg}. Max retries exceeded.")
        _add_to_dead_letter_queue(event_type, subject, data, source, event_id, str(e))
        return False


def _add_to_dead_letter_queue(
    event_type: str,
    subject: str,
    data: dict,
    source: str,
    event_id: str,
    error: str
):
    """Add failed event to dead letter queue for later processing."""
    global _dead_letter_queue
    
    failed_event = {
        "event_id": event_id,
        "event_type": event_type,
        "subject": subject,
        "data": data,
        "source": source,
        "error": error,
        "failed_at": datetime.utcnow().isoformat(),
        "retry_count": 3,
    }
    
    _dead_letter_queue.append(failed_event)
    
    # Maintain queue size limit
    if len(_dead_letter_queue) > MAX_DEAD_LETTER_QUEUE_SIZE:
        removed = _dead_letter_queue.pop(0)
        logger.warning(
            f"[EventBridge] Dead letter queue full, removing oldest event: {removed['event_id']}"
        )
    
    logger.warning(
        f"[EventBridge] Event added to dead letter queue: {event_type} (queue size: {len(_dead_letter_queue)})"
    )


def get_dead_letter_queue() -> list[Dict[str, Any]]:
    """Get the current dead letter queue contents."""
    return _dead_letter_queue.copy()


async def retry_dead_letter_queue() -> Dict[str, int]:
    """
    Attempt to retry all events in the dead letter queue.
    
    Returns:
        Dictionary with counts of succeeded and failed retries
    """
    global _dead_letter_queue
    
    results = {"succeeded": 0, "failed": 0}
    remaining = []
    
    for event in _dead_letter_queue:
        success = await publish_event(
            event["event_type"],
            event["subject"],
            event["data"],
            event["source"]
        )
        
        if success:
            results["succeeded"] += 1
            logger.info(
                f"[EventBridge] Dead letter event retry succeeded: {event['event_id']}"
            )
        else:
            results["failed"] += 1
            remaining.append(event)
    
    _dead_letter_queue = remaining
    logger.info(
        f"[EventBridge] Dead letter queue retry complete: {results['succeeded']} succeeded, {results['failed']} failed"
    )
    
    return results


# Import asyncio for retry logic
import asyncio
