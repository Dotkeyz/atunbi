from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
from contextlib import asynccontextmanager
import logging
from database import init_db
from api.routes import auth, history, chat, dream, config, stats, ingestion, tools
from mcp_server.sse_server import router as mcp_router

# Structured logging — INFO visible in terminal, DEBUG hidden
logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
logger = logging.getLogger("atunbi")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Atunbi starting up...")
    await init_db()
    logger.info("Ready.")
    yield

app = FastAPI(title="Atunbi", docs_url="/api/docs", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth")
app.include_router(history.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(dream.router, prefix="/api/v1")
app.include_router(config.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(ingestion.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
if mcp_router is not None:
    app.include_router(mcp_router, include_in_schema=False)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
