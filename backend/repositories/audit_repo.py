"""
Lightweight audit log — fire-and-forget writes for memory operations.
Used by agentic loop, dream phase, ingestion, and tools.
"""
import logging
from sqlmodel.ext.asyncio.session import AsyncSession
from models import MemoryAuditLog

logger = logging.getLogger("atunbi.audit")


def log_audit_event(
    db: AsyncSession,
    user_id: int,
    event: str,
    memory_type: str,
    memory_id: int | None = None,
    detail: str | None = None,
):
    """Write a lightweight audit log entry. Fire-and-forget — added to session, committed later.
    Must never raise — audit logging cannot block the main flow."""
    try:
        entry = MemoryAuditLog(
            user_id=user_id,
            event=event,
            memory_type=memory_type,
            memory_id_val=memory_id,
            detail=detail,
        )
        db.add(entry)
    except Exception:
        pass  # audit logging must never block the main flow
