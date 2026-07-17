"""Alibaba OSS storage service — upload, download, signed URLs."""
import logging
import oss2
from core.config import OSS_ACCESS_KEY, OSS_ACCESS_SECRET, OSS_BUCKET, OSS_ENDPOINT, OSS_REGION

logger = logging.getLogger("atunbi.storage")


def _get_bucket() -> oss2.Bucket:
    """Get authenticated OSS bucket. Raises if credentials are missing."""
    if not OSS_ACCESS_KEY or not OSS_ACCESS_SECRET or not OSS_BUCKET:
        raise RuntimeError("OSS credentials not configured — set OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET, OSS_BUCKET")
    auth = oss2.AuthV2(OSS_ACCESS_KEY, OSS_ACCESS_SECRET)
    endpoint = OSS_ENDPOINT or f"oss-{OSS_REGION}.aliyuncs.com"
    return oss2.Bucket(auth, endpoint, OSS_BUCKET)


def upload_file(file_content: bytes, oss_key: str, content_type: str = "application/octet-stream") -> str:
    """Upload file bytes to OSS. Returns the OSS key (path)."""
    bucket = _get_bucket()
    headers = {"Content-Type": content_type}
    bucket.put_object(oss_key, file_content, headers=headers)
    logger.info(f"[OSS] Uploaded {len(file_content)} bytes → {oss_key}")
    return oss_key


def get_signed_url(oss_key: str, expires_seconds: int = 3600) -> str:
    """Generate a time-limited signed URL for private objects."""
    bucket = _get_bucket()
    return bucket.sign_url("GET", oss_key, expires_seconds)


def download_file(oss_key: str) -> bytes:
    """Download file bytes from OSS by key."""
    bucket = _get_bucket()
    result = bucket.get_object(oss_key)
    return result.read()


def file_exists(oss_key: str) -> bool:
    """Check if an object exists in OSS."""
    bucket = _get_bucket()
    return bucket.object_exists(oss_key)


def build_oss_key(user_id: int, conversation_id: str, filename: str) -> str:
    """Build a deterministic OSS key from user + conversation + filename."""
    safe_name = "".join(c if c.isalnum() or c in ".-_" else "_" for c in filename)
    return f"uploads/user_{user_id}/{conversation_id}/{safe_name}"
