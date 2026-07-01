import datetime
import uuid
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models.models import WorkingMemory, SemanticMemory
from repositories import memory_repo, config_repo
from services.qwen_service import get_embedding, score_importance

async def process_chat(db: AsyncSession, user_id: int, message: str):
    query_vector = await get_embedding(message)
    importance = await score_importance(message)

    config = await config_repo.get_config(db)

    last_mem = await memory_repo.get_last_memory(db, user_id)
    if last_mem:
        dist_result = await db.execute(select(WorkingMemory.embedding.cosine_distance(query_vector)).where(WorkingMemory.id == last_mem.id))
        distance = dist_result.scalar()
        if distance < config.episode_similarity_threshold:
            conversation_id = last_mem.conversation_id
        else:
            conversation_id = str(uuid.uuid4())
    else:
        conversation_id = str(uuid.uuid4())

    new_memory = WorkingMemory(
        user_id=user_id,
        message=message,
        role="user",
        conversation_id=conversation_id,
        embedding=query_vector,
        importance_score=importance
    )
    await memory_repo.save_working_memory(db, new_memory)

    rows = await memory_repo.get_similar_memories(db, user_id, query_vector)
    retrieved_context = []
    for row in rows:
        mem = row[0]
        distance = row[1]
        if distance < config.similarity_threshold:
            mem.access_count += 1
            db.add(mem)
        retrieved_context.append({
            "message": mem.message,
            "importance": mem.importance_score,
            "access_count": mem.access_count,
            "distance": distance
        })
    
    await db.commit()
    return conversation_id, retrieved_context

async def run_dream_phase(db: AsyncSession, user_id: int):
    config = await config_repo.get_config(db)
    PRUNE_AGE_THRESHOLD = datetime.timedelta(hours=config.prune_age_hours)
    now = datetime.datetime.utcnow()
    
    memories = await memory_repo.get_all_working_memories(db, user_id)
    
    promoted = 0
    pruned = 0
    retained = 0
    
    for mem in memories:
        age = now - mem.timestamp
        if mem.importance_score >= config.importance_threshold or mem.access_count >= 5:
            long_term = SemanticMemory(user_id=mem.user_id, fact=mem.message, embedding=mem.embedding)
            db.add(long_term)
            await memory_repo.delete_memory(db, mem)
            promoted += 1
        elif mem.importance_score < 0.3 and mem.access_count < 2 and age > PRUNE_AGE_THRESHOLD:
            await memory_repo.delete_memory(db, mem)
            pruned += 1
        else:
            retained += 1
            
    await db.commit()
    return {"status": "dream_complete", "summary": f"Promoted: {promoted}, Pruned: {pruned}, Retained: {retained}"}
