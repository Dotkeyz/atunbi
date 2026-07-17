"""Entity extraction — detects entities, contradictions, and clarification needs from messages."""
import json
import logging
from services.qwen_service import get_client

logger = logging.getLogger("atunbi.extraction")


def _validate_entity(ent: dict) -> bool:
    en = ent.get("entity_name", "").strip().lower()
    tn = ent.get("target_name", "").strip().lower()
    et = ent.get("entity_type", "").strip()
    tt = ent.get("target_type", "").strip()
    rel = ent.get("relation", "").strip().lower()

    if not et or not tt:
        return False

    PRONOUNS_AND_COMMON = {
        'i', 'me', 'my', 'we', 'us', 'our', 'you', 'your', 'he', 'she',
        'it', 'they', 'them', 'there', 'here', 'this', 'that', 'these', 'those',
        'work', 'use', 'code', 'api', 'app', 'thing', 'stuff',
        'something', 'anything', 'nothing', 'yes', 'no', 'ok', 'okay',
        'speaker', 'user', 'person', 'someone', 'anyone', 'everyone',
    }
    if en in PRONOUNS_AND_COMMON or tn in PRONOUNS_AND_COMMON:
        return False

    NON_PROPER_RELATIONS = {'prefers_not_to_discuss', 'avoids', 'dislikes'}
    if rel not in NON_PROPER_RELATIONS:
        en_raw = ent.get("entity_name", "")
        tn_raw = ent.get("target_name", "")
        if not any(c.isupper() for c in en_raw):
            return False
        if not any(c.isupper() for c in tn_raw):
            return False

    ROLE_WORDS = {
        'chief', 'head', 'vp', 'director', 'manager', 'president',
        'engineer', 'developer', 'officer', 'senior', 'lead', 'junior',
        'coo', 'cto', 'ceo', 'cfo',
    }
    en_words = set(en.split())
    tn_words = set(tn.split())
    if en_words & ROLE_WORDS or tn_words & ROLE_WORDS:
        return False

    return True


async def extract_entities(text: str, context: str = "", entity_context: str = "") -> dict:
    client = get_client()

    user_parts = []
    if entity_context:
        user_parts.append(f"Existing knowledge:\n{entity_context}")
    if context:
        user_parts.append(f"Previous message (for pronoun context): {context}")
    user_parts.append(f"Current message: {text}")
    user_content = "\n\n".join(user_parts)

    try:
        response = await client.chat.completions.create(
            model="qwen-plus-latest",
            messages=[
                {"role": "system", "content": """You are an entity and contradiction detector for a cognitive memory system.

Your job: extract relationships from the CURRENT message AND flag contradictions with existing knowledge.

Output a JSON object with three fields:

1. "entities" — new relationships to record from the CURRENT message:
   - entity_name: proper noun (person, company, tech, location, etc.). Capitalized. NEVER a pronoun.
   - entity_type: descriptive label (person, company, technology, location, food, etc.)
   - relation: the verb (works_at, uses, left, lives_in, prefers, loves, etc.)
   - target_name: same rules as entity_name
   - target_type: same rules as entity_type
   - relation_type: "singular" if only ONE at a time (works_at, lives_in, prefers). "plural" if MANY can coexist (uses, loves, likes, knows, owns).

2. "contradictions" — when the CURRENT message says something that differs from EXISTING KNOWLEDGE (entity_context). Only flag when entity_name AND relation match but target_name differs. Each:
   - entity: the entity name
   - relation: the relation verb
   - previous_target: what existing knowledge says
   - new_target: what the current message says

3. "needs_clarification" — when you are UNSURE which person a fact belongs to. Output a string asking the user to clarify. If confident, set to null.

CRITICAL RULES:
- **If the message mentions multiple people and you're unsure who a fact applies to → use needs_clarification. Do NOT guess.**
- **Uncertain language (might, maybe, not sure, I think, could be) → STILL extract the fact and flag it as a contradiction.**
- **NEGATION**: "I don't use X", "I never use Y", "doesn't work at Y" → DO NOT extract. Skip negated statements entirely.
- **PREFERENCES**: "I never want to discuss X", "don't talk about Y" → Extract as relation "prefers_not_to_discuss" with target "X".
- Departments and roles are NOT workplaces: "VP of Platform" → skip or use "leads".
- NEVER output pronouns. Resolve "I"/"he"/"she"/"they" from context.
- NEVER flag a contradiction when relation_type is "plural" — those can coexist.
- NEVER flag a contradiction for brand-new entities that don't exist in entity_context.
- Max 8 entities. Max 4 contradictions. needs_clarification: null or one string.
- If no entities and no clarification needed, return {"entities": [], "contradictions": [], "needs_clarification": null}."""},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=500
        )
        content = response.choices[0].message.content
        result = json.loads(content)
        entities = result.get("entities", [])
        if isinstance(entities, list):
            entities = [e for e in entities if _validate_entity(e)]
        contradictions = result.get("contradictions", [])
        if not isinstance(contradictions, list):
            contradictions = []
        needs_clarification = result.get("needs_clarification")
        return {"entities": entities, "contradictions": contradictions, "needs_clarification": needs_clarification}
    except Exception as e:
        logger.warning(f"[Entity Extraction] Failed: {e}")
        return {"entities": [], "contradictions": [], "needs_clarification": None}
