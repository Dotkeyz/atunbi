"""
Agent Tool Manifest — what users can ask Atunbi to do.

Tool definitions live in core.tool_registry (single source of truth).
This module re-exports the chat-facing tools for use in the agent UI.
"""

from core.tool_registry import get_chat_tools


def _how_to_use(name: str) -> str:
    """Human-readable instructions for each tool."""
    return {
        "search_memory": "Tell me what you want to find and I'll search across all your conversations, extracted facts, and past summaries.",
        "get_memory_stats": "Ask me 'how's my memory doing?' or 'show my memory stats'.",
        "trigger_dream_phase": "Ask me to 'consolidate my memories' or 'run the dream phase'.",
        "upload_file": "Just drop a file or tell me what you want to upload.",
        "store_memory": "Tell me 'remember this: ...' and I'll save it.",
        "delete_memory": "Ask me to 'forget memory #42' to remove it.",
        "update_memory": "Tell me 'correct memory #42 to say ...' to update it.",
        "list_semantic_facts": "Ask me 'what do you know about me?' to see extracted facts.",
        "get_profile": "Ask me 'who am I?' or 'what do you know about me?'",
    }.get(name, f"Ask me to '{name.replace('_', ' ')}'.")


def _endpoint(name: str) -> str:
    """API endpoint for each tool."""
    return {
        "search_memory": "/api/v1/chat/stream",
        "get_memory_stats": "/api/v1/stats",
        "trigger_dream_phase": "/api/v1/dream",
        "upload_file": "/api/v1/ingest",
        "store_memory": "/api/v1/chat/stream",
        "delete_memory": "/api/v1/tools",
        "update_memory": "/api/v1/tools",
        "list_semantic_facts": "/api/v1/stats",
        "get_profile": "/api/v1/chat/stream",
    }.get(name, "/api/v1/tools")


# Chat-facing tools exposed to users
CHAT_TOOLS = [
    {
        "name": t.name,
        "description": t.description,
        "how_to_use": _how_to_use(t.name),
        "endpoint": _endpoint(t.name),
    }
    for t in get_chat_tools()
]
