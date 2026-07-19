import re
from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select, func, delete
from api.dependencies import get_db, get_current_user
from models import User, WorkingMemory, EntityMemory, FileAttachment

router = APIRouter(tags=["History"])

@router.get("/history")
async def get_conversation_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(WorkingMemory.conversation_id).where(WorkingMemory.user_id == current_user.id).distinct()
    result = await db.execute(stmt)
    conv_ids = result.scalars().all()

    conversations = []
    for conv_id in conv_ids:
        if not conv_id: continue
        
        title_stmt = (
            select(WorkingMemory.message, WorkingMemory.timestamp)
            .where(WorkingMemory.user_id == current_user.id, WorkingMemory.conversation_id == conv_id)
            .order_by(WorkingMemory.timestamp.asc())
            .limit(1)
        )
        title_res = await db.execute(title_stmt)
        first_msg = title_res.first()

        count_stmt = (
            select(func.count(WorkingMemory.id))
            .where(WorkingMemory.user_id == current_user.id, WorkingMemory.conversation_id == conv_id)
        )
        count_res = await db.execute(count_stmt)
        msg_count = count_res.scalar() or 0
        
        if first_msg:
            raw = first_msg.message
            # Clean up file-upload messages: extract just the filename
            if raw.startswith("[file:") and "]" in raw:
                fname = raw.split("]", 1)[0].replace("[file:", "").strip()
                title = f"📄 {fname}" if len(fname) <= 30 else f"📄 {fname[:28]}…"
            elif re.match(r'\[(video|audio|image):', raw):
                # Media upload — show just the filename with emoji
                m = re.match(r'\[(video|audio|image):([^\]]+)\]', raw)
                if m:
                    kind, fname = m.group(1), m.group(2).strip()
                    emoji = {"video": "🎬", "audio": "🎵", "image": "🖼️"}.get(kind, "📎")
                    title = f"{emoji} {fname}" if len(fname) <= 30 else f"{emoji} {fname[:28]}…"
                else:
                    title = raw[:40] + "…" if len(raw) > 40 else raw
            elif raw.startswith("✅ ") or raw.startswith("⚠️ ") or raw.startswith("📄 "):
                # Already a formatted upload confirmation
                title = raw[:40] + "…" if len(raw) > 40 else raw
            else:
                # Smart truncation at word boundary, max 40 chars
                if len(raw) <= 40:
                    title = raw
                else:
                    cut = raw[:40].rsplit(" ", 1)[0]
                    title = cut + "…"
            conversations.append({
                "id": conv_id,
                "title": title,
                "date": first_msg.timestamp.isoformat() + "Z",  # DB stores naive UTC — tell JS
                "message_count": msg_count
            })
            
    conversations.sort(key=lambda x: x["date"], reverse=True)
    return conversations

@router.get("/history/{conversation_id}")
async def get_conversation_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = (
        select(WorkingMemory)
        .where(WorkingMemory.user_id == current_user.id, WorkingMemory.conversation_id == conversation_id)
        .order_by(WorkingMemory.timestamp.asc())
    )
    result = await db.execute(stmt)
    memories = result.scalars().all()
    
    messages = []
    for m in memories:
        # Skip system messages — file content chunks are for retrieval only
        if m.role == "system":
            continue
        content = m.message
        messages.append({"role": m.role, "content": content})
    return {"conversation_id": conversation_id, "messages": messages}

@router.delete("/history/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Detach entity references first to avoid FK violation on bulk delete
    wm_ids_stmt = select(WorkingMemory.id).where(
        WorkingMemory.user_id == current_user.id,
        WorkingMemory.conversation_id == conversation_id
    )
    wm_ids_result = await db.execute(wm_ids_stmt)
    wm_ids = [row[0] for row in wm_ids_result.all()]
    if wm_ids:
        entity_stmt = select(EntityMemory).where(EntityMemory.source_message_id.in_(wm_ids))
        entity_result = await db.execute(entity_stmt)
        for entity in entity_result.scalars().all():
            entity.source_message_id = None
        await db.flush()
    stmt = delete(WorkingMemory).where(
        WorkingMemory.user_id == current_user.id,
        WorkingMemory.conversation_id == conversation_id
    )
    await db.execute(stmt)

    from services.storage_service import _get_bucket as _oss_bucket
    fa_stmt = select(FileAttachment).where(
        FileAttachment.user_id == current_user.id,
        FileAttachment.conversation_id == conversation_id
    )
    fa_result = await db.execute(fa_stmt)
    attachments = fa_result.scalars().all()
    for att in attachments:
        if att.oss_key and not att.oss_key.startswith("local://"):
            try:
                _oss_bucket().delete_object(att.oss_key)
            except Exception:
                pass
    if attachments:
        await db.execute(delete(FileAttachment).where(
            FileAttachment.user_id == current_user.id,
            FileAttachment.conversation_id == conversation_id
        ))

    await db.commit()
    return {"status": "deleted"}
