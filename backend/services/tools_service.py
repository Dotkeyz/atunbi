"""Shared tools logic — called by both the REST API and the agentic loop."""
import logging
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models import WorkingMemory, SemanticMemory, EntityMemory

logger = logging.getLogger("atunbi.tools")


async def forget_memories(db: AsyncSession, user_id: int, query: str) -> int:
    forgotten = 0

    wm_stmt = select(WorkingMemory).where(
        WorkingMemory.user_id == user_id,
        WorkingMemory.message.ilike(f"%{query}%"),
    ).limit(20)
    wm_result = await db.execute(wm_stmt)
    wm_rows = wm_result.scalars().all()
    wm_ids = [m.id for m in wm_rows]
    if wm_ids:
        entity_stmt = select(EntityMemory).where(EntityMemory.source_message_id.in_(wm_ids))
        entity_result = await db.execute(entity_stmt)
        for entity in entity_result.scalars().all():
            entity.source_message_id = None
        await db.flush()
    for mem in wm_rows:
        await db.delete(mem)
        forgotten += 1

    sm_stmt = select(SemanticMemory).where(
        SemanticMemory.user_id == user_id,
        SemanticMemory.fact.ilike(f"%{query}%"),
    ).limit(20)
    sm_result = await db.execute(sm_stmt)
    for fact in sm_result.scalars().all():
        fact.status = "superseded"
        db.add(fact)
        forgotten += 1

    em_stmt = select(EntityMemory).where(
        EntityMemory.user_id == user_id,
        (
            EntityMemory.entity_name.ilike(f"%{query}%") |
            EntityMemory.relation.ilike(f"%{query}%") |
            EntityMemory.target_name.ilike(f"%{query}%")
        ),
        EntityMemory.status == "active",
    ).limit(50)
    em_result = await db.execute(em_stmt)
    for entity in em_result.scalars().all():
        entity.status = "superseded"
        entity.confidence = 0.0
        db.add(entity)
        forgotten += 1

    await db.commit()
    return forgotten


async def forget_entities_by_relation(db: AsyncSession, user_id: int, relation: str) -> int:
    forgotten = 0
    
    em_stmt = select(EntityMemory).where(
        EntityMemory.user_id == user_id,
        EntityMemory.relation == relation,
        EntityMemory.status == "active",
    ).limit(50)
    em_result = await db.execute(em_stmt)
    for entity in em_result.scalars().all():
        entity.status = "superseded"
        entity.confidence = 0.0
        db.add(entity)
        forgotten += 1
    
    await db.commit()
    return forgotten


async def list_active_facts(db: AsyncSession, user_id: int, limit: int = 20) -> list[dict]:
    """List active semantic facts for a user."""
    stmt = select(SemanticMemory).where(
        SemanticMemory.user_id == user_id,
        SemanticMemory.status == 'active',
    ).limit(limit)
    result = await db.execute(stmt)
    return [{"id": f.id, "fact": f.fact, "confidence": f.confidence} for f in result.scalars().all()]
