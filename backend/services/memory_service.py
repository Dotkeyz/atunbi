import datetime
import math
import uuid
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models import WorkingMemory, SemanticMemory, EpisodicMemory
from repositories import memory_repo, config_repo
from services.qwen_service import get_embedding, score_importance, score_emotion, generate_response, generate_stream, summarize_episode

async def process_chat(db: AsyncSession, user_id: int, message: str):
    query_vector = await get_embedding(message)
    importance = await score_importance(message)
    emotion = await score_emotion(message)

    config = await config_repo.get_config(db)

    # Semantic Episode Linking
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
        importance_score=importance,
        emotional_valence=emotion
    )
    await memory_repo.save_working_memory(db, new_memory)

    # Hybrid Search
    rows = await memory_repo.hybrid_search(db, user_id, query_vector, message)
    
    retrieved_context = []
    context_text = []
    for row in rows:
        mem = row[0]
        distance = row[1]
        if distance < config.similarity_threshold:
            mem.access_count += 1
            db.add(mem)
        retrieved_context.append({
            "message": mem.message,
            "importance": mem.importance_score,
            "emotion": mem.emotional_valence,
            "access_count": mem.access_count,
            "distance": distance
        })
        context_text.append(mem.message)
    
    await db.commit()
    
    # The "G" in RAG (Synthesis)
    context_str = "\n".join(context_text) if context_text else "No relevant memories found."
    ai_response = await generate_response(context_str, message)
    
    return conversation_id, retrieved_context, ai_response

async def process_chat_stream(db: AsyncSession, user_id: int, message: str):
    query_vector = await get_embedding(message)
    importance = await score_importance(message)
    emotion = await score_emotion(message)
    config = await config_repo.get_config(db)

    last_mem = await memory_repo.get_last_memory(db, user_id)
    if last_mem:
        dist_result = await db.execute(select(WorkingMemory.embedding.cosine_distance(query_vector)).where(WorkingMemory.id == last_mem.id))
        distance = dist_result.scalar()
        conversation_id = last_mem.conversation_id if distance < config.episode_similarity_threshold else str(uuid.uuid4())
    else:
        conversation_id = str(uuid.uuid4())

    new_memory = WorkingMemory(
        user_id=user_id, message=message, role="user", conversation_id=conversation_id,
        embedding=query_vector, importance_score=importance, emotional_valence=emotion
    )
    await memory_repo.save_working_memory(db, new_memory)

    rows = await memory_repo.hybrid_search(db, user_id, query_vector, message)
    context_text = []
    for row in rows:
        mem = row[0]
        distance = row[1]
        if distance < config.similarity_threshold:
            mem.access_count += 1
            db.add(mem)
        context_text.append(mem.message)
    await db.commit()
    
    context_str = "\n".join(context_text) if context_text else "No relevant memories found."
    
    async for token in generate_stream(context_str, message):
        yield f"data: {token}\n\n"
    yield "data: [DONE]\n\n"

async def run_dream_phase(db: AsyncSession, user_id: int):
    config = await config_repo.get_config(db)
    now = datetime.datetime.utcnow()
    
    all_memories = await memory_repo.get_all_working_memories(db, user_id)
    pruned = 0
    retained = 0
    
    for mem in all_memories:
        # Ebbinghaus Forgetting Curve: R = e^(-t/S)
        hours_since = (now - mem.timestamp).total_seconds() / 3600
        stability = (mem.importance_score * 10) + (mem.access_count * 5) + (abs(mem.emotional_valence) * 5)
        if stability == 0: stability = 0.1
        
        retention = math.exp(-hours_since / stability)
        
        if retention < 0.1 and mem.importance_score < 0.4 and mem.access_count < 2:
            await memory_repo.delete_memory(db, mem)
            pruned += 1
        else:
            retained += 1
            
    clusters = await memory_repo.get_conversation_clusters(db, user_id)
    episodes_created = 0
    
    for cluster in clusters:
        text = "\n".join([f"{m.role}: {m.message}" for m in cluster])
        summary = await summarize_episode(text)
        summary_vector = await get_embedding(summary)
        avg_imp = sum(m.importance_score for m in cluster) / len(cluster)
        
        episode = EpisodicMemory(
            user_id=user_id, summary=summary, embedding=summary_vector, importance_score=avg_imp
        )
        db.add(episode)
        
        for m in cluster:
            await memory_repo.delete_memory(db, m)
        episodes_created += 1
        
    await db.commit()
    
    return {
        "status": "dream_complete", 
        "summary": f"Pruned: {pruned}, Retained: {retained}, Episodic Consolidations: {episodes_created}"
    }

async def get_stats(db: AsyncSession, user_id: int):
    return await memory_repo.get_memory_stats(db, user_id)
