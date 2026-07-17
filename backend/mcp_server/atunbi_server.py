"""
Atunbi MCP Server — exposes memory tools to AI models via Model Context Protocol.

Tool definitions are sourced from core.tool_registry — the single source of truth.
Adding a tool to the registry automatically exposes it here.

Usage (stdio, for local MCP clients):
  python -m mcp_server.atunbi_server

MCP client config (claude_desktop_config.json / cursor mcp.json):
  {
    "mcpServers": {
      "atunbi": {
        "command": "python",
        "args": ["-m", "mcp_server.atunbi_server"],
        "cwd": "/path/to/atunbi/backend"
      }
    }
  }
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from sqlmodel import select
from database import async_session
from repositories import memory_repo, config_repo, entity_repo
from services.qwen_service import get_embedding, score_message
from services.dream_service import run_dream_phase
from models import WorkingMemory, SemanticMemory
from core.tool_registry import TOOLS, get_mcp_tools


server = Server("atunbi-memory")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Auto-generate MCP tool schemas from the registry."""
    mcp_tools = []
    for tool_def in get_mcp_tools():
        schema: dict = {
            "type": "object",
            "properties": {
                **{
                    pname: {"type": pdef["type"], "description": pdef.get("description", "")}
                    for pname, pdef in tool_def.parameters.items()
                },
                "user_id": {"type": "integer", "description": "User ID (default: 1)", "default": 1},
            },
        }
        required = [pname for pname in tool_def.parameters if "default" not in tool_def.parameters.get(pname, {})]
        if required:
            schema["required"] = required
        
        mcp_tools.append(Tool(
            name=tool_def.name,
            description=tool_def.description,
            inputSchema=schema,
        ))
    return mcp_tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch tool calls using the registry as reference. Each tool maps to a handler below."""
    user_id = arguments.get("user_id", 1)
    
    handlers = {
        "search_memory": _handle_search_memory,
        "get_profile": _handle_get_profile,
        "get_memory_stats": _handle_get_memory_stats,
        "list_semantic_facts": _handle_list_semantic_facts,
        "trigger_dream_phase": _handle_trigger_dream_phase,
        "store_memory": _handle_store_memory,
        "delete_memory": _handle_delete_memory,
        "update_memory": _handle_update_memory,
    }
    
    # Registry validation — only execute tools that exist in the registry
    if name not in TOOLS:
        known = ", ".join(TOOLS.keys())
        return [TextContent(type="text", text=f"Unknown tool: {name}. Known tools: {known}")]
    
    if TOOLS[name].internal_only:
        return [TextContent(type="text", text=f"Tool '{name}' is internal-only and not available via MCP.")]
    
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=f"Tool '{name}' is registered but has no MCP handler yet.")]
    
    try:
        return await handler(arguments, user_id)
    except Exception as e:
        return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]


# Tool handlers

async def _handle_search_memory(args: dict, user_id: int) -> list[TextContent]:
    query = args["query"]
    async with async_session() as db:
        embedding = await get_embedding(query)
        rows = await memory_repo.hybrid_search(db, user_id, embedding, query)
        results = []
        for row in rows[:10]:
            mem = row[0]
            if hasattr(mem, 'fact'):
                text, kind = mem.fact, "semantic"
            elif hasattr(mem, 'summary'):
                text, kind = mem.summary, "episodic"
            else:
                text, kind = mem.message, "working"
            results.append(f"[{kind}] {text[:300]}")
        if not results:
            return [TextContent(type="text", text="No matching memories found.")]
        return [TextContent(type="text", text="\n\n".join(results))]


async def _handle_get_profile(args: dict, user_id: int) -> list[TextContent]:
    async with async_session() as db:
        summary = await entity_repo.get_entity_summary(db, user_id)
        if not summary:
            return [TextContent(type="text", text="No entity graph built yet. Start a conversation to build connections.")]
        total = sum(len(v) for v in summary.values())
        lines = [f"Entity graph: {total} entities across {len(summary)} types"]
        for etype, names in summary.items():
            lines.append(f"  {etype}: {', '.join(names[:8])}{' +' + str(len(names)-8) if len(names) > 8 else ''}")
        return [TextContent(type="text", text="\n".join(lines))]


async def _handle_get_memory_stats(args: dict, user_id: int) -> list[TextContent]:
    async with async_session() as db:
        config = await config_repo.get_config(db)
        stats = await memory_repo.get_memory_stats(db, user_id, config)
        lines = [
            f"Working: {stats['working_memory']}",
            f"Episodic: {stats['episodic_memory']}",
            f"Semantic: {stats['semantic_memory']}",
            f"Conversations: {stats['conversations']}",
            f"Lifecycle: Active={stats['lifecycle']['active']} Inactive={stats['lifecycle']['inactive']} Prune={stats['lifecycle']['prune_candidates']} Archive={stats['lifecycle']['archive_ready']}",
            f"Avg Importance: {stats['average_importance']}",
        ]
        return [TextContent(type="text", text="\n".join(lines))]


async def _handle_list_semantic_facts(args: dict, user_id: int) -> list[TextContent]:
    limit = args.get("limit", 20)
    async with async_session() as db:
        facts = (await db.execute(
            select(SemanticMemory).where(SemanticMemory.user_id == user_id).limit(limit)
        )).scalars().all()
        if not facts:
            return [TextContent(type="text", text="No facts yet. Trigger dream_phase after conversations age.")]
        return [TextContent(type="text", text="\n".join(f"- {f.fact}" for f in facts))]


async def _handle_trigger_dream_phase(args: dict, user_id: int) -> list[TextContent]:
    async with async_session() as db:
        result = await run_dream_phase(db, user_id)
        return [TextContent(type="text", text=f"Dream complete: {result['summary']}")]


async def _handle_store_memory(args: dict, user_id: int) -> list[TextContent]:
    content = args["content"]
    async with async_session() as db:
        embedding = await get_embedding(content)
        importance, emotion = await score_message(content)
        mem = WorkingMemory(
            user_id=user_id, message=content, role="user",
            conversation_id=str(uuid.uuid4()),
            embedding=embedding, importance_score=importance, emotional_valence=emotion,
        )
        await memory_repo.save_working_memory(db, mem)
        return [TextContent(type="text", text=f"Stored (id={mem.id}, importance={importance:.2f}).")]


async def _handle_delete_memory(args: dict, user_id: int) -> list[TextContent]:
    memory_id = args["memory_id"]
    async with async_session() as db:
        deleted = await memory_repo.delete_memory_by_id(db, memory_id, user_id)
        if deleted:
            await db.commit()
            return [TextContent(type="text", text=f"Memory {memory_id} deleted.")]
        return [TextContent(type="text", text=f"Memory {memory_id} not found or not owned by user {user_id}.")]


async def _handle_update_memory(args: dict, user_id: int) -> list[TextContent]:
    memory_id = args["memory_id"]
    content = args["content"]
    async with async_session() as db:
        updated = await memory_repo.update_memory_content(db, memory_id, user_id, content)
        if updated:
            await db.commit()
            return [TextContent(type="text", text=f"Memory {memory_id} updated.")]
        return [TextContent(type="text", text=f"Memory {memory_id} not found or not owned by user {user_id}.")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(server_name="atunbi"),
        )


if __name__ == "__main__":
    asyncio.run(main())


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(server_name="atunbi"),
        )


if __name__ == "__main__":
    asyncio.run(main())
