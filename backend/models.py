from sqlmodel import SQLModel, Field
from typing import Optional, List
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
import datetime

class WorkingMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    message: str
    role: str
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    # The Cognitive Fields
    importance_score: float = Field(default=0.5) # 0.0 (forgettable) to 1.0 (critical)
    access_count: int = Field(default=0)         # Reinforcement tracker
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class EpisodicMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    summary: str
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    importance_score: float = Field(default=0.5)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

class SemanticMemory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    fact: str
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
