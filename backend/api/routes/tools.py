"""Agent Tools — self-service capability discovery and invocation."""
from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import get_db, get_current_user
from models.models import User
from core.tools import CHAT_TOOLS as TOOLS
from repositories import memory_repo, config_repo
from services import tools_service
from services.dream_service import run_dream_phase
from sqlmodel.ext.asyncio.session import AsyncSession
from services.qwen_service import get_embedding

router = APIRouter(tags=["Tools"])


@router.get("/tools")
async def list_tools(current_user: User = Depends(get_current_user)):
    """List all tools the agent can use — self-service capability discovery."""
    return {"tools": TOOLS, "total": len(TOOLS)}


@router.post("/tools/call")
async def call_tool(
    tool_name: str,
    parameters: dict = {},
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Execute a tool on behalf of the agent. Returns the tool's result."""
    if tool_name == "search_memory":
        query = parameters.get("query", "")
        query_vector = await get_embedding(query)
        results = await memory_repo.hybrid_search(db, current_user.id, query_vector, query, limit=5)
        return {"results": [{"content": str(getattr(m, "message", getattr(m, "fact", getattr(m, "summary", str(m)))))[:200], "score": round(1.0 - s, 3)} for m, s in results]}

    elif tool_name == "get_memory_stats":
        config = await config_repo.get_config(db)
        return await memory_repo.get_memory_stats(db, current_user.id, config)

    elif tool_name == "trigger_dream_phase":
        return await run_dream_phase(db, current_user.id)

    elif tool_name == "get_config":
        config = await config_repo.get_config(db)
        return {
            "recency_half_life_days": config.recency_half_life_days,
            "active_window_h": config.active_window_h,
            "max_recent": config.max_recent,
            "max_important": config.max_important,
            "temp_default": config.temp_default
        }
    
    elif tool_name == "forget":
        query = parameters.get("query", "")
        if not query:
            raise HTTPException(status_code=400, detail="query parameter required")
        forgotten = await tools_service.forget_memories(db, current_user.id, query)
        return {"forgotten": forgotten, "query": query}
    
    elif tool_name == "list_semantic_facts":
        limit = parameters.get("limit", 20)
        facts = await tools_service.list_active_facts(db, current_user.id, limit)
        return {"facts": facts, "count": len(facts)}
    
    elif tool_name == "delete_memory":
        memory_id = parameters.get("memory_id", 0)
        if not memory_id:
            raise HTTPException(status_code=400, detail="memory_id parameter required")
        deleted = await memory_repo.delete_memory_by_id(db, memory_id, current_user.id)
        return {"deleted": deleted, "memory_id": memory_id}
    
    elif tool_name == "update_memory":
        memory_id = parameters.get("memory_id", 0)
        content = parameters.get("content", "")
        if not memory_id or not content:
            raise HTTPException(status_code=400, detail="memory_id and content required")
        updated = await memory_repo.update_memory_content(db, memory_id, current_user.id, content)
        return {"updated": updated is not None, "memory_id": memory_id}

    elif tool_name == "list_conversations":
        clusters = await memory_repo.get_conversation_clusters(db, current_user.id)
        return {"conversations": [{"id": c[0].conversation_id, "messages": len(c)} for c in clusters[-5:]]}

    raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")

