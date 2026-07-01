from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models.models import WorkingMemory

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
