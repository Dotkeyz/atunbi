"""Entity repository — CRUD for EntityMemory graph nodes and edges."""
from typing import Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, update as sql_update
from models import EntityMemory, SemanticMemory
import logging

logger = logging.getLogger("atunbi.entity_repo")


async def save_entity(db: AsyncSession, entity: EntityMemory) -> EntityMemory:
    db.add(entity)
    await db.commit()
    await db.refresh(entity)
    return entity


async def supersede_entity_edge(
    db: AsyncSession,
    user_id: int,
    entity_name: str,
    relation: str,
    target_name: str,
) -> int:
    """Mark conflicting entity edges as superseded."""
    stmt = (
        sql_update(EntityMemory)
        .where(EntityMemory.user_id == user_id)
        .where(EntityMemory.entity_name.ilike(entity_name))
        .where(EntityMemory.relation.ilike(relation))
        .where(EntityMemory.target_name.ilike(target_name))
        .where(EntityMemory.status == "active")
        .values(status="superseded")
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount


async def supersede_semantic_facts_for_edge(
    db: AsyncSession,
    user_id: int,
    entity_name: str,
    relation: str,
    old_target: str,
) -> int:
    """Mark SemanticMemory facts matching an old entity edge as superseded."""
    stmt = (
        sql_update(SemanticMemory)
        .where(SemanticMemory.user_id == user_id)
        .where(SemanticMemory.status == "active")
        .where(SemanticMemory.fact.ilike(f"%{entity_name}%"))
        .where(SemanticMemory.fact.ilike(f"%{old_target}%"))
        .values(status="superseded")
    )
    result = await db.execute(stmt)
    await db.commit()
    if result.rowcount:
        logger.info(
            f"[Semantic Supersede] {entity_name} {relation} {old_target}: "
            f"marked {result.rowcount} semantic fact(s) as superseded"
        )
    return result.rowcount


async def get_all_entities(db: AsyncSession, user_id: int) -> list:
    """Get all entity graph edges for a user — used to rebuild the NetworkX graph."""
    stmt = (
        select(EntityMemory)
        .where(EntityMemory.user_id == user_id)
        .where(EntityMemory.status == "active")
        .order_by(EntityMemory.timestamp.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_entity_summary(db: AsyncSession, user_id: int) -> dict[str, list[str]]:
    """Aggregate entity graph edges into grouped summary.
    Returns {type: [names]} — e.g. {'person': ['Dotun', 'Kai'], 'org': ['Paystack']}.
    Both entity_name and target_name are collected as unique entities."""
    rows = await get_all_entities(db, user_id)
    entities: dict[str, set[str]] = {}
    for e in rows:
        for name, etype in [(e.entity_name, e.entity_type), (e.target_name, e.target_type)]:
            if name and etype:
                entities.setdefault(etype.lower(), set()).add(name)
    return {k: sorted(v) for k, v in entities.items()}


async def get_entities_for_conversation(db: AsyncSession, conversation_id: str) -> list:
    """Get entities extracted from a specific conversation."""
    stmt = (
        select(EntityMemory)
        .where(EntityMemory.conversation_id == conversation_id)
        .order_by(EntityMemory.timestamp)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def find_entity_edge(
    db: AsyncSession,
    user_id: int,
    entity_name: str,
    relation: str,
    target_name: str,
) -> Optional[EntityMemory]:
    """Check if an entity relationship already exists (case-insensitive).
    
    Prevents duplicate edges like Ada→live_in→Nairobi appearing 3 times
    when extracted from different messages with inconsistent casing.
    """
    stmt = (
        select(EntityMemory)
        .where(EntityMemory.user_id == user_id)
        .where(EntityMemory.entity_name.ilike(entity_name))
        .where(EntityMemory.relation.ilike(relation))
        .where(EntityMemory.target_name.ilike(target_name))
        .where(EntityMemory.status == "active")
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def get_entities_from_name(db: AsyncSession, user_id: int, entity_name: str) -> list:
    """Get all relationships for a specific entity (as source or target)."""
    stmt = (
        select(EntityMemory)
        .where(EntityMemory.user_id == user_id)
        .where(
            (EntityMemory.entity_name == entity_name) |
            (EntityMemory.target_name == entity_name)
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def find_canonical_name(db: AsyncSession, user_id: int, name: str) -> str:
    """Resolve partial name to canonical form using first/last word matching.
    'Dotun' or 'Akindele' → 'Dotun Akindele'. Skips substrings like 'otun'."""
    if len(name.strip()) < 3:
        return name  # too short to match reliably
    
    stmt = select(EntityMemory).where(EntityMemory.user_id == user_id)
    result = await db.execute(stmt)
    all_entities = result.scalars().all()
    
    name_lower = name.lower().strip()
    name_words = set(name_lower.split())
    best_match = None
    best_len = 0
    
    for e in all_entities:
        for candidate in [e.entity_name, e.target_name]:
            cand_lower = candidate.lower().strip()
            cand_words = cand_lower.split()
            
            if cand_lower == name_lower:
                continue  # already exact match
            
            is_first_word = cand_words and cand_words[0] == name_lower
            is_last_word = len(cand_words) >= 2 and cand_words[-1] == name_lower
            is_expansion = cand_lower.startswith(name_lower + ' ')  # "Dotun" → "Dotun ..."
            
            if (is_first_word or is_last_word or is_expansion) and len(candidate) > best_len:
                best_match = candidate
                best_len = len(candidate)
    
    return best_match if best_match else name
