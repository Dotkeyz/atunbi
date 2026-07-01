from pydantic import BaseModel, Field
from typing import Optional

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4)

class UserLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)

class ConfigUpdate(BaseModel):
    prune_age_hours: Optional[float] = None
    similarity_threshold: Optional[float] = None
    importance_threshold: Optional[float] = None
    episode_similarity_threshold: Optional[float] = None
