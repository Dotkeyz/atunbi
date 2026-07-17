"""Agentic loop for memory retrieval using OpenAI native function calling."""
import datetime
import json
import logging
import re
from dataclasses import dataclass, field
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models import WorkingMemory, SemanticMemory, EpisodicMemory, FileAttachment
from repositories import memory_repo, entity_repo
from services.qwen_service import rerank_results, get_client
from core.tool_registry import get_tools_as_openai_functions
from core.graph import traverse_from, build_mermaid_paths, find_structural_gaps
from services.tools_service import forget_memories

logger = logging.getLogger("atunbi.agentic")

AGENTIC_SYSTEM_PROMPT = """You are Atunbi's memory retrieval agent. Call ONE tool at a time. After each result, decide the next tool or call 'finish'. Your goal is to find ALL relevant context — not just the first match.

Always check the entity graph after searching memory. Never finish directly after search_memory.

What to search for: named people, places, tools, frameworks, companies, skills, projects — entities the user mentioned or that appear in loaded context. Not pronouns.

If search_memory returns nothing: retry once with a different query. Extract an entity, broaden the terms, or use recent context.

Call list_files if the user might be referring to an uploaded file.

CRITICAL: When the user asks recall/identity questions ("who am I", "what do you know about me", "what do you remember", etc):
1. FIRST call get_profile
2. THEN call search_graph
3. THEN call finish
Skip graph traversal only for: greetings, small talk, calculations, trivia."""

AGENTIC_TOOLS = get_tools_as_openai_functions()


def _entity_rows(entities) -> list[tuple]:
    return [(e.entity_name, e.entity_type, e.relation, e.target_name, e.target_type, e.confidence) for e in entities]

def _add_entity_facts(entity_rows: list[tuple], context_text: list[str], seen: set, max_facts: int = 6):
    grouped: dict[str, list[str]] = {}
    for e in entity_rows:
        grouped.setdefault(e[0], []).append(f"{e[2]} {e[3]}")
    for name, facts in grouped.items():
        label = f"{name} — {', '.join(facts[:max_facts])}."
        if label not in seen:
            seen.add(label)
            context_text.insert(1, label)


@dataclass
class _LoopState:
    context: list[str] = field(default_factory=list)
    seen_messages: set = field(default_factory=set)
    seen_results: set = field(default_factory=set)
    steps: list[dict] = field(default_factory=list)
    empty_searches: int = 0
    graph_attempted: bool = False


async def _handle_search_memory(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    query = params.get("query", message)
    state.steps.append({"action": "search", "detail": query})
    raw_rows = await memory_repo.hybrid_search(db, user_id, query_vector, query, half_life_days=config.recency_half_life_days, conversation_id=conversation_id)
    if raw_rows:
        rows = await rerank_results(query, raw_rows)
    else:
        rows = []
    
    ctx_before = len(state.context)
    result = _format_tool_result(rows, "search", conversation_id, db, state.seen_messages, state.context, message)
    ctx_added = len(state.context) - ctx_before
    
    # Fallback: if reranker + dedup filters removed everything useful,
    # use the raw hybrid search top results directly. This handles cases where
    # the reranker rejects media analyses or cross-conversation facts, and
    # exact-query duplicates get skipped by the current_message dedup.
    if ctx_added == 0 and raw_rows:
        logger.info(f"[Agentic] Search added 0 items (had {len(rows)} reranked, {len(raw_rows)} raw) — falling back to raw top-5")
        # Exclude exact current-message duplicates; prioritize media analyses
        fallback = [r for r in raw_rows if getattr(r[0], 'message', '') != message]
        # Sort: media/PDF entries first (their analysis is more valuable than chat echoes)
        fallback.sort(key=lambda r: 0 if re.match(r'\[(audio|video|image|pdf):', getattr(r[0], 'message', '')) else 1)
        if not fallback:
            fallback = raw_rows[:5]
        else:
            fallback = fallback[:5]
        result = _format_tool_result(fallback, "search", conversation_id, db, state.seen_messages, state.context, message)
    
    if not rows:
        state.empty_searches += 1
    else:
        state.empty_searches = 0
    return result

async def _handle_get_profile(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    state.steps.append({"action": "profile", "detail": "Loading entity graph..."})
    summary = await entity_repo.get_entity_summary(db, user_id)
    total = sum(len(v) for v in summary.values())
    
    # Build a compact summary string for the agent context
    lines = []
    for etype, names in summary.items():
        lines.append(f"  {etype}: {', '.join(names[:8])}{' +' + str(len(names)-8) if len(names) > 8 else ''}")
    
    state.steps[-1]["detail"] = ", ".join(f"{len(v)} {k}" for k, v in summary.items())
    state.steps[-1]["preview"] = [f"{len(v)}× {k}" for k, v in sorted(summary.items(), key=lambda x: -len(x[1]))[:5]]
    
    text = f"[Entity graph: {total} entities across {len(summary)} types]\n" + "\n".join(lines) if lines else "[Entity graph: empty — start a conversation to build connections]"
    state.context.append(text)
    return text

async def _handle_get_recent(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    state.steps.append({"action": "recent", "detail": "Recent messages"})
    word_count = len(message.split())
    limit = min(max(word_count * 2, config.min_recent), config.max_recent)
    rows = await memory_repo.get_recent_conversation_messages(db, conversation_id, limit=limit)
    state.steps[-1]["preview"] = [getattr(m, 'message', str(m))[:80] for m in rows[:5]]
    return _format_tool_result(rows, "recent", conversation_id, db, state.seen_messages, state.context, message)

async def _handle_list_files(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    state.steps.append({"action": "files", "detail": "Checking uploaded files..."})
    stmt = (
        select(FileAttachment)
        .where(FileAttachment.conversation_id == conversation_id)
        .order_by(FileAttachment.timestamp.desc())
        .limit(5)
    )
    result = await db.execute(stmt)
    files = result.scalars().all()
    if not files:
        state.steps[-1]["detail"] = "No files in this conversation"
        return "[No files uploaded in this conversation]"
    lines = []
    for f in files:
        size = f"{f.file_size/1024:.1f}KB" if f.file_size >= 1024 else f"{f.file_size}B"
        lines.append(f"  {f.filename} ({size}, {f.file_type})")
    text = "[Files in this conversation]:\n" + "\n".join(lines)
    state.steps[-1]["detail"] = f"{len(files)} file(s): {', '.join(f.filename for f in files[:3])}"
    state.context.insert(0, text)
    return text

async def _handle_get_important(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    state.steps.append({"action": "important", "detail": "Key moments"})
    rows = await memory_repo.get_important_memories(db, conversation_id, limit=config.max_important)
    return _format_tool_result(rows, "important", conversation_id, db, state.seen_messages, state.context, message)

async def _handle_search_graph(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    state.graph_attempted = True
    query = params.get("query", message)
    state.steps.append({"action": "graph", "detail": f"Traversing from '{query}'"})
    entities = await entity_repo.get_all_entities(db, user_id)
    rows = _entity_rows(entities)
    paths = traverse_from(user_id, rows, [query], max_depth=3)
    all_entities = [{"from": e[0], "relation": e[2], "to": e[3]} for e in rows]
    state.steps[-1]["all_entities"] = all_entities

    if paths:
        state.steps[-1]["paths"] = paths
        state.steps[-1]["mermaid"] = build_mermaid_paths(paths)
        state.steps[-1]["detail"] = f"Found {len(paths)} connections"
        summaries = [f"{p['from']} {p['relation']} {p['to']}" for p in paths]
        _add_entity_facts([(p['from'], '', p['relation'], p['to'], '', 1.0) for p in paths], state.context, state.seen_messages)
        return f"[Graph traversal found {len(paths)} paths]\n" + "\n".join(f"  - {s}" for s in summaries)

    names = sorted(set(e[0] for e in rows) | set(e[3] for e in rows))
    # Resolve case-insensitive match for the error message
    query_lower = query.lower()
    resolved = next((n for n in names if n.lower() == query_lower), query)
    state.steps[-1]["detail"] = f"No connections for '{resolved}'"
    _add_entity_facts(rows, state.context, state.seen_messages, max_facts=8)
    if names:
        return f"[Graph: no paths from '{query}'. Known entities: {', '.join(names[:8])}]"
    return "[Graph: no entities in memory yet]"

async def _handle_search_gaps(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    state.graph_attempted = True
    state.steps.append({"action": "insight", "detail": "Scanning for blind spots..."})
    entities = await entity_repo.get_all_entities(db, user_id)
    rows = _entity_rows(entities)
    gaps = find_structural_gaps(rows, min_confidence=0.3)
    if gaps:
        state.steps[-1]["detail"] = f"Found {len(gaps)} blind spots"
        state.steps[-1]["entities"] = [g["entity_a"] for g in gaps] + [g["entity_b"] for g in gaps]
        for g in gaps:
            insight = f"[Blind Spot]: {g['entity_a']} and {g['entity_b']} are both connected to {g['shared_neighbor']} but have never been discussed together."
            if insight not in state.seen_messages:
                state.seen_messages.add(insight)
                state.context.append(insight)
        summaries = [f"{g['entity_a']} + {g['entity_b']} — both linked to {g['shared_neighbor']}" for g in gaps]
        return f"[Found {len(gaps)} blind spots]\n" + "\n".join(f"  • {s}" for s in summaries)
    state.steps[-1]["detail"] = "No blind spots found"
    return "[No structural gaps found]"

async def _handle_forget_memory(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    query = params.get("query", "").strip()
    if query.lower() in {"that", "it", "this", "the", "a", "an", ""} or len(query) <= 2:
        state.steps.append({"action": "forget", "detail": f"Skipped: '{query}' too vague"})
        return "[Forget skipped — query too vague]"
    state.steps.append({"action": "forget", "detail": f"Removing: {query}"})
    n = await forget_memories(db, user_id, query)
    state.steps[-1]["detail"] = f"Removed {n} memories"
    return f"[Forgot {n} memories matching '{query}']"

async def _handle_expand_memory(db, user_id, params, state: _LoopState, message: str, query_vector, conversation_id: str, config) -> str:
    mem_id = params.get("memory_id", 0)
    state.steps.append({"action": "expand", "detail": f"Loading memory #{mem_id}"})
    expanded = await _expand_memory(db, mem_id, user_id)
    if "not found" not in expanded and expanded not in state.seen_messages:
        state.seen_messages.add(expanded)
        state.context.append(expanded)
    return expanded


TOOL_HANDLERS = {
    "search_memory": _handle_search_memory,
    "get_profile": _handle_get_profile,
    "get_recent": _handle_get_recent,
    "get_important": _handle_get_important,
    "list_files": _handle_list_files,
    "search_graph": _handle_search_graph,
    "search_gaps": _handle_search_gaps,
    "forget_memory": _handle_forget_memory,
    "expand_memory": _handle_expand_memory,
}


async def _inject_forgotten_markers(db, user_id: int, context: list[str]):
    try:
        result = await db.execute(
            select(SemanticMemory).where(
                SemanticMemory.user_id == user_id,
                SemanticMemory.fact.like("[Forgotten: %"),
                SemanticMemory.status == "active",
            )
        )
        facts = result.scalars().all()
        if not facts:
            return
        topics = []
        all_targets: set[str] = set()
        for f in facts:
            fact_text = f.fact.replace("[Forgotten: ", "").rstrip("]")
            if " | " in fact_text:
                topic, targets_str = fact_text.split(" | ", 1)
                topics.append(topic.strip())
                all_targets.update(t.strip().lower() for t in targets_str.split(","))
            else:
                topics.append(fact_text.strip())
        topics = [t for t in topics if t]
        if not topics:
            return
        marker = (
            f"[IMPORTANT: User ordered you to forget: {', '.join(topics)}. "
            f"You have ZERO knowledge about {'this' if len(topics)==1 else 'these topics'}. "
            f"When asked, say you don't have that information. "
            f"Do NOT list or describe any facts about {'it' if len(topics)==1 else 'them'} "
            f"— even if mentioned in context below. Those are stale.]"
        )
        context.insert(0, marker)
        filtered = [item for item in context[1:] if not any(
            t in item.lower() for t in topics | all_targets
        )]
        if len(filtered) < len(context) - 1:
            context[:] = [context[0]] + filtered
    except Exception:
        pass


async def _attach_all_entities(db, user_id: int, steps: list[dict]):
    try:
        entities = await entity_repo.get_all_entities(db, user_id)
        if not entities or not steps:
            return
        data = [{"from": e.entity_name, "relation": e.relation, "to": e.target_name} for e in entities]
        steps[-1]["all_entities"] = data
        for s in reversed(steps):
            if s.get("action") == "graph" and s is not steps[-1]:
                s["all_entities"] = data
                break
    except Exception:
        pass


async def agentic_retrieve(db: AsyncSession, user_id: int, message: str, query_vector: list[float], conversation_id: str, config, recent_context: str = "") -> tuple[list[str], list[dict]]:
    client = get_client()
    state = _LoopState()
    max_steps = getattr(config, 'max_agent_steps', 5) or 5
    
    today = datetime.datetime.now(datetime.UTC).strftime('%A, %B %d, %Y')
    user_prompt = f"Today is {today}."
    if recent_context:
        user_prompt += f"\n\nRecent conversation:\n{recent_context}"
    user_prompt += f"\n\nUser message: \"{message}\"\n\nDecide your first tool call."
    
    conversation = [
        {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]
    
    for iteration in range(max_steps):
        try:
            response = await client.chat.completions.create(
                model="qwen-turbo",
                messages=conversation,
                tools=AGENTIC_TOOLS,
                tool_choice="required",
                temperature=0.1,
            )
            tool_calls = response.choices[0].message.tool_calls
            if not tool_calls:
                break
            tool_call = tool_calls[0]
            action = tool_call.function.name
            params = json.loads(tool_call.function.arguments)
        except Exception as e:
            logger.warning(f"[Agentic Loop] Error at step {iteration+1}: {e}")
            break
        
        logger.info(f"[Agentic Loop] Step {iteration+1}/{max_steps}: {action}")
        
        if action == "finish":
            productive_steps = sum(1 for s in state.steps if s["action"] not in ("rewrite", "done", "context"))
            if productive_steps < 3:
                logger.info(f"[Agentic] Too few steps ({productive_steps}) — forcing another iteration")
                conversation.append({"role": "user", "content": "You finished too early. Search more thoroughly. Try different queries."})
                state.steps.append({"action": "done", "detail": f"Too few ({productive_steps}) — retrying"})
                continue
            state.steps.append({"action": "done", "detail": "Ready"})
            break
        
        handler = TOOL_HANDLERS.get(action)
        if handler is None:
            logger.warning(f"[Agentic Loop] Unknown tool: {action}")
            break
        
        result_text = await handler(db, user_id, params, state, message, query_vector, conversation_id, config)
        
        if result_text is None:
            result_text = f"[Tool '{action}' executed]"
        
        fingerprint = hash(result_text)
        if fingerprint in state.seen_results:
            state.steps.append({"action": "done", "detail": "Duplicate — stopping"})
            break
        state.seen_results.add(fingerprint)
        
        if len(state.context) >= 15 and state.graph_attempted:
            state.steps.append({"action": "done", "detail": "Enough context — stopping"})
            break
        
        if state.empty_searches >= 2:
            state.steps.append({"action": "done", "detail": "No results after repeated searches"})
            break
        
        conversation.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": tool_call.id,
                "type": "function",
                "function": {"name": action, "arguments": json.dumps(params)}
            }]
        })
        conversation.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result_text
        })
    
    await db.commit()
    await _inject_forgotten_markers(db, user_id, state.context)
    await _attach_all_entities(db, user_id, state.steps)
    
    return state.context, state.steps


def _format_tool_result(rows, tool_label: str, conversation_id: str, db, seen_messages: set, context_text: list, current_message: str) -> str:
    """Format tool results into context items and return a summary for the agent loop."""
    summaries = []
    items = rows if isinstance(rows, list) else [(rows, 1.0)]
    
    for item in items:
        if isinstance(item, tuple) and len(item) == 2:
            mem, score = item
        else:
            mem = item
        
        if isinstance(mem, WorkingMemory):
            mem.access_count += 1
            mem.last_used_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            db.add(mem)
            mem_text = mem.message
            if tool_label == "profile":
                label = f"[About You]: {mem.message}"
            elif mem.importance_score >= 0.6:
                label = f"[{'Atunbi' if mem.role == 'assistant' else 'You'} — important]: {mem.message}"
            else:
                label = f"[{'Atunbi' if mem.role == 'assistant' else 'You'}]: {mem.message}"
        elif isinstance(mem, SemanticMemory):
            mem_text = mem.fact
            is_superseded = getattr(mem, 'status', 'active') == 'superseded'
            if is_superseded:
                label = f"[Fact — SUPERSEDED]: {mem.fact}"
            else:
                label = f"[Fact — current]: {mem.fact}"
        elif isinstance(mem, EpisodicMemory):
            mem_text = mem.summary
            label = f"[Past conversation summary]: {mem.summary}"
        else:
            continue
        
        if hasattr(mem, 'conversation_id') and mem.conversation_id != conversation_id:
            # Don't skip media/PDF entries from other conversations —
            # the user uploaded them and expects to recall them anywhere.
            if isinstance(mem, WorkingMemory):
                prefix = "Atunbi" if mem.role == "assistant" else "You"
                label = f"[{prefix} — earlier chat]: {mem.message}"
        
        if mem_text not in seen_messages and mem_text != current_message:
            seen_messages.add(mem_text)
            context_text.append(label)
            summaries.append(mem_text[:100])
    
    if not summaries:
        return f"[{tool_label} returned no results]"
    return f"[{tool_label} returned {len(summaries)} results]\n" + "\n".join(f"  - {s}" for s in summaries[:5])


async def _expand_memory(db: AsyncSession, memory_id: int, user_id: int) -> str:
    stmt = select(WorkingMemory).where(WorkingMemory.id == memory_id, WorkingMemory.user_id == user_id)
    result = await db.execute(stmt)
    mem = result.scalars().first()
    if mem:
        return f"[Memory #{memory_id} — full text]: {mem.message}"
    
    stmt = select(SemanticMemory).where(SemanticMemory.id == memory_id, SemanticMemory.user_id == user_id)
    result = await db.execute(stmt)
    mem = result.scalars().first()
    if mem:
        tag = "SUPERSEDED" if mem.status == 'superseded' else "current"
        return f"[Fact #{memory_id} — {tag}]: {mem.fact}"
    
    stmt = select(EpisodicMemory).where(EpisodicMemory.id == memory_id, EpisodicMemory.user_id == user_id)
    result = await db.execute(stmt)
    mem = result.scalars().first()
    if mem:
        return f"[Episode #{memory_id} — full summary]: {mem.summary}"
    
    return f"[Memory #{memory_id} not found]"