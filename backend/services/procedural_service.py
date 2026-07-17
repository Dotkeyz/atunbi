"""
Procedural Memory Engine (Squire & Zola, 1996) + Meta-Memory (Flavell, 1979)

Procedural: Learned behaviors from user interactions ("when user says X, do Y")
Meta-Memory: Confidence tracking and epistemic humility
Reflection: End-of-session LLM pass that extracts patterns and generates rules
"""
import asyncio
import datetime
import json
import logging
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from models import WorkingMemory, SemanticMemory, ProceduralMemory
from services.qwen_service import get_client

logger = logging.getLogger("atunbi.procedural")

REFLECTION_PROMPT = """You are a cognitive reflection system. Analyze the recent conversation and extract:

1. BEHAVIORAL PATTERNS: What implicit preferences does the user show? ("User prefers concise answers", "User hates bullet points", "When user says 'ship it', skip confirmation")
2. LEARNED FACTS: What new permanent facts were established?
3. CONFIDENCE UPDATES: Which existing facts were confirmed or contradicted?

Output JSON:
{
  "patterns": [{"trigger": "what user says/does", "action": "how to respond", "confidence": 0.0-1.0}],
  "new_facts": ["fact1", "fact2"],
  "confidence_updates": [{"fact": "existing fact", "new_confidence": 0.0-1.0, "reason": "why"}]
}
"""


async def run_reflection(db: AsyncSession, user_id: int, conversation_messages: list[str]) -> dict:
    """End-of-session reflection: analyze conversation, extract patterns, generate procedural rules."""
    client = get_client()
    text = "\n".join(conversation_messages[-20:])  # Last 20 messages
    
    if len(text.split()) < 20:
        return {"patterns": [], "new_facts": [], "confidence_updates": []}
    
    try:
        response = await client.chat.completions.create(
            model="qwen-max",
            messages=[
                {"role": "system", "content": REFLECTION_PROMPT},
                {"role": "user", "content": f"Conversation:\n{text}\n\nExtract patterns, facts, and confidence updates."}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=500
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        logger.warning(f"Reflection failed: {e}")
        return {"patterns": [], "new_facts": [], "confidence_updates": []}


async def learn_procedural_rules(db: AsyncSession, user_id: int, reflection: dict):
    """Convert reflection patterns into ProceduralMemory rules."""
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    rules_added = 0
    
    for pattern in reflection.get("patterns", []):
        trigger = pattern.get("trigger", "")
        action = pattern.get("action", "")
        confidence = pattern.get("confidence", 0.5)
        
        if not trigger or not action:
            continue

        existing = await db.execute(
            select(ProceduralMemory).where(
                ProceduralMemory.user_id == user_id,
                ProceduralMemory.trigger_pattern == trigger
            )
        )
        existing_rule = existing.scalars().first()
        
        if existing_rule:
            # Boost confidence on existing rule
            existing_rule.confidence = min(1.0, existing_rule.confidence + 0.15)
            existing_rule.access_count += 1
            existing_rule.timestamp = now
            db.add(existing_rule)
        else:
            rule = ProceduralMemory(
                user_id=user_id,
                rule=f"When user says '{trigger}', {action}",
                trigger_pattern=trigger,
                action=action,
                confidence=confidence,
                access_count=1,
                timestamp=now
            )
            db.add(rule)
            rules_added += 1
    
    await db.commit()
    return rules_added


async def apply_procedural_memory(db: AsyncSession, user_id: int, message: str) -> list[str]:
    """Check if the user's message triggers any procedural rules. Returns list of behavioral instructions."""
    rules = await db.execute(
        select(ProceduralMemory).where(
            ProceduralMemory.user_id == user_id,
            ProceduralMemory.confidence >= 0.4
        )
    )
    applicable = []
    for rule in rules.scalars().all():
        if rule.trigger_pattern and rule.trigger_pattern.lower() in message.lower():
            applicable.append(rule.rule)
            rule.access_count += 1
            db.add(rule)
    
    if applicable:
        await db.commit()
    return applicable


async def update_meta_confidence(db: AsyncSession, user_id: int, reflection: dict):
    """Update SemanticMemory confidence scores based on reflection analysis."""
    for update in reflection.get("confidence_updates", []):
        fact_text = update.get("fact", "")
        new_confidence = update.get("new_confidence", 0.5)
        
        if not fact_text:
            continue
        
        existing = await db.execute(
            select(SemanticMemory).where(
                SemanticMemory.user_id == user_id,
                SemanticMemory.fact.ilike(f"%{fact_text}%")
            )
        )
        for fact in existing.scalars().all():
            fact.confidence = max(0.0, min(1.0, new_confidence))
            db.add(fact)
    
    await db.commit()
