from sqlmodel import SQLModel, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from models import SystemConfig
from core.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(SQLModel.metadata.create_all)

        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_wm_embedding_hnsw "
            "ON workingmemory USING hnsw (embedding vector_cosine_ops);"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_sm_embedding_hnsw "
            "ON semanticmemory USING hnsw (embedding vector_cosine_ops);"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_em_embedding_hnsw "
            "ON episodicmemory USING hnsw (embedding vector_cosine_ops);"
        ))

    async with async_session() as session:
        result = await session.execute(select(SystemConfig))
        if not result.scalars().first():
            session.add(SystemConfig())
            await session.commit()
