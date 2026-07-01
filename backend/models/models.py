from sqlmodel import SQLModel, Field
from typing import Optional, List
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    hashed_password: str

class SystemConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    prune_age_hours: float = Field(default=0.083)
    similarity_threshold: float = Field(default=0.5)
    importance_threshold: float = Field(default=0.8)
    episode_similarity_threshold: float = Field(default=0.3)

class WorkingMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    message: str
    role: str
    conversation_id: str = Field(index=True)
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    importance_score: float = Field(default=0.5)
    access_count: int = Field(default=0)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class EpisodicMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    summary: str
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    importance_score: float = Field(default=0.5)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class SemanticMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    fact: str
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
