"""Configuration schemas."""
from typing import Optional
from pydantic import BaseModel


class ConfigUpdate(BaseModel):
    # Lifespan parameters (all values in hours)
    active_window_h: Optional[float] = None
    base_hours: Optional[float] = None
    hours_per_access: Optional[float] = None
    emotion_hours: Optional[float] = None
    min_working_life_h: Optional[float] = None
    max_working_life_h: Optional[float] = None

    # Dream phase
    min_convo_age_to_archive_h: Optional[float] = None
    prune_max_importance: Optional[float] = None

    # Retrieval limits
    min_recent: Optional[int] = None
    max_recent: Optional[int] = None
    max_important: Optional[int] = None

    # Agentic loop
    max_agent_steps: Optional[int] = None

    # Recency decay
    recency_half_life_days: Optional[float] = None

    # Adaptive temperature
    temp_default: Optional[float] = None

    # Salience gate
    save_threshold: Optional[float] = None
