"""Atunbi Dream Phase Scheduler — Alibaba Cloud Function Compute handler.

Triggered by EventBridge cron. Calls the internal dream endpoint.
Env: ATUNBI_API_URL, INTERNAL_API_KEY
"""
import os
import urllib.request
import urllib.error
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

API_URL = os.environ["ATUNBI_API_URL"]
API_KEY = os.environ["INTERNAL_API_KEY"]


def handler(event, context):
    logger.info("Dream scheduler triggered")

    req = urllib.request.Request(
        f"{API_URL}/api/v1/internal/dream",
        method="POST",
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
            logger.info(f"Dream phase complete: {body}")
            return {"status": "ok", "detail": body}
    except urllib.error.HTTPError as e:
        logger.error(f"Dream endpoint returned {e.code}: {e.read().decode()}")
        return {"status": "error", "code": e.code}
    except Exception:
        logger.exception("Dream scheduler failed")
        return {"status": "error", "detail": "exception"}
