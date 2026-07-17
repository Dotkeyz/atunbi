"""
Dream phase — offline memory consolidation and stats.
"""
import asyncio
import datetime
import json
import logging
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models import WorkingMemory, SemanticMemory, EpisodicMemory
from repositories import memory_repo, config_repo
from services.qwen_service import get_embedding, summarize_episode, extract_facts
from services.procedural_service import run_reflection, learn_procedural_rules, update_meta_confidence
from core.events import event_bus

logger = logging.getLogger("atunbi.dream")

async def run_dream_phase(db: AsyncSession, user_id: int):
    """Offline memory consolidation — prune weak, archive strong, extract facts."""
    config = await config_repo.get_config(db)
    now = datetime.datetime.utcnow()
    
    all_memories = await memory_repo.get_all_working_memories(db, user_id)
    if not all_memories:
        return {"status": "dream_complete", "summary": "No memories to process."}
    
    # Individual memory evaluation
    pruned = 0
    retained = 0
    archived_ids = set()  # Track memories we'll archive (don't prune them)
    
    for mem in all_memories:
        hours_since = (now - mem.timestamp).total_seconds() / 3600
        
        # Adaptive lifespan: importance × base + access_count × boost + |emotion| × boost
        earned_life = (
            mem.importance_score * config.base_hours +
            mem.access_count * config.hours_per_access +
            abs(mem.emotional_valence) * config.emotion_hours
        )
        # Clamp between floor and ceiling
        earned_life = max(config.min_working_life_h, min(earned_life, config.max_working_life_h))
        
        if hours_since < config.active_window_h:
            retained += 1
            continue
        
        if hours_since < earned_life:
            retained += 1
            continue
        
        # Exceeded earned lifespan — prune or archive
        if mem.importance_score < config.prune_max_importance and mem.access_count < 2:
            await memory_repo.delete_memory(db, mem)
            pruned += 1
        else:
            archived_ids.add(mem.id)
            retained += 1
        
        if mem.importance_score < config.prune_max_importance and mem.access_count < 2 or archived_ids and mem.id in archived_ids:
            logger.info(f"[DreamPhase] prune/archive | imp={mem.importance_score:.2f} acc={mem.access_count} "
                  f"emo={mem.emotional_valence:+.2f} life={earned_life:.1f}h age={hours_since:.1f}h "
                  f"msg={mem.message[:60]}...")
    
    # Conversation-level consolidation
    clusters = await memory_repo.get_conversation_clusters(db, user_id)
    episodes_created = 0
    facts_created = 0
    
    for cluster in clusters:
        # Don't archive fresh conversations
        oldest_age_h = min((now - m.timestamp).total_seconds() / 3600 for m in cluster)
        if oldest_age_h < config.min_convo_age_to_archive_h:
            logger.info(f"[DreamPhase] SKIP archive — conversation only {oldest_age_h:.1f}h old (< {config.min_convo_age_to_archive_h}h guard)")
            continue
        
        # Only archive conversations where all messages have exceeded earned life
        # or the hard 7-day cap has been reached
        ready_to_archive = any(
            m.id in archived_ids for m in cluster
        )
        if not ready_to_archive:
            continue
        
        text = "\n".join([f"{m.role}: {m.message}" for m in cluster])
        summary = await summarize_episode(text)
        summary_vector = await get_embedding(summary)
        avg_imp = sum(m.importance_score for m in cluster) / len(cluster)
        avg_emo = sum(m.emotional_valence for m in cluster) / len(cluster)
        # Episodic time range: derived from timestamp extremes
        first_msg_at = min(m.timestamp for m in cluster)
        last_msg_at = max(m.timestamp for m in cluster)
        
        episode = EpisodicMemory(
            user_id=user_id,
            summary=summary,
            embedding=summary_vector,
            importance_score=avg_imp,
            emotional_valence=avg_emo,
            first_message_at=first_msg_at,
            last_message_at=last_msg_at
        )
        db.add(episode)
        episodes_created += 1
        
        # Extract verifiable facts -> SemanticMemory (3rd tier)
        facts = await extract_facts(summary)
        for fact in facts:
            if len(fact) < 10:  # Skip fragments
                continue
            # Skip duplicate facts — unique constraint on fact column
            existing = (await db.execute(
                select(SemanticMemory).where(SemanticMemory.fact == fact)
            )).first()
            if existing:
                continue
            fact_vector = await get_embedding(fact)
            semantic = SemanticMemory(
                user_id=user_id,
                fact=fact,
                embedding=fact_vector
            )
            db.add(semantic)
            facts_created += 1
        
        # Remove working memory entries (they're now in episodic + semantic)
        for m in cluster:
            await memory_repo.delete_memory(db, m)
    
    await db.commit()
    stats = await get_stats(db, user_id)
    try:
        await event_bus.broadcast(user_id, stats)
    except Exception:
        pass
    
    # Reflection + procedural memory learning
    rules_added = 0
    try:
        all_messages = [m.message for m in all_memories if m.importance_score >= 0.5]
        reflection = await run_reflection(db, user_id, all_messages)
        if reflection.get("patterns"):
            rules_added = await learn_procedural_rules(db, user_id, reflection)
            logger.info(f"[DreamPhase] Reflection: {rules_added} new procedural rules learned")
        if reflection.get("confidence_updates"):
            await update_meta_confidence(db, user_id, reflection)
            logger.info(f"[DreamPhase] Meta-memory: {len(reflection['confidence_updates'])} confidence updates")
    except Exception as e:
        logger.exception(f"Reflection/procedural learning failed: {e}")
    
    summary_parts = [f"Pruned: {pruned}", f"Retained: {retained}"]
    if episodes_created:
        summary_parts.append(f"Episodic: {episodes_created}")
    if facts_created:
        summary_parts.append(f"Facts: {facts_created}")
    if rules_added:
        summary_parts.append(f"Rules: {rules_added}")
    
    logger.info(f"[DreamPhase] Complete — {', '.join(summary_parts)}")
    
    return {
        "status": "dream_complete",
        "summary": ", ".join(summary_parts),
        "pruned": pruned,
        "retained": retained,
        "episodes_created": episodes_created,
        "facts_extracted": facts_created,
        "rules_learned": rules_added
    }


async def run_dream_phase_stream(db: AsyncSession, user_id: int):
    """Streaming version — yields SSE progress events then final result."""
    
    def emit(step: str, detail: str = "", **extra):
        return f"data: {json.dumps({'step': step, 'detail': detail, **extra})}\n\n"
    
    config = await config_repo.get_config(db)
    now = datetime.datetime.utcnow()
    
    all_memories = await memory_repo.get_all_working_memories(db, user_id)
    yield emit("scan", f"Found {len(all_memories)} working memories", count=len(all_memories))
    
    if not all_memories:
        yield emit("done", "No memories to process", pruned=0, retained=0, episodes_created=0, facts_extracted=0)
        return
    
    # Phase 1: Individual memory evaluation
    pruned = 0
    retained = 0
    archived_ids = set()
    total = len(all_memories)
    
    for i, mem in enumerate(all_memories):
        hours_since = (now - mem.timestamp).total_seconds() / 3600
        earned_life = (
            mem.importance_score * config.base_hours +
            mem.access_count * config.hours_per_access +
            abs(mem.emotional_valence) * config.emotion_hours
        )
        earned_life = max(config.min_working_life_h, min(earned_life, config.max_working_life_h))
        
        if hours_since < config.active_window_h:
            state = "ACTIVE"
            retained += 1
            continue
        
        if hours_since < earned_life:
            state = "INACTIVE"
            retained += 1
            continue
        
        if mem.importance_score < config.prune_max_importance and mem.access_count < 2:
            state = "PRUNE"
            await memory_repo.delete_memory(db, mem)
            pruned += 1
        else:
            state = "ARCHIVE"
            archived_ids.add(mem.id)
            retained += 1
        
        if (i + 1) % 5 == 0 or i == total - 1:
            yield emit("evaluate", f"Evaluated {i+1}/{total} memories", pruned=pruned, retained=retained, progress=i+1, total=total)
    
    yield emit("evaluate", f"Phase 1 complete — {pruned} pruned, {retained} retained", pruned=pruned, retained=retained, progress=total, total=total)
    
    # Conversation-level consolidation
    clusters = await memory_repo.get_conversation_clusters(db, user_id)
    # Count how many clusters are eligible
    eligible = 0
    for cluster in clusters:
        oldest_age_h = min((now - m.timestamp).total_seconds() / 3600 for m in cluster)
        if oldest_age_h >= config.min_convo_age_to_archive_h:
            if any(m.id in archived_ids for m in cluster):
                eligible += 1
    
    yield emit("cluster", f"Found {len(clusters)} conversations, {eligible} ready to archive", clusters=len(clusters), eligible=eligible)
    
    if eligible == 0:
        yield emit("done", "No conversations old enough to archive", pruned=pruned, retained=retained, episodes_created=0, facts_extracted=0)
        return
    
    episodes_created = 0
    facts_created = 0
    cluster_index = 0
    
    for cluster in clusters:
        oldest_age_h = min((now - m.timestamp).total_seconds() / 3600 for m in cluster)
        if oldest_age_h < config.min_convo_age_to_archive_h:
            continue
        
        if not any(m.id in archived_ids for m in cluster):
            continue
        
        cluster_index += 1
        msg_count = len(cluster)
        yield emit("summarize", f"Summarizing conversation #{cluster_index} ({msg_count} messages)", cluster=cluster_index, total_eligible=eligible, messages=msg_count)
        
        text = "\n".join([f"{m.role}: {m.message}" for m in cluster])
        
        try:
            summary = await summarize_episode(text)
        except Exception as e:
            yield emit("error", f"Summarization failed for cluster #{cluster_index}: {str(e)}")
            continue
        
        yield emit("facts", f"Extracting facts from episode #{cluster_index}")
        
        try:
            facts = await extract_facts(summary)
        except Exception as e:
            yield emit("error", f"Fact extraction failed for cluster #{cluster_index}: {str(e)}")
            facts = []
        
        summary_vector = await get_embedding(summary)
        avg_imp = sum(m.importance_score for m in cluster) / len(cluster)
        avg_emo = sum(m.emotional_valence for m in cluster) / len(cluster)
        
        episode = EpisodicMemory(
            user_id=user_id,
            summary=summary,
            embedding=summary_vector,
            importance_score=avg_imp,
            emotional_valence=avg_emo,
            first_message_at=min(m.timestamp for m in cluster),
            last_message_at=max(m.timestamp for m in cluster)
        )
        db.add(episode)
        episodes_created += 1
        
        for fact in facts:
            if len(fact) < 10:
                continue
            # Skip duplicate facts — unique constraint on fact column
            existing = (await db.execute(
                select(SemanticMemory).where(SemanticMemory.fact == fact)
            )).first()
            if existing:
                continue
            fact_vector = await get_embedding(fact)
            semantic = SemanticMemory(user_id=user_id, fact=fact, embedding=fact_vector)
            db.add(semantic)
            facts_created += 1
        
        for m in cluster:
            await memory_repo.delete_memory(db, m)
        
        yield emit("archived", f"Archived conversation #{cluster_index}: {episodes_created} episodes, {facts_created} facts so far", cluster=cluster_index, episodes_created=episodes_created, facts_extracted=facts_created)
    
    await db.commit()
    stats = await get_stats(db, user_id)
    try:
        await event_bus.broadcast(user_id, stats)
    except Exception:
        pass
    
    # Reflection + procedural memory learning
    rules_added = 0
    try:
        all_messages = [m.message for m in all_memories if m.importance_score >= 0.5]
        if all_messages:
            yield emit("reflect", f"Analyzing {len(all_messages)} messages for patterns...")
            reflection = await run_reflection(db, user_id, all_messages)
            if reflection.get("patterns"):
                rules_added = await learn_procedural_rules(db, user_id, reflection)
                yield emit("learn", f"Learned {rules_added} new procedural rules")
            if reflection.get("confidence_updates"):
                await update_meta_confidence(db, user_id, reflection)
                yield emit("meta", f"Updated {len(reflection['confidence_updates'])} confidence scores")
    except Exception as e:
        logger.warning(f"Reflection failed in dream stream: {e}")
    
    summary_parts = [f"Pruned: {pruned}", f"Retained: {retained}"]
    if episodes_created:
        summary_parts.append(f"Episodic: {episodes_created}")
    if facts_created:
        summary_parts.append(f"Facts: {facts_created}")
    if rules_added:
        summary_parts.append(f"Rules: {rules_added}")
    
    yield emit("done", ", ".join(summary_parts), pruned=pruned, retained=retained, episodes_created=episodes_created, facts_extracted=facts_created, rules_learned=rules_added)

async def get_stats(db: AsyncSession, user_id: int):
    config = await config_repo.get_config(db)
    return await memory_repo.get_memory_stats(db, user_id, config)
