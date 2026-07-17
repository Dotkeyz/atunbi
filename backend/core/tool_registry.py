"""
Tool Registry — Single source of truth for all Atunbi tools.

16 tools, 4 categories. Each tool is defined once; the registry feeds three
consumers via filtering functions at the bottom of this file.

Consumers:
  agentic loop  — get_tools_as_openai_functions() → OpenAI native function calling
  MCP server    — get_mcp_tools() → stdio + SSE transport
  chat agent    — get_chat_tools() → lifecycle + management + ingestion
"""

from dataclasses import dataclass, field


@dataclass
class Tool:
    name: str
    description: str
    category: str              # retrieval | lifecycle | management | ingestion
    internal_only: bool = False  # True = agentic loop only, hidden from MCP
    parameters: dict[str, dict] = field(default_factory=dict)


TOOLS: dict[str, Tool] = {}


def _register(tool: Tool) -> Tool:
    TOOLS[tool.name] = tool
    return tool


# Retrieval tools — called by agentic loop in registration order

_register(Tool(name="get_profile",
    description="Load entity graph overview: all people, organizations, technologies, "
                "and projects the user is connected to. Use FIRST when the user asks "
                "'who am I', 'what do you know about me', or any recall question. "
                "Always follow with search_graph to explore specific entities.",
    category="retrieval",
    parameters={},
))

# Memory search

_register(Tool(name="search_memory",
    description="Hybrid search across all memory tiers and conversations. "
                "Use for factual recall: 'what did we discuss about X?', "
                "'what do I use for Y?'. Returns ranked, reranked results.",
    category="retrieval",
    parameters={
        "query": {"type": "string", "description": "Multi-word search terms."},
    },
))

# Entity graph

_register(Tool(name="search_graph",
    description="Multi-hop entity graph traversal starting from a NAMED entity "
                "(a person, place, company, tool, or skill — NOT a pronoun like 'me' or 'you'). "
                "Reveals hidden connections the user didn't ask about. Always run after "
                "search_memory or get_profile. If empty, try a different entity or call search_gaps.",
    category="retrieval",
    parameters={
        "query": {"type": "string", "description": "A named entity to start traversal from (e.g. 'Ngozi', 'Paystack', 'Go')."},
    },
))

_register(Tool(name="search_gaps",
    description="Find structural gaps in the entity graph: entities that share "
                "a common neighbor but have never been discussed together. "
                "Use after get_profile or when search_graph returns empty.",
    category="retrieval", internal_only=True,
    parameters={},
))

# Conversation context

_register(Tool(name="list_files",
    description="List files uploaded in the current conversation. Use when the user "
                "refers to a file without naming it. Returns filename, size, and type.",
    category="retrieval",
    parameters={},
))

_register(Tool(name="get_recent",
    description="Last N messages in the current conversation. Use for session "
                "continuity when the user references something said earlier.",
    category="retrieval", internal_only=True,
    parameters={},
))

_register(Tool(name="get_important",
    description="High-importance messages from the current conversation. "
                "Use for significant decisions or revelations from this session.",
    category="retrieval", internal_only=True,
    parameters={},
))

# Memory management

_register(Tool(name="expand_memory",
    description="Load full content of a previously summarized memory. "
                "Use when user asks for more detail about something in context.",
    category="retrieval", internal_only=True,
    parameters={
        "memory_id": {"type": "integer", "description": "Memory ID from context."},
    },
))

_register(Tool(name="forget_memory",
    description="Remove memories matching a keyword query. "
                "Extract the exact entity, topic, or phrase the user wants to forget — "
                "never pass pronouns like 'that' or 'it'. "
                "Example: user says 'forget what I said about Kafka' → query='Kafka'.",
    category="retrieval", internal_only=True,
    parameters={
        "query": {"type": "string", "description": "Exact keyword/entity/topic to forget (NOT pronouns like 'that', 'it')."},
    },
))

# Loop control

_register(Tool(name="finish",
    description="Stop gathering context and generate the final response. "
                "Only call after both memory search and graph traversal are complete. "
                "Never finish directly after search_memory.",
    category="retrieval", internal_only=True,
    parameters={},
))


_register(Tool(name="get_memory_stats",
    description="Full memory breakdown: working/episodic/semantic counts, "
                "lifecycle states, average importance, conversation count, "
                "entity graph size.",
    category="lifecycle",
    parameters={},
))

_register(Tool(name="list_semantic_facts",
    description="Browse permanent facts extracted from past conversations. "
                "The user's distilled long-term knowledge that survives pruning.",
    category="lifecycle",
    parameters={
        "limit": {"type": "integer", "description": "Max facts (default: 20)", "default": 20},
    },
))

_register(Tool(name="trigger_dream_phase",
    description="Run memory consolidation: prune low-value noise, summarize "
                "old conversations into EpisodicMemory, extract permanent facts "
                "into SemanticMemory.",
    category="lifecycle",
    parameters={},
))


_register(Tool(name="store_memory",
    description="Inject a new memory into WorkingMemory for later recall.",
    category="management",
    parameters={
        "content": {"type": "string", "description": "Text content to store."},
    },
))

_register(Tool(name="delete_memory",
    description="Permanently remove a memory by ID.",
    category="management",
    parameters={
        "memory_id": {"type": "integer", "description": "Memory ID to delete."},
    },
))

_register(Tool(name="update_memory",
    description="Correct a memory's content while preserving its history.",
    category="management",
    parameters={
        "memory_id": {"type": "integer", "description": "Memory ID to update."},
        "content": {"type": "string", "description": "New corrected content."},
    },
))


_register(Tool(name="upload_file",
    description="Ingest audio, video, images, PDFs, or text into memory. "
                "Audio transcribed, video analyzed, PDFs read, text chunked "
                "and embedded.",
    category="ingestion",
    parameters={
        "filename": {"type": "string", "description": "Name of the uploaded file."},
    },
))


def get_agentic_tools() -> list[Tool]:
    """All retrieval-category tools (9: the agentic loop's tool set)."""
    return [t for t in TOOLS.values() if t.category == "retrieval"]


def get_mcp_tools() -> list[Tool]:
    """Tools exposed to external MCP clients (10: non-internal_only)."""
    return [t for t in TOOLS.values() if not t.internal_only]


def get_chat_tools() -> list[Tool]:
    """Tools the chat agent can present to users (7: lifecycle + management + ingestion)."""
    return [t for t in TOOLS.values() if t.category in ("lifecycle", "management", "ingestion")]


def get_tools_as_openai_functions() -> list[dict]:
    """Convert agentic tools to OpenAI native function calling format.

    Returns the standard 'tools' array for chat.completions.create().
    Each tool's name, description, and parameters become a function
    definition the model is constrained to call — zero parse failures.
    """
    result = []
    for tool in get_agentic_tools():
        properties = {}
        required = []
        for pname, pdef in tool.parameters.items():
            properties[pname] = {
                "type": pdef["type"],
                "description": pdef.get("description", ""),
            }
            if "default" not in pdef:
                required.append(pname)

        func_def = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {"type": "object", "properties": properties},
            },
        }
        if required:
            func_def["function"]["parameters"]["required"] = required
        result.append(func_def)
    return result

