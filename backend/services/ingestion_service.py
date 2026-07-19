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
from services.qwen_service import get_embedding, score_message, get_client, OMNI_MODEL, _caption_audio, _render_pdf_pages, _extract_pdf_text
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
        # Store as one memory — the caller has already determined this
        # should not be chunked (documents, transcripts).
        para = text.strip()
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
        paragraphs = chunks if chunks else [text.strip()[:4000]]  # fallback

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
    max_chunk = 4000 if source_label == "document" else 500
    for para in paragraphs:
        if len(para) < 10:
            continue

        if len(para) > max_chunk:
            truncated_count += 1

        embedding = await get_embedding(para[:max_chunk])
        importance, emotion = await score_message(para[:max_chunk])

        memory = WorkingMemory(
            user_id=user_id,
            message=f"[{source_label}]: {para[:max_chunk]}",
            role=role,
            conversation_id=conversation_id,
            embedding=embedding,
            importance_score=importance,
            emotional_valence=emotion,
            timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
        await memory_repo.save_working_memory(db, memory)
        injected += 1
        
        if not re.match(r'^(video|image):', source_label):
            try:
                result = await extract_entities(para[:500])
                entities = result.get("entities", []) if isinstance(result, dict) else []
                for ent in entities:
                    en = ent.get("entity_name", "")
                    rel = ent.get("relation", "")
                    tn = ent.get("target_name", "")
                    if en.lower() == tn.lower():
                        continue
                    existing = await entity_repo.find_entity_edge(db, user_id, en, rel, tn)
                    if not existing:
                        entity_mem = EntityMemory(
                            user_id=user_id,
                            entity_name=en,
                            entity_type=ent.get("entity_type", "unknown"),
                            relation=rel,
                            target_name=tn,
                            target_type=ent.get("target_type", "unknown"),
                            source_message_id=memory.id,
                            conversation_id=conversation_id,
                            confidence=1.0,
                            timestamp=datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
                        )
                        await entity_repo.save_entity(db, entity_mem)
                if entities:
                    invalidate_graph(user_id)
            except Exception as e:
                logger.warning(f"[Entity Save] Failed for source={source_label}: {e}")

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
        
        # Extract text from PDFs directly — avoids vision model hallucination on
        # numbers. Falls back to page rendering for image-only PDFs.
        if mime_type == 'application/pdf':
            pdf_text = _extract_pdf_text(file_content)
            
            if pdf_text and len(pdf_text.strip()) > 100:
                response = await client.chat.completions.create(
                    model="qwen-plus-latest",
                    messages=[{
                        "role": "user",
                        "content": (
                            "Extract ALL lab values, numbers, dates, and findings from this report. "
                            "Return them as a structured summary. Be exact — do not change any numbers. "
                            "Include: test name, result value, reference range, units, and any flags (HIGH/LOW).\n\n"
                            f"{pdf_text}"
                        ),
                    }],
                    max_tokens=1500,
                )
                return response.choices[0].message.content
            
            # Image-only PDF fallback
            pages = _render_pdf_pages(file_content)
            if pages:
                page_images = [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(p).decode()}"}}
                    for p in pages
                ]
                response = await client.chat.completions.create(
                    model=OMNI_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Read this document carefully. Extract all data values, numbers, dates, lab results, and key findings. Be thorough and exact — do not change any numbers."},
                            *page_images,
                        ]
                    }],
                    max_tokens=1000,
                )
                return response.choices[0].message.content
            return None
        
        data_url = f"data:{mime_to_send};base64,{base64.b64encode(content_to_send).decode()}"
        
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
        is_audio = ext in ('mp3','wav','m4a','ogg','flac','aac')
        is_video = ext in ('mp4','mov','avi','webm','mkv')
        is_visual = ext in ('png','jpg','jpeg','gif','webp','bmp')
        is_webm = ext == 'webm'

        transcript = None
        if is_audio or is_webm:
            try:
                transcript = await _caption_audio(file_content)
            except Exception as e:
                logger.warning(f"[Ingest] Transcription failed for {filename}: {e}")
        elif is_video:
            try:
                transcript = await _caption_audio(file_content)
            except Exception:
                pass

        visual_analysis = None
        if is_visual or (is_video and not is_webm) or ext == 'pdf':
            visual_analysis = await _analyze_media(file_content, filename, mime_type)

        parts = []
        if transcript:
            parts.append(f"[Transcript]: {transcript}")
        if visual_analysis:
            parts.append(f"[Visual]: {visual_analysis}")
        analysis = "\n\n".join(parts) if parts else None
        preview = (transcript or visual_analysis or "")[:200]
        
        await _save_display_message(db, user_id, conversation_id, filename, ext, size, preview)
        if analysis:
            kind = 'audio' if is_audio else ('video' if is_video else ('image' if is_visual else ext))
            if is_webm and transcript and not visual_analysis:
                kind = 'audio'

            display_text = transcript if (is_audio or is_webm) and transcript else visual_analysis or analysis
            source_label = "voice note" if (is_audio or is_webm) else ("video note" if is_video else ("image" if is_visual else "document"))
            await ingest_text(db, user_id, display_text, source_label, conversation_id, role="user", whole=(kind != 'audio'))
        return {"status": "stored", "filename": filename, "file_size": len(file_content), "oss_key": attachment.oss_key, "conversation_id": conversation_id, "transcript": transcript}
    
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
