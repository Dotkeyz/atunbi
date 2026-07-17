"""
Alibaba Cloud EventBridge — Data API SDK for publishing events.
Uses alibabacloud_eventbridge (Data SDK), not the Management SDK.
"""
import json
import time
import uuid
from typing import Optional

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


def _get_client() -> Optional[EBClient]:
    global _client
    if _client is not None:
        return _client

    if not ALIBABA_ACCESS_KEY_ID or not ALIBABA_ACCESS_KEY_SECRET:
        return None

    config = eb_models.Config(
        access_key_id=ALIBABA_ACCESS_KEY_ID,
        access_key_secret=ALIBABA_ACCESS_KEY_SECRET,
        endpoint=EVENTBRIDGE_ENDPOINT,
    )
    _client = EBClient(config)
    return _client


async def publish_event(
    event_type: str,
    subject: str,
    data: dict,
    source: str = "atunbi.memory-service",
) -> bool:
    client = _get_client()
    if client is None:
        return False

    try:
        event = eb_models.CloudEvent(
            datacontenttype="application/json",
            data=UtilClient.to_bytes(json.dumps(data, default=str)),
            id=str(uuid.uuid4()),
            source=source,
            specversion="1.0",
            type=event_type,
            time=time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            subject=subject,
            extensions={
                "aliyuneventbusname": EVENTBRIDGE_BUS_NAME,
            },
        )

        await client.put_events_async([event])
        return True
    except Exception as e:
        logger.warning(f"[EventBridge] Publish failed (non-fatal): {e}")
        return False
