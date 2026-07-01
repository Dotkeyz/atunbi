from fastapi import FastAPI
from contextlib import asynccontextmanager
from database import init_db
from api.routes import auth, chat, dream, config

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🧠 Booting up Atunbi... Initializing Cognitive Schema...")
    await init_db()
    print("✅ Database tables created. Atunbi is awake.")
    yield

app = FastAPI(title="Atunbi Cognitive Architecture", lifespan=lifespan)

app.include_router(auth.router, prefix="/auth")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(dream.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "alive", "service": "atunbi-skeleton", "brain": "connected"}
