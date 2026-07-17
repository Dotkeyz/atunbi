from sqlmodel.ext.asyncio.session import AsyncSession
from repositories import config_repo
from schemas.config import ConfigUpdate

async def get_config(db: AsyncSession):
    return await config_repo.get_config(db)

async def update_config(db: AsyncSession, update: ConfigUpdate):
    config = await config_repo.get_config(db)
    # Apply all non-None fields from the update to the config
    update_data = update.model_dump(exclude_none=True)
    for key, value in update_data.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return await config_repo.update_config(db, config)
