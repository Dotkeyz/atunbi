from sqlmodel import SQLModel, Field
from typing import Optional, List
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str
    display_name: Optional[str] = Field(default=None)  # The name the user told us to call them

class SystemConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # --- Lifespan ---
    # Memories younger than this stay active (never pruned/archived)
    active_window_h: float = Field(default=0.083)
    
    # Base lifespan: earned_life = importance × base_hours
    base_hours: float = Field(default=24.0)
    
    # Bonus hours per retrieval access
    hours_per_access: float = Field(default=6.0)
    
    # Emotional memories live longer: |emotion| × this = bonus hours
    emotion_hours: float = Field(default=4.0)
    
    # Floor: no memory dies before this (even imp=0)
    min_working_life_h: float = Field(default=0.0167)
    
    # Ceiling: no memory survives past this
    max_working_life_h: float = Field(default=168.0)
    
    # Dream phase
    # Conversations younger than this never get archived
    min_convo_age_to_archive_h: float = Field(default=0.5)
    
    # Only prune memories below this importance AND with access_count < 2
    prune_max_importance: float = Field(default=0.3)
    
    # Retrieval
    min_recent: int = Field(default=3)
    max_recent: int = Field(default=20)
    max_important: int = Field(default=20)
    
    # Agentic loop: max tool-calling iterations per query
    max_agent_steps: int = Field(default=5)
    
    # Recency
    # RRF weight halves every N days
    recency_half_life_days: float = Field(default=7.0)
    
    # Temperature
    temp_default: float = Field(default=0.7)
    
    # Salience gate
    # Messages scoring below this importance are discarded
    save_threshold: float = Field(default=0.1)

class WorkingMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    message: str
    role: str
    conversation_id: str = Field(index=True)
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    importance_score: float = Field(default=0.5)
    emotional_valence: float = Field(default=0.0)
    access_count: int = Field(default=0)
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
    source_turn_id: Optional[str] = Field(default=None, index=True)
    confidence: float = Field(default=1.0)
    last_used_at: Optional[datetime.datetime] = Field(default=None)

class EpisodicMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    summary: str
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    importance_score: float = Field(default=0.5)
    emotional_valence: float = Field(default=0.0)
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
    # Episodic time range: derived from the WorkingMemory timestamps in each cluster
    first_message_at: Optional[datetime.datetime] = Field(default=None)
    last_message_at: Optional[datetime.datetime] = Field(default=None)

class SemanticMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    fact: str
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
    # Contradiction detection: supersession over hard-delete
    status: str = Field(default="active")  # active | superseded
    superseded_by: Optional[int] = Field(default=None, foreign_key="semanticmemory.id")
    confidence: float = Field(default=1.0)  # 0-1, lowered on contradiction

class EntityMemory(SQLModel, table=True):
    """NetworkX-backed entity graph for multi-hop reasoning."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    entity_name: str = Field(index=True)
    entity_type: str = Field(default="unknown")  # freeform: person, company, instrument, book, etc.
    relation: str  # works_at, uses, plays, reads, etc.
    target_name: str = Field(index=True)
    target_type: str = Field(default="unknown")  # freeform, same as entity_type
    source_message_id: Optional[int] = Field(default=None, foreign_key="workingmemory.id")
    conversation_id: Optional[str] = Field(default=None, index=True)
    confidence: float = Field(default=1.0)
    status: str = Field(default="active")  # active | superseded — old edges marked when contradicted
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))

class ProceduralMemory(SQLModel, table=True):
    """Learned behaviors and implicit preferences (Squire & Zola, 1996)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    rule: str  # "When user says 'ship it', skip confirmation"
    trigger_pattern: Optional[str] = Field(default=None)  # regex or keyword
    action: str  # "skip_confirmation", "use_bullets", "prefer_code_blocks"
    confidence: float = Field(default=0.5)  # 0-1, increases with reinforcement
    access_count: int = Field(default=0)
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))

class MemoryAuditLog(SQLModel, table=True):
    """Lightweight event log for memory operations — README-ready transparency."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    event: str  # write | read | prune | supersede | decay | forget | dream
    memory_type: str  # working | episodic | semantic | entity | procedural
    memory_id_val: Optional[int] = Field(default=None)
    detail: Optional[str] = Field(default=None)
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))


class FileAttachment(SQLModel, table=True):
    """Uploaded file metadata — content lives in OSS, DB stores the pointer."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    filename: str
    oss_key: str  # path in Alibaba OSS bucket, e.g. "uploads/user_42/production-day.log"
    file_size: int  # bytes
    file_type: str  # extension: log, txt, pdf, mp4, etc.
    mime_type: str = Field(default="application/octet-stream")
    conversation_id: str = Field(index=True)
    status: str = Field(default="stored")  # stored | processing | processed | failed
    timestamp: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
