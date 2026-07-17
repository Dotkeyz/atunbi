from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models.models import SystemConfig

async def get_config(db: AsyncSession):
    result = await db.execute(select(SystemConfig))
    config = result.scalars().first()
    if config is None:
        config = SystemConfig()
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config

async def update_config(db: AsyncSession, config: SystemConfig):
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config
