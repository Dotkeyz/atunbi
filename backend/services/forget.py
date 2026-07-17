"""Forget command handling."""
import json
import logging
import re
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, delete
from models import WorkingMemory, SemanticMemory, EntityMemory
from services.qwen_service import get_client
from services.tools_service import forget_memories, forget_entities_by_relation

logger = logging.getLogger("atunbi.forget")

FORGET_PATTERNS = [
    re.compile(r'forget\s+(?:everything\s+)?(?:about|all\s+of)?\s*(?:my\s+)?(.+?)(?:[.!]?\s*$)', re.IGNORECASE),
    re.compile(r'delete\s+(?:everything\s+)?(?:about|all\s+of)?\s*(?:my\s+)?(.+?)(?:[.!]?\s*$)', re.IGNORECASE),
    re.compile(r'clear\s+(?:everything\s+)?(?:about|all\s+of)?\s*(?:my\s+)?(.+?)(?:[.!]?\s*$)', re.IGNORECASE),
    re.compile(r'remove\s+(?:everything\s+)?(?:about|all\s+of)?\s*(?:my\s+)?(.+?)(?:[.!]?\s*$)', re.IGNORECASE),
]

FORGET_TARGET_TO_RELATIONS: dict[str, list[str]] = {
    'tech stack': ['uses', 'prefers', 'learning'],
    'stack': ['uses', 'prefers', 'learning'],
    'tools': ['uses'],
    'languages': ['uses'],
    'preferences': ['prefers', 'prefers_not_to_discuss', 'avoids'],
    'team': ['works_at', 'works_with', 'reports_to', 'leads'],
    'work': ['works_at'],
    'projects': ['works_on', 'migrating', 'building'],
    'contact': ['lives_in', 'email', 'phone'],
    'food': ['loves', 'likes', 'eats', 'allergic_to'],
    'hobbies': ['likes', 'loves', 'enjoys'],
    'education': ['studied', 'graduated', 'attends'],
}


async def handle_forget(db: AsyncSession, user_id: int, message: str) -> tuple[bool, str | None]:
    """If message is a forget command, execute it and return (True, response)."""
    msg_lower = message.lower().strip().rstrip('.!?')

    if re.search(r'forget\s+the\s+forget', msg_lower):
        return (False, None)

    target = ""
    for pattern in FORGET_PATTERNS:
        m = pattern.search(msg_lower)
        if m:
            target = m.group(1).strip().rstrip('.!?')
            break

    if not target:
        return (False, None)

    target = await _parse_forget_target(message, target)
    if not target:
        return (False, None)

    logger.info(f"[Forget] target='{target}'")

    forgotten = 0
    forgotten_targets: list[str] = []

    relations_to_clear = FORGET_TARGET_TO_RELATIONS.get(target, [])
    if relations_to_clear:
        for rel in relations_to_clear:
            targets = await db.execute(
                select(EntityMemory.target_name).where(
                    EntityMemory.user_id == user_id,
                    EntityMemory.relation == rel,
                    EntityMemory.status == "active",
                )
            )
            forgotten_targets.extend([t[0] for t in targets.all() if t[0]])
            n = await forget_entities_by_relation(db, user_id, rel)
            forgotten += n

    text_forgotten = await forget_memories(db, user_id, target)
    forgotten += text_forgotten

    marker_fact = f"[Forgotten: {target}]"
    if forgotten_targets:
        marker_fact = f"[Forgotten: {target} | {', '.join(forgotten_targets[:10])}]"

    existing = (await db.execute(
        select(SemanticMemory).where(
            SemanticMemory.user_id == user_id,
            SemanticMemory.fact.like(f"[Forgotten: {target}%")
        )
    )).scalars().first()
    if existing:
        existing.status = "active"
        existing.confidence = 1.0
        existing.fact = marker_fact
        db.add(existing)
    else:
        try:
            sm = SemanticMemory(
                user_id=user_id,
                fact=marker_fact,
                confidence=1.0,
                status="active",
            )
            db.add(sm)
            await db.commit()
        except Exception:
            await db.rollback()
    forgotten += 1

    await db.commit()

    if forgotten > 0:
        response = f"Done — I've cleared {forgotten} memories about your {target}. I won't bring it up unless you do."
    else:
        response = f"I don't have any stored memories about your {target} to clear."

    return (True, response)


async def handle_forget_the_forget(db: AsyncSession, user_id: int, message: str) -> bool:
    """If message is 'forget the forget about X', remove the [Forgotten: X] marker."""
    if not re.search(r'forget\s+the\s+forget', message.lower()):
        return False

    ff_match = re.search(
        r'forget\s+the\s+forget\s+(?:about\s+)?(\w[\w\s]+?)(?:[.!]?\s*$|$)',
        message.lower()
    )
    if not ff_match:
        return False

    topic = ff_match.group(1).strip()
    result = await db.execute(
        delete(SemanticMemory).where(
            SemanticMemory.user_id == user_id,
            SemanticMemory.fact == f"[Forgotten: {topic}]",
        )
    )
    await db.commit()
    return result.rowcount > 0


async def _parse_forget_target(message: str, raw_target: str) -> str | None:
    """Parse a forget command with qwen-turbo. Returns the clean target or None if casual speech."""
    client = get_client()
    try:
        response = await client.chat.completions.create(
            model="qwen-turbo",
            messages=[{
                "role": "system",
                "content": """Parse a forget command into a JSON object: {"target": "<topic>", "exclude": ["<item>"]}

Extract the main topic (1-3 words, lowercase). List exceptions in exclude.
Return {"target": null} for casual speech, figures of speech, questions, or personal relationships (ex, boyfriend, girlfriend, wife, husband, friend, family member).

Examples:
- "forget my work" → {"target": "work", "exclude": []}
- "delete my tech stack but keep React" → {"target": "tech stack", "exclude": ["react"]}
- "forget my ex but keep the good memories" → {"target": null}
- "I'll never forget this" → {"target": null}"""
            }, {
                "role": "user",
                "content": f"Message: \"{message}\"\nRaw: \"{raw_target}\""
            }],
            temperature=0.0,
            max_tokens=50,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        target = data.get("target")
        if target and isinstance(target, str) and target.strip():
            return target.strip().lower()
        return None
    except Exception:
        logger.warning(f"[Forget] Parse failed, falling back: '{raw_target}'")
        return raw_target.lower()
