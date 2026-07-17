"""
Atunbi Dream Phase Scheduler — Function Compute handler.

Triggered by EventBridge cron rule (every 1 hour).
Calls the internal dream endpoint, which runs consolidation for ALL users due.
Zero state — the app itself tracks last dream time via dream_run_every_h config.

Deploy to Alibaba Cloud Function Compute:
  Runtime: Python 3.11+
  Handler: main.handler
  Env vars:
    ATUNBI_API_URL  = http://8.211.196.226
    INTERNAL_API_KEY = <same as SECRET_KEY>
"""
import os
import urllib.request
import urllib.error
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

API_URL = os.environ.get("ATUNBI_API_URL", "http://8.211.196.226")
API_KEY = os.environ.get("INTERNAL_API_KEY", "")


def handler(event, context):
    """Entry point. Event is the EventBridge cron trigger — we ignore its payload."""
    logger.info("Dream scheduler triggered by EventBridge cron")

    url = f"{API_URL}/api/v1/internal/dream"

    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-API-Key": API_KEY,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
            logger.info(f"Dream phase complete: {body}")
            return {"status": "ok", "detail": body}
    except urllib.error.HTTPError as e:
        logger.error(f"Dream endpoint returned {e.code}: {e.read().decode()}")
        return {"status": "error", "code": e.code}
    except Exception as e:
        logger.exception("Dream scheduler failed")
        return {"status": "error", "detail": str(e)}
