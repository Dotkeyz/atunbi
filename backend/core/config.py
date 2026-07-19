"""Central configuration. All environment variables read once at import time."""
import os
from dotenv import load_dotenv
load_dotenv()

# ── Authentication ──────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "alibaba-qwen-secret-hackathon-key-2026!!")  # local dev only

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", SECRET_KEY)

# ── Database ────────────────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_NAME = os.getenv("DB_NAME", "atunbi_memory")
DB_USER = os.getenv("DB_USER", "atunbi")
DB_PASSWORD = os.getenv("DB_PASSWORD", "atunbi_secret")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ── Alibaba Cloud ───────────────────────────────────────────────
ALIBABA_ACCESS_KEY_ID = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")
ALIBABA_ACCESS_KEY_SECRET = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")

# DashScope (Qwen models)
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

# EventBridge
EVENTBRIDGE_ENDPOINT = os.getenv("EVENTBRIDGE_ENDPOINT", "eventbridge.eu-west-1.aliyuncs.com")
EVENTBRIDGE_BUS_NAME = os.getenv("EVENTBRIDGE_BUS_NAME", "atunbi-memory-bus")

# OSS (Object Storage)
OSS_BUCKET = os.getenv("OSS_BUCKET", "")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "")
OSS_REGION = os.getenv("OSS_REGION", "eu-west-1")
OSS_ACCESS_KEY = os.getenv("OSS_ACCESS_KEY_ID") or ALIBABA_ACCESS_KEY_ID
OSS_ACCESS_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET") or ALIBABA_ACCESS_KEY_SECRET
