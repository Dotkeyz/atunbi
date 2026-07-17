"""
Central configuration — all environment variables in one place.
Import from here instead of calling os.getenv() directly.
"""
import os
from dotenv import load_dotenv
load_dotenv()

# JWT
_SECRET = os.getenv("SECRET_KEY")
if _SECRET:
    SECRET_KEY = _SECRET
elif os.getenv("ECS_HOST"):
    # Running on ECS — SECRET_KEY must come from GitHub Secrets
    raise RuntimeError("SECRET_KEY must be set in production. Add it to GitHub Secrets.")
else:
    SECRET_KEY = "alibaba-qwen-secret-hackathon-key-2026!!"  # local dev only
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

# Internal service-to-service auth (Function Compute → dream endpoint)
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", SECRET_KEY)

# Database
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_NAME = os.getenv("DB_NAME", "atunbi_memory")
DB_USER = os.getenv("DB_USER", "atunbi")
DB_PASSWORD = os.getenv("DB_PASSWORD", "atunbi_secret")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Alibaba Cloud Core
ALIBABA_ACCESS_KEY_ID = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
ALIBABA_ACCESS_KEY_SECRET = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")

# DashScope (Qwen LLM + Paraformer ASR)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

# EventBridge
EVENTBRIDGE_ENDPOINT = os.getenv("EVENTBRIDGE_ENDPOINT", "eventbridge.eu-west-1.aliyuncs.com")
EVENTBRIDGE_BUS_NAME = os.getenv("EVENTBRIDGE_BUS_NAME", "atunbi-memory-bus")

# OSS (Object Storage)
OSS_BUCKET = os.getenv("OSS_BUCKET", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "")
OSS_REGION = os.getenv("OSS_REGION", "eu-west-1")
# OSS uses same credentials as Alibaba Cloud core if not set separately
OSS_ACCESS_KEY = os.getenv("OSS_ACCESS_KEY_ID") or os.getenv("OSS_ACCESS_KEY") or ALIBABA_ACCESS_KEY_ID
OSS_ACCESS_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET") or os.getenv("OSS_ACCESS_SECRET") or ALIBABA_ACCESS_KEY_SECRET
