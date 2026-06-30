import os
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# The Environment Bridge
# In the cloud, GitHub injects these. Locally, it falls back to docker-compose.
DB_USER = os.getenv("DB_USER", "atunbi")
DB_PASSWORD = os.getenv("DB_PASSWORD", "atunbi_secret")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_NAME = os.getenv("DB_NAME", "atunbi_memory")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_async_engine(DATABASE_URL, echo=True)

async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db():
    async with engine.begin() as conn:
        # Enable the pgvector extension in Postgres
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        # Create the tables based on our SQLModel classes
        await conn.run_sync(SQLModel.metadata.create_all)
