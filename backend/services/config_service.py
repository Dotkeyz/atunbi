from sqlmodel.ext.asyncio.session import AsyncSession
from repositories import config_repo
from schemas.schemas import ConfigUpdate

async def get_config(db: AsyncSession):
    return await config_repo.get_config(db)

async def update_config(db: AsyncSession, update: ConfigUpdate):
    config = await config_repo.get_config(db)
    if update.prune_age_hours is not None: config.prune_age_hours = update.prune_age_hours
    if update.similarity_threshold is not None: config.similarity_threshold = update.similarity_threshold
    if update.importance_threshold is not None: config.importance_threshold = update.importance_threshold
    if update.episode_similarity_threshold is not None: config.episode_similarity_threshold = update.episode_similarity_threshold
    return await config_repo.update_config(db, config)
