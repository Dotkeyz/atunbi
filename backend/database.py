from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# The connection string for our local Docker Postgres
DATABASE_URL = "postgresql+asyncpg://atunbi:atunbi_secret@localhost:5433/atunbi_memory"

# The Engine: This is the connection pool (HikariCP equivalent)
engine = create_async_engine(DATABASE_URL, echo=True)

# The Session Factory: Creates a new database session for each request
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db():
    async with engine.begin() as conn:
        # Enable the pgvector extension in Postgres
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        # Create the tables based on our SQLModel classes
        await conn.run_sync(SQLModel.metadata.create_all)
