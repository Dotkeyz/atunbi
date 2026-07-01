from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from sqlalchemy import or_, func, literal_column
from models import WorkingMemory

async def save_working_memory(db: AsyncSession, memory: WorkingMemory):
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory

async def get_last_memory(db: AsyncSession, user_id: int):
    stmt = select(WorkingMemory).where(WorkingMemory.user_id == user_id).order_by(WorkingMemory.timestamp.desc()).limit(1)
    result = await db.execute(stmt)
    return result.scalars().first()

async def get_similar_memories(db: AsyncSession, user_id: int, query_vector: list[float], limit: int = 3):
    stmt = (
        select(WorkingMemory, WorkingMemory.embedding.cosine_distance(query_vector).label("distance"))
        .where(WorkingMemory.user_id == user_id)
        .order_by("distance")
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.all()

async def get_all_working_memories(db: AsyncSession, user_id: int):
    stmt = select(WorkingMemory).where(WorkingMemory.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalars().all()

async def delete_memory(db: AsyncSession, memory: WorkingMemory):
    await db.delete(memory)

async def get_memory_stats(db: AsyncSession, user_id: int):
    from sqlmodel import func
    from models import EpisodicMemory, SemanticMemory
    
    working_count = (await db.execute(select(func.count(WorkingMemory.id)).where(WorkingMemory.user_id == user_id))).scalar() or 0
    episodic_count = (await db.execute(select(func.count(EpisodicMemory.id)).where(EpisodicMemory.user_id == user_id))).scalar() or 0
    semantic_count = (await db.execute(select(func.count(SemanticMemory.id)).where(SemanticMemory.user_id == user_id))).scalar() or 0
    
    avg_importance = (await db.execute(select(func.avg(WorkingMemory.importance_score)).where(WorkingMemory.user_id == user_id))).scalar() or 0.0
    
    return {
        "working_memory": working_count,
        "episodic_memory": episodic_count,
        "semantic_memory": semantic_count,
        "total_memories": working_count + episodic_count + semantic_count,
        "average_importance": round(float(avg_importance), 2)
    }

async def get_conversation_clusters(db: AsyncSession, user_id: int):
    stmt = select(WorkingMemory.conversation_id).where(WorkingMemory.user_id == user_id).distinct()
    result = await db.execute(stmt)
    conv_ids = result.scalars().all()
    
    clusters = []
    for conv_id in conv_ids:
        stmt = select(WorkingMemory).where(WorkingMemory.user_id == user_id, WorkingMemory.conversation_id == conv_id).order_by(WorkingMemory.timestamp)
        res = await db.execute(stmt)
        memories = res.scalars().all()
        if len(memories) >= 2:
            clusters.append(memories)
    return clusters

async def hybrid_search(db: AsyncSession, user_id: int, query_vector: list[float], user_message: str, limit: int = 5):
    from sqlalchemy import or_
    
    # 1. Vector Search
    vec_stmt = (
        select(WorkingMemory, WorkingMemory.embedding.cosine_distance(query_vector).label("distance"))
        .where(WorkingMemory.user_id == user_id)
        .order_by("distance")
        .limit(limit)
    )
    vec_results = (await db.execute(vec_stmt)).all()
    
    # 2. Keyword Search (Extract words > 4 chars)
    keywords = [w for w in user_message.split() if len(w) > 4]
    kw_results = []
    if keywords:
        keyword_conditions = [WorkingMemory.message.ilike(f"%{kw}%") for kw in keywords]
        # FIX: Use literal_column for raw SQL casting with an alias
        kw_stmt = (
            select(WorkingMemory, literal_column("0.1::float").label("distance"))
            .where(WorkingMemory.user_id == user_id, or_(*keyword_conditions))
            .limit(limit)
        )
        kw_results = (await db.execute(kw_stmt)).all()
        
    # 3. Combine and Deduplicate
    combined = {}
    for row in vec_results:
        combined[row[0].id] = row
    for row in kw_results:
        if row[0].id not in combined:
            combined[row[0].id] = row
            
    sorted_results = sorted(combined.values(), key=lambda x: x[1])
    return sorted_results[:limit]
