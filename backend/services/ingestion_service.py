"""
Omnichannel ingestion — chunks, scores, embeds, saves to WorkingMemory.
Files are uploaded to OSS; DB stores metadata pointers, not raw content.
"""

import base64
import logging
import os
import re
import subprocess
import tempfile
import uuid
import datetime
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from repositories import memory_repo, entity_repo
from services.qwen_service import get_embedding, score_message, get_client, OMNI_MODEL
from services.extraction import extract_entities
from services.storage_service import upload_file, build_oss_key
from models import WorkingMemory, EntityMemory, FileAttachment
from core.graph import invalidate_graph

logger = logging.getLogger("atunbi.ingestion")

async def ingest_text(
    db: AsyncSession,
    user_id: int,
    text: str,
    source_label: str = "upload",
    conversation_id: Optional[str] = None,
    role: str = "user",
    whole: bool = False,
) -> dict:
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    if whole:
        para = text.strip()[:500]
        if len(para) < 10:
            return {"status": "ingested", "source": source_label, "segments": 0, "conversation_id": conversation_id}
        embedding = await get_embedding(para)
        importance, emotion = await score_message(para)
        memory = WorkingMemory(
            user_id=user_id, message=f"[{source_label}]: {para}",
            role=role, conversation_id=conversation_id,
            embedding=embedding, importance_score=importance, emotional_valence=emotion,
            timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        await memory_repo.save_working_memory(db, memory)
        return {"status": "ingested", "source": source_label, "segments": 1, "conversation_id": conversation_id}

    text = re.sub(r'\n{3,}', '\n\n', text)

    raw_paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]

    paragraphs = []
    for block in raw_paragraphs:
        subs = re.split(r'\n(?=#{1,3}\s)|(?<=\n)-{3,}\n|(?<=\n)\*{3,}\n|(?<=\n)={3,}\n', block)
        for s in subs:
            s = s.strip()
            if s:
                paragraphs.append(s)

    if not paragraphs:
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text.strip())
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) < 300:
                current = (current + " " + sent).strip() if current else sent
            else:
                if current:
                    chunks.append(current)
                current = sent
        if current:
            chunks.append(current)
        paragraphs = chunks if chunks else [text.strip()[:500]]

    overlap_chars = 50
    if len(paragraphs) > 1:
        overlapped = [paragraphs[0]]
        for i in range(1, len(paragraphs)):
            prev_tail = paragraphs[i-1][-overlap_chars:].lstrip()
            if prev_tail:
                overlapped.append(prev_tail + " " + paragraphs[i])
            else:
                overlapped.append(paragraphs[i])
        paragraphs = overlapped

    injected = 0
    truncated_count = 0
    for para in paragraphs:
        if len(para) < 10:
            continue

        # Warn on truncation — 500 chars is a lot for a single fact
        if len(para) > 500:
            truncated_count += 1

        embedding = await get_embedding(para[:500])
        importance, emotion = await score_message(para[:500])

        memory = WorkingMemory(
            user_id=user_id,
            message=f"[{source_label}]: {para[:500]}",
            role=role,
            conversation_id=conversation_id,
            embedding=embedding,
            importance_score=importance,
            emotional_valence=emotion,
            timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        await memory_repo.save_working_memory(db, memory)
        injected += 1
        
        if not re.match(r'^(video|image|audio):', source_label):
            try:
                entities = await extract_entities(para[:500])
                for ent in entities:
                    if ent.get("entity_name", "").lower() == ent.get("target_name", "").lower():
                        continue
                    existing = await entity_repo.find_entity_edge(
                        db, user_id, ent.get("entity_name", ""), ent.get("relation", ""), ent.get("target_name", "")
                    )
                    if not existing:
                        entity_mem = EntityMemory(
                            user_id=user_id,
                            entity_name=ent.get("entity_name", ""),
                            entity_type=ent.get("entity_type", "unknown"),
                            relation=ent.get("relation", ""),
                            target_name=ent.get("target_name", ""),
                            target_type=ent.get("target_type", "unknown"),
                            source_message_id=memory.id,
                            conversation_id=conversation_id,
                            confidence=1.0,
                            timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                        )
                        await entity_repo.save_entity(db, entity_mem)
                if entities:
                    invalidate_graph(user_id)
            except Exception:
                pass

    if truncated_count:
        logger.warning(
            f"{truncated_count}/{injected} segments truncated to 500 chars"
        )
    
    return {
        "status": "ingested",
        "source": source_label,
        "segments": injected,
        "conversation_id": conversation_id
    }


async def _analyze_media(file_content: bytes, filename: str, mime_type: str) -> str | None:
    try:
        client = get_client()
        content_to_send = file_content
        mime_to_send = mime_type
        
        if mime_type.startswith('video/'):
            frame_data, frame_mime = _extract_video_frame(file_content)
            if frame_data:
                content_to_send = frame_data
                mime_to_send = frame_mime
        
        data_url = f"data:{mime_to_send};base64,{base64.b64encode(content_to_send).decode()}"
        
        # Use correct content type for the model
        if mime_to_send.startswith('audio/'):
            media_block = {"type": "audio_url", "audio_url": {"url": data_url}}
        elif mime_to_send.startswith('video/'):
            media_block = {"type": "video_url", "video_url": {"url": data_url}}
        else:
            media_block = {"type": "image_url", "image_url": {"url": data_url}}
        
        response = await client.chat.completions.create(
            model=OMNI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this media in 2-3 sentences. For videos: summarize what happens, key actions, people, and setting. For images: describe the visual content, text, and context. For audio: transcribe and summarize."},
                    media_block,
                ]
            }],
            max_tokens=300,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.warning(f"[Media Analysis] Failed for {filename}: {e}")
        return None


def _extract_video_frame(file_content: bytes) -> tuple[bytes | None, str]:
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(file_content)
            video_path = f.name
        
        frame_path = video_path + '.jpg'
        subprocess.run(
            ['ffmpeg', '-y', '-i', video_path, '-vframes', '1', '-q:v', '2', frame_path],
            capture_output=True, timeout=15
        )
        os.unlink(video_path)
        
        if os.path.exists(frame_path):
            with open(frame_path, 'rb') as f:
                frame_data = f.read()
            os.unlink(frame_path)
            return frame_data, 'image/jpeg'
        return None, ''
    except Exception as e:
        logger.warning(f"[Frame Extract] Failed: {e}")
        return None, ''

async def _store_file_in_oss(
    db: AsyncSession, user_id: int, file_content: bytes,
    filename: str, mime_type: str, conversation_id: str,
) -> FileAttachment:
    oss_key = build_oss_key(user_id, conversation_id, filename)
    try:
        upload_file(file_content, oss_key, mime_type)
    except RuntimeError as e:
        logger.warning(f"[OSS] Upload skipped (credentials missing): {e}")
        oss_key = f"local://{filename}"
    
    attachment = FileAttachment(
        user_id=user_id,
        filename=filename,
        oss_key=oss_key,
        file_size=len(file_content),
        file_type=filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin',
        mime_type=mime_type,
        conversation_id=conversation_id,
        status="stored",
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return attachment


def _fmt_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1048576:
        return f"{size_bytes/1024:.1f}KB"
    else:
        return f"{size_bytes/1048576:.1f}MB"


_FILE_ICONS = {
    'mp4': '🎬', 'mov': '🎬', 'avi': '🎬', 'webm': '🎬', 'mkv': '🎬',
    'mp3': '🎵', 'wav': '🎵', 'm4a': '🎵', 'ogg': '🎵',
    'png': '🖼️', 'jpg': '🖼️', 'jpeg': '🖼️', 'gif': '🖼️', 'webp': '🖼️',
    'pdf': '📕', 'txt': '📄', 'md': '📄', 'csv': '📊', 'log': '📋', 'json': '📋',
}


async def _save_display_message(
    db: AsyncSession, user_id: int, conversation_id: str,
    filename: str, ext: str, size_label: str, preview: str = "",
):
    icon = _FILE_ICONS.get(ext, '📎')
    msg = f"{icon} {filename} · {size_label}"
    wm = WorkingMemory(
        user_id=user_id, role="user", message=msg,
        conversation_id=conversation_id, importance_score=0.5, emotional_valence=0.0,
    )
    await memory_repo.save_working_memory(db, wm)


async def ingest_file(
    db: AsyncSession, user_id: int, file_content: bytes,
    filename: str, conversation_id: Optional[str] = None
) -> dict:
    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    MIME = {
        'mp3':'audio/mpeg','wav':'audio/wav','m4a':'audio/mp4','ogg':'audio/ogg',
        'flac':'audio/flac','aac':'audio/aac','mp4':'video/mp4','mov':'video/quicktime',
        'avi':'video/x-msvideo','webm':'video/webm','mkv':'video/x-matroska',
        'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','gif':'image/gif',
        'webp':'image/webp','bmp':'image/bmp','pdf':'application/pdf',
        'txt':'text/plain','md':'text/markdown','csv':'text/csv','log':'text/plain',
        'json':'application/json',
    }
    mime_type = MIME.get(ext, 'application/octet-stream')
    size = _fmt_size(len(file_content))
    
    attachment = await _store_file_in_oss(db, user_id, file_content, filename, mime_type, conversation_id)

    if ext in ('mp3','wav','m4a','ogg','flac','aac','mp4','mov','avi','webm','mkv','png','jpg','jpeg','gif','webp','bmp','pdf'):
        analysis = await _analyze_media(file_content, filename, mime_type)
        preview = (analysis or "")[:200]
        await _save_display_message(db, user_id, conversation_id, filename, ext, size, preview)
        if analysis:
            kind = ext if ext != 'pdf' else 'pdf'
            if ext in ('mp3','wav','m4a','ogg','flac','aac'):
                kind = 'audio'
            elif ext in ('mp4','mov','avi','webm','mkv'):
                kind = 'video'
            elif ext in ('png','jpg','jpeg','gif','webp','bmp'):
                kind = 'image'
            await ingest_text(db, user_id, f"[{kind.capitalize()} analysis: {filename}]\n{analysis}", f"{kind}:{filename}", conversation_id, role="system", whole=True)
        return {"status": "stored", "filename": filename, "file_size": len(file_content), "oss_key": attachment.oss_key, "conversation_id": conversation_id}
    
    if ext in ('txt','md','csv','log'):
        text = file_content.decode('utf-8', errors='replace')
        preview = text[:200] + ("…" if len(text) > 200 else "")
        await _save_display_message(db, user_id, conversation_id, filename, ext, size, preview)
        if ext == 'log':
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            for line in lines:
                embedding = await get_embedding(line)
                importance, emotion = await score_message(line)
                if importance < 0.3:
                    importance = 0.3
                wm = WorkingMemory(
                    user_id=user_id, role="system", message=f"[log]: {line}",
                    conversation_id=conversation_id, embedding=embedding,
                    importance_score=importance, emotional_valence=emotion,
                    timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                )
                await memory_repo.save_working_memory(db, wm)
            logger.info(f"[Log] {len(lines)} lines ingested from {filename}")
        else:
            await ingest_text(db, user_id, text, f"file:{filename}", conversation_id, role="system")
        return {"status": "stored", "filename": filename, "file_size": len(file_content), "oss_key": attachment.oss_key, "conversation_id": conversation_id}
    
    return {"status": "unsupported", "filename": filename, "extension": ext}
