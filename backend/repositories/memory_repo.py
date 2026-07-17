import asyncio
import datetime as _dt
import math as _math
from collections import defaultdict
from typing import Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, func
from models import WorkingMemory, SemanticMemory, EpisodicMemory, EntityMemory, ProceduralMemory

RRF_K = 60  # Standard value from IR research — never needs tuning
DEFAULT_RECENCY_HALF_LIFE_DAYS = 7.0  # Fallback if config is unavailable


def _rrf_fuse(*ranked_lists: list, limit: int = 5, half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS, conversation_id: str = ""):
    """
    Reciprocal Rank Fusion — combine N independently ranked lists into one.
    Ignores raw scores — only rank position matters.
    Items appearing high in MULTIPLE lists get boosted (consensus wins).
    
    Recency decay is applied: each item's RRF score is multiplied by
    0.5^(age_days / half_life_days). Recent memories get a gentle boost; old-but-critical
    memories still surface — they just need a stronger semantic match to win.
    
    Items from the current conversation get a 2x boost over historical items.
    
    Each list must be ordered BEST → WORST.
    Returns: [(item, rrf_score), ...] sorted by score descending.
    """
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    scores = defaultdict(float)
    seen = {}
    
    for result_list in ranked_lists:
        for rank, item in enumerate(result_list, start=1):
            key = id(item)
            rrf_score = 1.0 / (RRF_K + rank)
            
            # Recency decay in days — coarse for long-term memory
            ts = getattr(item, 'timestamp', None)
            if ts is not None:
                days_old = (now - ts).total_seconds() / 86400.0
                if days_old > 0:
                    rrf_score *= 0.5 ** (days_old / half_life_days)
            
            # 10% boost for memories cited in last 24h
            last_used = getattr(item, 'last_used_at', None)
            if last_used is not None:
                hours_since_use = (now - last_used).total_seconds() / 3600
                if hours_since_use < 24:
                    rrf_score *= 1.10
            
            # 30% boost for current conversation items
            if conversation_id:
                item_conv = getattr(item, 'conversation_id', '')
                if item_conv and item_conv == conversation_id:
                    rrf_score *= 1.3
            
            scores[key] += rrf_score
            seen[key] = item
    
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(seen[k], score) for k, score in fused[:limit]]

async def save_working_memory(db: AsyncSession, memory: WorkingMemory):
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory

async def get_all_working_memories(db: AsyncSession, user_id: int):
    stmt = select(WorkingMemory).where(WorkingMemory.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalars().all()

async def delete_memory(db: AsyncSession, memory: WorkingMemory):
    """Delete a WorkingMemory row. EntityMemory rows that reference it
    via source_message_id are detached (FK set to NULL) so entity
    knowledge survives while transient working memory is cleaned up."""
    # Detach entity rows first to avoid FK violation.
    # Must flush after NULLing FKs so the UPDATE runs before the DELETE.
    stmt = select(EntityMemory).where(EntityMemory.source_message_id == memory.id)
    result = await db.execute(stmt)
    linked_entities = result.scalars().all()
    for entity in linked_entities:
        entity.source_message_id = None
    if linked_entities:
        await db.flush()
    await db.delete(memory)

async def delete_memory_by_id(db: AsyncSession, memory_id: int, user_id: int) -> bool:
    """Delete a memory by ID, verifying it belongs to the given user. Returns True if deleted."""
    stmt = select(WorkingMemory).where(WorkingMemory.id == memory_id, WorkingMemory.user_id == user_id)
    result = await db.execute(stmt)
    mem = result.scalars().first()
    if not mem:
        return False
    # Detach entity rows first to avoid FK violation
    entity_stmt = select(EntityMemory).where(EntityMemory.source_message_id == memory_id)
    entity_result = await db.execute(entity_stmt)
    linked_entities = entity_result.scalars().all()
    for entity in linked_entities:
        entity.source_message_id = None
    if linked_entities:
        await db.flush()
    await db.delete(mem)
    return True

async def update_memory_content(db: AsyncSession, memory_id: int, user_id: int, new_content: str) -> Optional[WorkingMemory]:
    """Update a memory's content. Returns the updated memory or None if not found."""
    stmt = select(WorkingMemory).where(WorkingMemory.id == memory_id, WorkingMemory.user_id == user_id)
    result = await db.execute(stmt)
    mem = result.scalars().first()
    if mem:
        mem.message = new_content
        db.add(mem)
        return mem
    return None

async def get_memory_by_id(db: AsyncSession, memory_id: int, user_id: int) -> Optional[WorkingMemory]:
    """Get a single memory by ID."""
    stmt = select(WorkingMemory).where(WorkingMemory.id == memory_id, WorkingMemory.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalars().first()

async def get_recent_conversation_messages(db: AsyncSession, conversation_id: str, limit: int = 10):
    """Get the most recent messages from a conversation, ordered by time."""
    stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.conversation_id == conversation_id)
        .order_by(WorkingMemory.timestamp.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    # Reverse so they're in chronological order
    return list(reversed(messages))

async def get_important_memories(db: AsyncSession, conversation_id: str, limit: int = 5):
    """Get high-importance messages from a conversation — critical for MemoryAgent recall."""
    stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.conversation_id == conversation_id)
        .where(WorkingMemory.importance_score >= 0.6)
        .order_by(WorkingMemory.importance_score.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_user_profile(db: AsyncSession, user_id: int, limit: int = 5):
    """Fetch identity facts — SemanticMemory first, fall back to WorkingMemory."""
    stmt = (
        select(SemanticMemory)
        .where(SemanticMemory.user_id == user_id)
        .where(SemanticMemory.status == "active")
        .order_by(SemanticMemory.confidence.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    semantic = list(result.scalars().all())
    if semantic:
        return semantic
    
    stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.user_id == user_id)
        .where(WorkingMemory.role == "user")
        .where(WorkingMemory.importance_score >= 0.5)
        .order_by(WorkingMemory.timestamp.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())

async def get_conversation_clusters(db: AsyncSession, user_id: int):
    """Group working memories by conversation_id"""
    stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.user_id == user_id)
        .order_by(WorkingMemory.conversation_id, WorkingMemory.timestamp)
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()
    
    clusters = {}
    for mem in memories:
        if mem.conversation_id not in clusters:
            clusters[mem.conversation_id] = []
        clusters[mem.conversation_id].append(mem)
    
    return list(clusters.values())

async def hybrid_search(
    db: AsyncSession, 
    user_id: int, 
    query_vector: list[float], 
    query_text: str,
    limit: int = 50,
    half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
    conversation_id: str = "",
):
    """
    TRUE HYBRID RRF RETRIEVAL — 4 parallel queries across ALL user conversations.
    
    1. Vector: Working Memory (all conversations)
    2. Vector: Semantic Memory (global facts)
    3. Vector: Episodic Memory (past summaries)  
    4. Keyword: PostgreSQL full-text search on Working Memory
    
    Combined via Reciprocal Rank Fusion (k=60). Cross-session recall is inherent —
    conversations are never merged, but results from past conversations are surfaced
    with source labels in the context assembly layer.
    
    Returns: [(memory_object, rrf_score), ...] — higher score = better match.
    Cross-encoder early termination handles filtering, so no arbitrary limit needed.
    """
    FETCH_MORE = 200  # Generous fetch — cross-encoder handles the rest
    
    # Query 1: Vector search on Working Memory (all conversations)
    w_stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.user_id == user_id)
        .order_by(WorkingMemory.embedding.cosine_distance(query_vector))
        .limit(FETCH_MORE)
    )
    
    # Query 2: Vector search on Semantic Memory (always global) — exclude superseded facts
    s_stmt = (
        select(SemanticMemory)
        .where(SemanticMemory.user_id == user_id)
        .where(SemanticMemory.status == 'active')
        .order_by(SemanticMemory.embedding.cosine_distance(query_vector))
        .limit(FETCH_MORE)
    )
    
    # Query 3: Vector search on Episodic Memory (always global)
    e_stmt = (
        select(EpisodicMemory)
        .where(EpisodicMemory.user_id == user_id)
        .order_by(EpisodicMemory.embedding.cosine_distance(query_vector))
        .limit(FETCH_MORE)
    )
    
    # Query 4: Keyword full-text search (PostgreSQL built-in, BM25-like)
    fts_query = func.websearch_to_tsquery('english', query_text)
    fts_vector = func.to_tsvector('english', WorkingMemory.message)
    
    kw_stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.user_id == user_id)
        .where(fts_vector.op('@@')(fts_query))
        .order_by(func.ts_rank_cd(fts_vector, fts_query).desc())
        .limit(FETCH_MORE)
    )
    
    # Run all 4 in parallel — same latency as the old 3-query version
    w_res, s_res, e_res, kw_res = await asyncio.gather(
        db.execute(w_stmt),
        db.execute(s_stmt),
        db.execute(e_stmt),
        db.execute(kw_stmt),
    )
    
    vec_working  = list(w_res.scalars().all())
    vec_semantic = list(s_res.scalars().all())
    vec_episodic = list(e_res.scalars().all())
    kw_working   = list(kw_res.scalars().all())
    
# Fuse with RRF — return ALL candidates, cross-encoder handles filtering
    fused = _rrf_fuse(vec_working, vec_semantic, vec_episodic, kw_working, limit=FETCH_MORE, half_life_days=half_life_days, conversation_id=conversation_id)
    
# Return compatible format: (memory_object, pseudo_distance)
    # Lower pseudo_distance = better match (compatible with existing gating logic)
    return [(mem, 1.0 - rrf_score) for mem, rrf_score in fused]

async def get_memory_stats(db: AsyncSession, user_id: int, config=None):
    now = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    
    # Use config values if provided, otherwise defaults
    active_window = config.active_window_h if config else 6.0
    base_hours = config.base_hours if config else 24.0
    hours_per_access = config.hours_per_access if config else 6.0
    emotion_hours = config.emotion_hours if config else 4.0
    min_working_life_h = config.min_working_life_h if config else 1.0
    max_working_life_h = config.max_working_life_h if config else 168.0
    prune_max_importance = config.prune_max_importance if config else 0.3
    
    # Tier counts
    working_count = await db.execute(
        select(func.count(WorkingMemory.id)).where(WorkingMemory.user_id == user_id)
    )
    semantic_count = await db.execute(
        select(func.count(SemanticMemory.id)).where(SemanticMemory.user_id == user_id)
    )
    episodic_count = await db.execute(
        select(func.count(EpisodicMemory.id)).where(EpisodicMemory.user_id == user_id)
    )
    
    # Aggregates
    avg_importance = await db.execute(
        select(func.avg(WorkingMemory.importance_score)).where(WorkingMemory.user_id == user_id)
    )
    avg_access = await db.execute(
        select(func.avg(WorkingMemory.access_count)).where(WorkingMemory.user_id == user_id)
    )
    avg_emotion = await db.execute(
        select(func.avg(WorkingMemory.emotional_valence)).where(WorkingMemory.user_id == user_id)
    )
    
    # Lifecycle breakdown (derived, like the dream phase)
    all_wm = await db.execute(select(WorkingMemory).where(WorkingMemory.user_id == user_id))
    memories = all_wm.scalars().all()
    
    active = inactive = prune_candidates = archive_ready = at_risk = 0
    for m in memories:
        hours_since = (now - m.timestamp).total_seconds() / 3600
        earned_life = (
            m.importance_score * base_hours +
            m.access_count * hours_per_access +
            abs(m.emotional_valence) * emotion_hours
        )
        earned_life = max(min_working_life_h, min(earned_life, max_working_life_h))
        
        if hours_since < active_window:
            active += 1
        elif hours_since < earned_life:
            inactive += 1
        elif m.importance_score < prune_max_importance and m.access_count < 2:
            prune_candidates += 1
        else:
            archive_ready += 1
        
        # At risk: low retention probability
        stability = m.importance_score * 10 + m.access_count * 5 + abs(m.emotional_valence) * 5
        if stability > 0:
            retention = _math.exp(-hours_since / stability)
            if retention < 0.3 and m.importance_score < 0.5:
                at_risk += 1
    
    # Conversation count
    conv_count = await db.execute(
        select(func.count(func.distinct(WorkingMemory.conversation_id)))
        .where(WorkingMemory.user_id == user_id)
    )
    
    # Token savings: naive = sum of all message lengths (chars → tokens)
    total_msg_len = await db.execute(
        select(func.sum(func.length(WorkingMemory.message)))
        .where(WorkingMemory.user_id == user_id)
    )
    naive_tokens = (total_msg_len.scalar() or 0) // 3
    from core.metrics import token_actual_total, token_naive_total
    actual_tokens = token_actual_total.get(user_id, 0)
    tracked_naive = token_naive_total.get(user_id, 0)
    
    # Entity graph count
    entity_count = await db.execute(
        select(func.count(EntityMemory.id)).where(EntityMemory.user_id == user_id)
    )
    
    # Procedural memory count
    procedural_count = await db.execute(
        select(func.count(ProceduralMemory.id)).where(ProceduralMemory.user_id == user_id)
    )
    
    return {
        "working_memory": working_count.scalar() or 0,
        "semantic_memory": semantic_count.scalar() or 0,
        "episodic_memory": episodic_count.scalar() or 0,
        "entity_graph": entity_count.scalar() or 0,
        "procedural_memory": procedural_count.scalar() or 0,
        "conversations": conv_count.scalar() or 0,
        "token_savings": {
            "naive_tokens": naive_tokens,       # if we stuffed all messages into prompt
            "actual_tokens": actual_tokens,      # what Atunbi actually used
            "savings_pct": round((1 - actual_tokens / max(naive_tokens, 1)) * 100, 1) if naive_tokens > 0 else 0
        },
        "average_importance": float(round(avg_importance.scalar() or 0, 2)),
        "average_access": float(round(avg_access.scalar() or 0, 1)),
        "average_emotion": float(round(avg_emotion.scalar() or 0, 2)),
        "lifecycle": {
            "active": active,
            "inactive": inactive,
            "prune_candidates": prune_candidates,
            "archive_ready": archive_ready
        },
        "at_risk": at_risk,
        "total": len(memories)
    }
