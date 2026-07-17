"""Memory service — chat processing pipeline, entity extraction, context assembly."""
import asyncio
import datetime
import hashlib
import json
import logging
import re
import time
import uuid
from sqlmodel.ext.asyncio.session import AsyncSession
from models import WorkingMemory, EntityMemory
from repositories import memory_repo, config_repo, entity_repo
from services.qwen_service import (
    get_embedding, score_message, generate_stream, get_client,
    ATUNBI_BASE_PROMPT,
)
from services.extraction import extract_entities
from services.agentic_loop import agentic_retrieve
from services.dream_service import get_stats
from services.forget import handle_forget, handle_forget_the_forget
from repositories.audit_repo import log_audit_event
from core.metrics import token_naive_total, token_actual_total
from core.events import event_bus
from core.cache import embedding_cache, scoring_cache
from core.graph import invalidate_graph

logger = logging.getLogger("atunbi.memory")

ATUNBI_PROMPT = ATUNBI_BASE_PROMPT + "\n\nNever fabricate facts or pretend to recall something not in context."

CREATIVE_PROMPT = """You are Atunbi, a thoughtful design and exploration partner. Use the context as a springboard, not a cage. Think aloud, draw connections, explore ideas. Offer alternatives, trade-offs, and mental models. Be expansive but grounded — every suggestion should connect back to something in context or a well-known pattern. Never fabricate facts."""


def _is_creative(message: str) -> bool:
    """Simple heuristic for design/architecture/brainstorming queries."""
    msg = message.lower().strip()
    markers = [
        'design a', 'design an', 'architect', 'brainstorm',
        'how would you', 'system design', 'what if', 'trade-off',
        'tradeoff', 'alternative', 'refactor', 'restructure',
        'best practice', 'pattern for',
    ]
    return any(m in msg for m in markers)


def _message_hash(text: str) -> str:
    cleaned = re.sub(r'[^\w\s]', '', text.lower().strip())
    return hashlib.sha256(cleaned.encode()).hexdigest()[:16]


async def _query_rewrite(message: str, recent_context: str = "") -> list[str]:
    client = get_client()
    ctx_hint = f"\nRecent conversation context: {recent_context[:300]}" if recent_context else ""
    try:
        response = await client.chat.completions.create(
            model="qwen-turbo",
            messages=[
                {"role": "system", "content": "Rewrite this search query into 2-3 alternative formulations that might match different wording in stored memories. Output one per line. Keep each under 10 words. Be specific — preserve all people, places, and company names." + ctx_hint},
                {"role": "user", "content": message},
            ],
            temperature=0.3,
            max_tokens=100,
        )
        variants = [line.strip() for line in response.choices[0].message.content.strip().split('\n') if line.strip()]
        
        original_entities = set(re.findall(r'[A-Z][a-z]+', message))
        filtered = []
        for v in variants:
            variant_entities = set(re.findall(r'[A-Z][a-z]+', v))
            if original_entities and not (original_entities & variant_entities):
                logger.info(f"[Query Rewrite] Discarding variant that lost entities: '{v}'")
                continue
            filtered.append(v)
        
        return filtered[:3] if filtered else []
    except Exception:
        return []


def _hierarchical_render(context_items: list[str], now: datetime.datetime | None = None) -> list[str]:
    if now is None:
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    rendered = []
    for item in context_items:
        if item.startswith('[Fact') or item.startswith('[Entity Graph]') or item.startswith('[Blind Spot]'):
            rendered.append(item)
            continue
        if 'earlier chat' in item.lower() or 'past conversation' in item.lower():
            if len(item) > 150:
                rendered.append(item[:147] + '...')
            else:
                rendered.append(item)
        else:
            rendered.append(item)
    return rendered

def _sse_line(data: str) -> str:
    lines = data.split('\n')
    return '\n'.join(f"data: {line}" for line in lines) + '\n\n'


async def process_chat_stream(
    db: AsyncSession,
    user_id: int,
    message: str,
    conversation_id: str | None = None,
):
    t0 = time.perf_counter()
    config = await config_repo.get_config(db)

    handled, forget_response = await handle_forget(db, user_id, message)
    if handled:
        await db.commit()
        try:
            wm = WorkingMemory(
                user_id=user_id, message=message, role="user",
                conversation_id=conversation_id or str(uuid.uuid4()),
                embedding=[0.0]*1536,
                importance_score=0.5, emotional_valence=0.0,
                timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            )
            await memory_repo.save_working_memory(db, wm)
            await db.commit()
        except Exception:
            logger.warning(f"Failed to save forget echo for user {user_id}", exc_info=True)
        yield _sse_line(forget_response)
        yield _sse_line("[DONE]")
        return

    await handle_forget_the_forget(db, user_id, message)

    # Early init — entity extraction below may add notes before the
    # greeting/agentic branch initializes context_text properly.
    context_text: list[str] = []

    # Embedding + scoring
    cached_emb = embedding_cache.get(message)
    cached_score = scoring_cache.get(message)
    
    async def get_embed() -> list[float]:
        if cached_emb is not None:
            return cached_emb
        emb = await get_embedding(message)
        embedding_cache.set(message, emb)
        return emb
    
    async def get_score() -> tuple[float, float]:
        if cached_score is not None:
            return cached_score
        imp, emo = await score_message(message)
        scoring_cache.set(message, (imp, emo))
        return imp, emo
    
    query_vector, (importance, emotion) = await asyncio.gather(get_embed(), get_score())
    t1 = time.perf_counter()
    logger.info(f"[Timing] Pre-flight: {t1-t0:.2f}s")

    # Conversation ID
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    # Dedup check
    msg_hash = _message_hash(message)
    recent_memories = await memory_repo.get_recent_conversation_messages(db, conversation_id, limit=1)
    for recent in recent_memories:
        if _message_hash(recent.message) == msg_hash:
            logger.info(f"[Dedup] Skipping duplicate: '{message[:60]}...' (matches msg #{recent.id})")
            context_str = ""
            async for token in generate_stream(context_str, message):
                yield _sse_line(token)
            yield _sse_line("[DONE]")
            return

    save_threshold = getattr(config, 'save_threshold', 0.1)
    _pending_contradictions = []
    if importance < save_threshold:
        logger.info(f"[Salience Gate] Skipping (imp={importance:.2f} < {save_threshold})")
    else:
        wm = WorkingMemory(
            user_id=user_id, message=message, role="user",
            conversation_id=conversation_id, embedding=query_vector,
            importance_score=importance, emotional_valence=emotion,
            timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        await memory_repo.save_working_memory(db, wm)
        log_audit_event(db, user_id, "write", "working", wm.id, f"Saved: '{message[:80]}'")

        if importance >= 0.2 and len(message.split()) >= 3:
            try:
                prev_context = ""
                if recent_memories:
                    prev_user_msgs = [m.message for m in recent_memories if getattr(m, 'role', '') == 'user']
                    if prev_user_msgs:
                        prev_context = prev_user_msgs[-1]
                
                profile = await memory_repo.get_user_profile(db, user_id, limit=5)
                identity_hints = []
                for p in profile:
                    msg = getattr(p, 'fact', getattr(p, 'message', ''))
                    if any(w in msg.lower() for w in ['name is', 'i am', 'i live', 'i work', 'vp ', 'cto', 'engineer']):
                        if msg[:120].strip().lower() != message.strip().lower():
                            identity_hints.append(msg[:120])
                if identity_hints:
                    prev_context = (prev_context + "\n" if prev_context else "") + "User identity: " + identity_hints[0]

                old_entity_rows = await entity_repo.get_all_entities(db, user_id)
                speaker_facts: list[str] = []
                other_facts: list[str] = []

                speaker_name = ""
                m = re.search(
                    r'(?:I am|I\'m|my name is|it\'?s|this is|actually it\'?s)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
                    message, re.IGNORECASE
                )
                if m:
                    candidate = m.group(1)
                    # The prefix matched case-insensitively, but the captured
                    # name must actually start with uppercase in the message.
                    # (Without this guard, "I am travelling" would capture
                    # "travelling" as a name via the IGNORECASE flag.)
                    first_char = message[m.start(1):m.start(1)+1]
                    if first_char.isupper():
                        NON_NAMES = {
                            'planning to', 'going to', 'attending', 'not sure', 'not a', 'just a',
                            'also a', 'still a', 'now a', 'currently', 'definitely', 'probably',
                            'maybe a', 'thinking of', 'wondering', 'trying to', 'working on',
                            'leading the', 'using a', 'reporting to', 'excited about', 'looking',
                            'pretty sure', 'really not', 'very much', 'quite sure',
                            'travelling', 'traveling', 'going', 'heading', 'flying', 'driving',
                        }
                        if candidate.lower() not in NON_NAMES:
                            # Discard trailing noise words that the optional
                            # second-word capture may have picked up ("and", "the", etc.)
                            clean = candidate.split()[0]
                            if not clean.lower().endswith('ing'):
                                speaker_name = clean
                                from models import User as UserModel
                                from sqlmodel import select as sql_select
                                uresult = await db.execute(sql_select(UserModel).where(UserModel.id == user_id))
                                u = uresult.scalars().first()
                                if u and u.display_name != speaker_name:
                                    u.display_name = speaker_name
                                    await db.commit()
                                    logger.info(f"[Identity] Stored display_name='{speaker_name}' for user {user_id}")

                if not speaker_name:
                    from models import User as UserModel
                    from sqlmodel import select as sql_select
                    uresult = await db.execute(sql_select(UserModel).where(UserModel.id == user_id))
                    u = uresult.scalars().first()
                    if u and u.display_name and u.display_name not in ('not sure', 'planning to', 'automatic'):
                        speaker_name = u.display_name
                    elif u:
                        # Username fallback: ensure at least one uppercase char
                        # so _validate_entity doesn't reject it as a non-proper noun
                        speaker_name = u.username
                        if not any(c.isupper() for c in speaker_name):
                            speaker_name = speaker_name[0].upper() + speaker_name[1:] if len(speaker_name) > 1 else speaker_name.upper()

                for e in old_entity_rows:
                    fact = f"{e.entity_name} {e.relation} {e.target_name}"
                    if speaker_name and e.entity_name.lower() == speaker_name.lower():
                        speaker_facts.append(fact)
                    else:
                        other_facts.append(fact)

                entity_context_parts: list[str] = []
                if speaker_name:
                    parts = [f"The current user is {speaker_name}."]
                    if speaker_facts:
                        parts.append("Their known facts:\n" + "\n".join(speaker_facts[:15]))
                    entity_context_parts.append(" ".join(parts))
                if other_facts:
                    entity_context_parts.append(
                        f"Other known facts:\n" + "\n".join(other_facts[:25])
                    )
                entity_context = "\n\n".join(entity_context_parts)

                result = await extract_entities(message, context=prev_context, entity_context=entity_context)
                entities = result["entities"]
                model_contradictions = result["contradictions"]
                needs_clarification = result.get("needs_clarification")

                if needs_clarification and isinstance(needs_clarification, str) and needs_clarification.strip():
                    context_text.insert(0, f"[Note]: {needs_clarification.strip()}")
                    logger.info(f"[Entity Extraction] Pronoun note: {needs_clarification}")

                # Compare extracted entities with existing
                for ent in entities:
                    ename = ent.get("entity_name", "")
                    rel = ent.get("relation", "")
                    new_target = ent.get("target_name", "")
                    rel_type = ent.get("relation_type", "singular")
                    
                    if not ename or not rel or not new_target or ename == new_target:
                        continue
                    
                    existing = None
                    for old in old_entity_rows:
                        if (old.entity_name.lower() == ename.lower() and 
                            old.relation.lower() == rel.lower() and
                            old.target_name.lower() != new_target.lower()):
                            existing = old
                            break
                    
                    if existing and rel_type == "singular":
                        definitive = bool(re.search(
                            r'\b(now|no longer|left|moved|switched|changed|currently|anymore|actually|i was wrong|still|not|i work at|i work for|i live in|i am at)\b',
                            message, re.IGNORECASE
                        ))
                        uncertain = bool(re.search(
                            r'\b(might|maybe|perhaps|not sure|i think|possibly|could be|or maybe)\b',
                            message, re.IGNORECASE
                        ))
                        
                        if definitive and not uncertain:
                            await entity_repo.supersede_entity_edge(
                                db, user_id, ename, rel, existing.target_name,
                            )
                            await entity_repo.supersede_semantic_facts_for_edge(
                                db, user_id, ename, rel, existing.target_name,
                            )
                            logger.info(
                                f"[Fact Change] {ename}: '{rel}' auto-updated "
                                f"'{existing.target_name}' → '{new_target}' (definitive language)"
                            )
                        else:
                            note = (
                                f"[Fact Check]: {ename} — recorded as {rel} → {existing.target_name}. "
                                f"User message says {rel} → {new_target}."
                            )
                            if uncertain:
                                note += " User expressed uncertainty."
                            _pending_contradictions.append(note)

                for ent in entities:
                    if ent.get("entity_name") == ent.get("target_name"):
                        continue

                    disambig_relations = {'is_different_from', 'not_same_as', 'separate_from'}
                    if ent.get("relation", "").lower() not in disambig_relations:
                        ent["entity_name"] = await entity_repo.find_canonical_name(
                            db, user_id, ent["entity_name"]
                        )
                        ent["target_name"] = await entity_repo.find_canonical_name(
                            db, user_id, ent["target_name"]
                        )
                    if ent["entity_name"] == ent["target_name"]:
                        continue

                    existing = await entity_repo.find_entity_edge(
                        db, user_id, ent["entity_name"], ent["relation"], ent["target_name"],
                    )
                    if not existing:
                        entity = EntityMemory(
                            user_id=user_id,
                            entity_name=ent["entity_name"],
                            entity_type=ent.get("entity_type", "unknown"),
                            relation=ent["relation"],
                            target_name=ent["target_name"],
                            target_type=ent.get("target_type", "unknown"),
                            source_message_id=wm.id,
                            conversation_id=conversation_id,
                            confidence=ent.get("confidence", 1.0),
                        )
                        await entity_repo.save_entity(db, entity)
                        invalidate_graph(user_id)
                        log_audit_event(db, user_id, "write", "entity", entity.id,
                                       f"{ent['entity_name']} {ent['relation']} {ent['target_name']}")

                    departure_relations = {"left", "departed", "quit", "resigned_from", "exited"}
                    if ent.get("relation", "").lower() in departure_relations:
                        for core_rel in ("works_at", "lives_in", "works_as", "contractor_at"):
                            count = await entity_repo.supersede_entity_edge(
                                db, user_id, ent["entity_name"], core_rel, ent["target_name"],
                            )
                            if count > 0:
                                logger.info(
                                    f"[Departure Cleanup] Superseded {count} '{core_rel}' "
                                    f"edge(s) for {ent['entity_name']} → {ent['target_name']}"
                                )
                    
                    relation_type = ent.get("relation_type", "").lower()
                    if relation_type == "singular":
                        opposite_transitions = {"left", "joined", "rejoined", "moved_to", "moved_from", "relocated_to"}
                        for opp_rel in opposite_transitions:
                            count = await entity_repo.supersede_entity_edge(
                                db, user_id, ent["entity_name"], opp_rel, ent["target_name"],
                            )
                            if count > 0:
                                logger.info(
                                    f"[Transition Cleanup] Superseded {count} '{opp_rel}' "
                                    f"edge(s) for {ent['entity_name']} → {ent['target_name']}"
                                )
            except Exception as e:
                logger.warning(f"[Entity Extraction] Failed: {e}")
    
    if importance >= save_threshold:
        try:
            await db.commit()
        except Exception:
            logger.warning(f"DB commit failed after entity extraction for user {user_id}", exc_info=True)

    greeting_words = {'hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening', 'yo', 'sup', 'heyy', 'howdy'}
    is_greeting = (len(message.split()) <= 2 and message.lower().strip('?!. ') in greeting_words)

    recent_rows = await memory_repo.get_recent_conversation_messages(db, conversation_id, limit=5)
    recent_context = "\n".join([f"[{'You' if m.role == 'assistant' else 'User'}]: {m.message[:200]}" for m in recent_rows[-5:]])

    if is_greeting:
        agent_steps = []
        context_text = []
        seen = set()
        profile = await memory_repo.get_user_profile(db, user_id, limit=5)
        for mem in profile:
            label = f"[About You]: {mem.message}"
            if label not in seen:
                seen.add(label)
                context_text.append(label)
        agent_steps.append({"action": "profile", "detail": f"Loaded {len(profile)} facts",
            "preview": [m.message[:80] + ('...' if len(m.message) > 80 else '') for m in profile]})

        recent = await memory_repo.get_recent_conversation_messages(db, conversation_id, limit=3)
        for mem in recent:
            label = f"[{'You' if mem.role == 'assistant' else 'User'}]: {mem.message}"
            if label not in seen:
                seen.add(label)
                context_text.append(label)
        agent_steps.append({"action": "recent", "detail": f"Loaded {len(recent)} recent",
            "preview": [m.message[:80] + ('...' if len(m.message) > 80 else '') for m in recent]})
        agent_steps.append({"action": "done", "detail": "Ready (greeting bypass)"})
    else:
        agent_steps = []
        context_text = []
        seen = set()

        # Query rewriting
        search_variants = []
        if len(message.split()) > 2:
            search_variants = await _query_rewrite(message, recent_context)
            if search_variants:
                logger.info(f"[Query Rewrite] Original: '{message[:60]}' → Variants: {search_variants}")

        context_text, agent_steps = await agentic_retrieve(
            db, user_id, message, query_vector, conversation_id, config, recent_context,
        )

        if search_variants:
            agent_steps.insert(0, {
                "action": "rewrite",
                "detail": f"{len(search_variants)} variants",
                "variants": [message] + search_variants,
            })

        # Add snippets to search step
        for step in agent_steps:
            if step.get("action") == "search" and step.get("count", 0) > 0:
                snippets = []
                for item in context_text[-10:]:
                    snippets.append(item[:80] + ('...' if len(item) > 80 else ''))
                step["snippets"] = snippets[:3]

    from models import User
    from sqlmodel import select as sql_select
    result = await db.execute(sql_select(User).where(User.id == user_id))
    user = result.scalars().first()
    # Skip identity injection when context is file content — the user is asking about a file, not themselves
    has_file_content = any(item.startswith('[log]:') or item.startswith('[file]:') for item in context_text)
    if user and user.display_name and not has_file_content:
        context_text.insert(0, f"[User Identity: {user.display_name}]")
    elif user and user.username and not has_file_content:
        context_text.insert(0, f"[User Identity: {user.username}]")
    elif not has_file_content:
        context_text.insert(0, "[User Identity: UNKNOWN]")

    # Render context + apply token budget
    t2 = time.perf_counter()
    
    # ── Contradiction handling ──
    clarification_question: str | None = None
    
    # Fallback: if entity extraction returned nothing but message has uncertainty
    # about known entities, synthesize a fact check note.
    if not _pending_contradictions:
        uncertain_markers = r'\b(might|maybe|perhaps|not sure|i think|possibly|could be|or maybe|unsure)\b'
        if re.search(uncertain_markers, message, re.IGNORECASE):
            known_names = set()
            for item in context_text:
                for m in re.finditer(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s', item):
                    known_names.add(m.group(1).lower())
            msg_names = set(re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', message))
            matching = [n for n in msg_names if n.lower() in known_names]
            if matching:
                note = (
                    f"[Fact Check]: {matching[0]} — recorded in entity graph. "
                    f"Your message suggests a possible change but you sounded uncertain. "
                    f"User message: \"{message[:200]}\""
                )
                _pending_contradictions.append(note)
                logger.info(f"[Fallback] Synthesized fact check for {matching[0]}")
    
    if _pending_contradictions:
        # Skip two-pass for pronoun-only clarifications — the chat model
        # handles "who does 'he' refer to" naturally in conversation flow.
        # Only trigger two-pass for substantive fact conflicts.
        substantive_notes = [
            n for n in _pending_contradictions
            if not re.search(r'\b(he|she|they|who does .* refer to)\b', n, re.IGNORECASE)
        ]
        if substantive_notes:
            from services.qwen_service import get_client as qwen_get_client
            client = qwen_get_client()
            
            notes_text = "\n".join(substantive_notes[:3])
            clarification_prompt = f"""The user's message triggered these fact checks:

{notes_text}

The user's original message was: "{message}"

Generate exactly ONE clear, direct question to ask the user. Combine multiple concerns into a single question if possible. Output ONLY JSON: {{"question": "your question here"}}"""
            
            try:
                clar_response = await client.chat.completions.create(
                    model="qwen-plus-latest",
                    messages=[{"role": "user", "content": clarification_prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_tokens=150,
                )
                clar_data = json.loads(clar_response.choices[0].message.content)
                clarification_question = clar_data.get("question", "").strip()
                if clarification_question:
                    logger.info(f"[Clarification] Two-pass generated: '{clarification_question}'")
            except Exception as e:
                logger.warning(f"[Clarification] Two-pass failed: {e}")
        
        # Attach structured contradiction data to agent steps for the frontend
        parsed_contradictions = []
        for note in _pending_contradictions[:3]:
            match = re.match(
                r"\[Fact Check\]: (.+?) — recorded as (.+?) → (.+?)\. Your message says (.+?) → (.+?)\.",
                note
            )
            if match:
                parsed_contradictions.append({
                    "entity": match.group(1),
                    "relation": match.group(2).replace("'", ""),
                    "old_target": match.group(3).rstrip('.'),
                    "new_target": match.group(5).rstrip('.'),
                })
        if parsed_contradictions:
            for step in agent_steps:
                if step.get("action") in ("graph", "context"):
                    step["contradictions"] = parsed_contradictions
                    break
    
    rendered = _hierarchical_render(context_text)
    all_context = rendered[:20]
    context_str = "\n".join(all_context) if all_context else "No relevant memories found."
    logger.info(f"[Timing] DB search + context build: {t2-t1:.2f}s")

    naive = sum(len(item) // 3 for item in rendered)
    actual = len(context_str) // 3
    token_naive_total[user_id] = token_naive_total.get(user_id, 0) + naive
    token_actual_total[user_id] = token_actual_total.get(user_id, 0) + actual

    logger.info(f"[MemoryAgent] Context: {len(all_context)} items, {len(context_str)} chars — empty={not bool(all_context)}")
    if all_context:
        logger.info(f"[MemoryAgent] First 3 context items: {all_context[:3]}")

    # Agent trace enrichment
    if all_context:
        source_label = f"{len(all_context)} memories retrieved → LLM"
    else:
        source_label = "No memories found → general knowledge"
    agent_steps.append({
        "action": "context",
        "detail": source_label,
        "count": len(all_context),
        "preview": all_context if all_context else [],
    })

    # Stream response
    system_prompt = CREATIVE_PROMPT if _is_creative(message) else ATUNBI_PROMPT
    temperature = getattr(config, 'temp_default', 0.7)
    logger.info(f"[Prompt] {'creative' if system_prompt == CREATIVE_PROMPT else 'default'} | temp={temperature} | query: {message[:60]}...")

    logger.info(f"[Token Budget] Context: ~{actual} tokens, {len(all_context)} items")
    for step in agent_steps:
        yield _sse_line(f"[AGENT_STEP] {json.dumps(step)}")
    yield _sse_line(f"[CONVERSATION_ID] {conversation_id}")

    full_response = ""
    
    # Two-pass: stream the clarification question first (if generated).
    # When there's a pending question, skip the main model entirely — 
    # no speculation after a question.
    if clarification_question:
        full_response = clarification_question
        yield _sse_line(clarification_question)
        yield _sse_line("[DONE]")
        # Save the question as AI response
        try:
            ai_embedding = await get_embedding(clarification_question[:500])
            ai_memory = WorkingMemory(
                user_id=user_id, message=clarification_question, role="assistant",
                conversation_id=conversation_id, embedding=ai_embedding,
                importance=0.5, emotion=0.0
            )
            db.add(ai_memory)
            await db.commit()
        except Exception:
            logger.warning(f"Failed to save clarification question for conv {conversation_id}", exc_info=True)
        return
    
    async for token in generate_stream(context_str, message, temperature=temperature, system_prompt=system_prompt):
        full_response += token
        yield _sse_line(token)
    yield _sse_line("[DONE]")

    # Save AI response to WorkingMemory so it persists across page refreshes
    if full_response.strip():
        try:
            ai_embedding = await get_embedding(full_response[:500])  # first 500 chars for embedding
            ai_memory = WorkingMemory(
                user_id=user_id,
                message=full_response,
                role="assistant",
                conversation_id=conversation_id,
                embedding=ai_embedding,
                importance_score=0.0,
                emotional_valence=0.0,
                timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                source_turn_id=str(uuid.uuid4()),
            )
            await memory_repo.save_working_memory(db, ai_memory)
        except Exception:
            logger.exception(f"Failed to save assistant response for conv {conversation_id}")

    # Push updated stats
    try:
        stats = await get_stats(db, user_id)
        await event_bus.broadcast(user_id, stats)
    except Exception:
        logger.exception("broadcast_stats failed")
