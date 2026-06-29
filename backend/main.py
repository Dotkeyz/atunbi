from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager
from sqlmodel import select
import datetime

from database import init_db, async_session
from models import WorkingMemory, SemanticMemory
from qwen_service import get_embedding, score_importance

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🧠 Booting up Atunbi... Initializing Cognitive Schema...")
    await init_db()
    print("✅ Database tables created. Atunbi is awake.")
    yield

app = FastAPI(title="Atunbi Cognitive Architecture", lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    user_id: str = "dotun-test"

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        query_vector = await get_embedding(request.message)
        importance = await score_importance(request.message)

        async with async_session() as session:
            # 1. Save the new thought
            new_memory = WorkingMemory(
                user_id=request.user_id,
                message=request.message,
                role="user",
                embedding=query_vector,
                importance_score=importance
            )
            session.add(new_memory)
            await session.commit()
            
            # 2. Semantic Search + Calculate Exact Distance
            statement = (
                select(WorkingMemory, WorkingMemory.embedding.cosine_distance(query_vector).label("distance"))
                .where(WorkingMemory.user_id == request.user_id)
                .order_by("distance")
                .limit(3)
            )
            result = await session.execute(statement)
            rows = result.all()
            
            retrieved_context = []
            for row in rows:
                mem = row[0]
                distance = row[1]
                
                # 3. THE BYSTANDER FIX: Only reinforce if mathematically similar (< 0.5)
                if distance < 0.5:
                    mem.access_count += 1
                    session.add(mem)
                    
                retrieved_context.append(f"{mem.message} (Imp: {mem.importance_score:.1f}, Acc: {mem.access_count}, Dist: {distance:.2f})")
            
            await session.commit()
            
        ai_response = f"I processed your thought and reinforced relevant pathways."
        return {
            "status": "success", 
            "reply": ai_response, 
            "retrieved_memories": retrieved_context
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dream")
async def dream_phase():
    '''
    Generational Garbage Collection.
    Promotes critical memories, prunes forgotten trivia, respects Age.
    '''
    PRUNE_AGE_THRESHOLD = datetime.timedelta(minutes=5) 
    now = datetime.datetime.utcnow()
    
    async with async_session() as session:
        statement = select(WorkingMemory)
        result = await session.execute(statement)
        memories = result.scalars().all()
        
        promoted = 0
        pruned = 0
        retained = 0
        
        for mem in memories:
            age = now - mem.timestamp
            
            # Promotion Rule
            if mem.importance_score >= 0.8 or mem.access_count >= 5:
                long_term = SemanticMemory(
                    user_id=mem.user_id,
                    fact=mem.message,
                    embedding=mem.embedding
                )
                session.add(long_term)
                await session.delete(mem)
                promoted += 1
                
            # Pruning Rule (Must be old enough!)
            elif mem.importance_score < 0.3 and mem.access_count < 2 and age > PRUNE_AGE_THRESHOLD:
                await session.delete(mem)
                pruned += 1
                
            else:
                retained += 1
                
        await session.commit()
        
    return {
        "status": "dream_complete",
        "summary": f"Promoted: {promoted}, Pruned: {pruned}, Retained: {retained}"
    }

@app.get("/health")
async def health_check():
    return {"status": "alive", "service": "atunbi-skeleton", "brain": "connected"}
