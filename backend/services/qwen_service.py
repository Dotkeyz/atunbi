from openai import AsyncOpenAI
from core.config import QWEN_API_KEY, QWEN_BASE_URL
from dashscope import MultiModalConversation
import asyncio
import base64
import dashscope
import fitz
import json
import os
import re
import shutil
import subprocess
import tempfile
import logging

logger = logging.getLogger("atunbi.qwen")

_client = None


def get_client():
    global _client
    if _client is None:
        if not QWEN_API_KEY:
            raise ValueError("QWEN_API_KEY is missing from environment variables.")
        _client = AsyncOpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    return _client

CHAT_MODELS = [
    {"name": "qwen-plus-latest",        "context_window": 131_072},
    {"name": "qwen3.5-omni-flash",      "context_window": 131_072},
    {"name": "qwen-omni-turbo",         "context_window": 131_072},
    {"name": "qwen-turbo",              "context_window": 1_000_000},
]

OMNI_MODEL = "qwen3.5-omni-flash"

def estimate_tokens(text: str) -> int:
    """Rough token estimation: 1 token ≈ 3.5 characters."""
    if not text: return 0
    return int(len(text) / 3.5)

def truncate_context_to_budget(context: str, system_prompt: str, user_prompt: str, model_context_window: int) -> str:
    """
    Dynamically truncates context (keeping the newest messages) so the total payload 
    fits within the specific model's context window.
    """
    # Reserve 20% of the window for the AI's response generation
    max_input_tokens = int(model_context_window * 0.80)
    
    sys_tokens = estimate_tokens(system_prompt)
    user_tokens = estimate_tokens(user_prompt)
    
    available_for_context = max_input_tokens - sys_tokens - user_tokens
    
    if available_for_context <= 0:
        return "" # System + User prompt alone exceeds the window (unlikely but safe)
        
    current_context_tokens = estimate_tokens(context)
    if current_context_tokens <= available_for_context:
        return context # It fits perfectly, no truncation needed
        
    # Truncate from the top (oldest messages) to preserve recent continuity
    lines = context.split('\n')
    kept_lines = []
    kept_tokens = 0
    
    for line in reversed(lines):
        line_tokens = estimate_tokens(line + "\n")
        if kept_tokens + line_tokens > available_for_context:
            break
        kept_lines.insert(0, line)
        kept_tokens += line_tokens
        
    logger.info(f"[Truncation] Context trimmed from {current_context_tokens} to {kept_tokens} tokens to fit {model_context_window:,} window.")
    return '\n'.join(kept_lines)

async def get_embedding(text: str) -> list[float]:
    client = get_client()
    response = await client.embeddings.create(
        input=text,
        model="text-embedding-v4", 
        dimensions=1536            
    )
    return response.data[0].embedding

async def score_message(text: str) -> tuple[float, float]:
    """Rate a message's importance (0-1) and emotional valence (-1 to 1) in a single API call.
    Uses qwen-flash — fastest model for structured classification output."""
    client = get_client()
    response = await client.chat.completions.create(
        model="qwen-flash",
        messages=[
            {"role": "system", "content": """Rate this message on two dimensions. Reply with ONLY two numbers separated by a comma: importance,emotion

IMPORTANCE (0.0 to 1.0):
0.8-1.0: Critical — identity statements (who you are, where you live, what you do), corrections to previous statements ("i'm no longer", "i don't", "actually i"), decisions, constraints, personal facts. Negations and updates to identity are ALWAYS critical.
0.5-0.7: Valuable — explanations, code snippets, domain knowledge, opinions, plans, substantive questions
0.2-0.4: Contextual — follow-ups that advance the conversation, clarifications, general discussion
0.0-0.1: Low-value — greetings, filler words, simple acknowledgments ("ok", "thanks")

EMOTION (-1.0 to 1.0):
-1.0: Strongly negative — frustration, anger, disappointment, stress
-0.5: Mildly negative — concern, confusion, dissatisfaction
 0.0: Neutral — factual, informational, technical
 0.5: Mildly positive — satisfaction, interest, curiosity
 1.0: Strongly positive — excitement, gratitude, enthusiasm"""},
            {"role": "user", "content": text}
        ],
        temperature=0.1,
        max_tokens=20
    )
    try:
        parts = response.choices[0].message.content.strip().split(",")
        importance = float(parts[0].strip())
        emotion = float(parts[1].strip())
        return importance, emotion
    except Exception:
        return 0.5, 0.0


async def score_importance(text: str) -> float:
    importance, _ = await score_message(text)
    return importance

async def score_emotion(text: str) -> float:
    _, emotion = await score_message(text)
    return emotion

async def summarize_episode(conversation_text: str) -> str:
    client = get_client()
    response = await client.chat.completions.create(
        model="qwen-max",
        messages=[
            {"role": "system", "content": "Summarize this conversation in 2-4 sentences. Capture the key topics, decisions made, and any user preferences revealed. Write in past tense."},
            {"role": "user", "content": conversation_text}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

async def extract_facts(episode_summary: str) -> list[str]:
    """Extract standalone, verifiable facts from an episode summary for SemanticMemory."""
    client = get_client()
    response = await client.chat.completions.create(
        model="qwen-max",
        messages=[
            {"role": "system", "content": "Extract ONLY standalone, verifiable facts from this conversation summary. One fact per line. Each fact must be a single sentence that is true regardless of context. Include: user preferences, technical decisions, constraints, personal information, error solutions. Exclude: greetings, filler, temporary state. Reply with facts only, one per line, no numbering."},
            {"role": "user", "content": episode_summary}
        ],
        temperature=0.1
    )
    facts = [line.strip() for line in response.choices[0].message.content.strip().split('\n') if line.strip()]
    return facts


async def rerank_results(query: str, candidates: list[tuple], top_n: int = 50) -> list[tuple]:
    """
    Cross-encoder rerank: feed each candidate + query to a cheap LLM for binary relevance.
    Returns all candidates marked relevant. Early termination prevents cost runaway.
    """
    if not candidates:
        return []
    
    client = get_client()
    to_check = list(candidates)
    
    async def check_relevance(candidate: tuple) -> tuple[tuple, bool]:
        mem, _ = candidate
        text = getattr(mem, 'message', getattr(mem, 'summary', getattr(mem, 'fact', '')))
        snippet = text[:300]
        
        try:
            response = await client.chat.completions.create(
                model="qwen-turbo",
                messages=[
                    {"role": "system", "content": "Reply with ONLY 'yes' or 'no'. Is this memory relevant to the user's question? Be generous — if the memory contains analysis of any media (image, video, audio, PDF) the user is asking about, say yes. If the memory mentions topics, people, or content related to the question, say yes."},
                    {"role": "user", "content": f"Question: {query}\nMemory: {snippet}\n\nRelevant? yes/no"}
                ],
                temperature=0.0,
                max_tokens=3
            )
            answer = response.choices[0].message.content.strip().lower().replace('.', '')
            return (candidate, "yes" in answer)
        except Exception:
            return (candidate, True)
    
    # Early termination: stop when signal fades (3+ relevant then 3 consecutive no)
    # or when all noise (8 checked, 0 relevant)
    kept = []
    consecutive_no = 0
    found_relevant = 0
    total_checked = 0
    BATCH_SIZE = 2
    
    for batch_start in range(0, min(len(to_check), 20), BATCH_SIZE):
        batch = to_check[batch_start:batch_start + BATCH_SIZE]
        tasks = [check_relevance(c) for c in batch]
        results = await asyncio.gather(*tasks)
        
        should_stop = False
        for candidate, is_relevant in results:
            total_checked += 1
            if is_relevant:
                kept.append(candidate)
                found_relevant += 1
                consecutive_no = 0
            else:
                consecutive_no += 1
                if consecutive_no >= 3 and found_relevant >= 3:
                    should_stop = True
                    break
        
        if found_relevant == 0 and total_checked >= 8:
            should_stop = True
        
        if should_stop:
            break
        
        # Brief pause between batches to respect rate limits
        await asyncio.sleep(0.2)
    
    return kept

ATUNBI_BASE_PROMPT = """You are Atunbi, an AI with memory. Respond based on context from past conversations. Your tone is warm, precise, and helpful.

---

## READABILITY RULE — ALWAYS FOLLOW THIS

**Every response longer than 3 sentences MUST use visual structure.** This is not optional.

**Numbered steps or sequences:** Use <ol><li> — each step wrapped in its own <li>. NEVER jam steps into a single paragraph.

**Key takeaways:** Wrap in <div class="key-insight"><p>...</p></div>.

**Multiple topics:** Separate with <h3> headings.

**NEVER output a long paragraph with inline <strong> numbering** like "1. **Foo** 2. **Bar**". That is unreadable. Use <ol><li> or <ul><li> instead.

**NEVER output a response that is a single block of text.** If you have more than 3 sentences, use at minimum a <p> per idea with proper spacing.

---

## HOW TO RESPOND

**HOW YOU RESPOND DEPENDS ON WHAT THE USER IS DOING:**

**User shares a fact** ("I use X", "My colleague is Y", "I no longer use Z", "X works at Y"): Acknowledge ONLY the current message. Do NOT circle back to earlier topics — the user has moved on. Do NOT say "let's explore" or "let's dive into" — the user didn't ask a question. One <p> tag, maybe two. No components. No lectures. Do NOT end with a question like "Anything else?" or "Would you like to know more?" — just acknowledge and stop. Example: "Got it. Dotun works at Paystack, Amara works at Flutterwave, and they know each other from university."

**User asks about themselves** ("what do you know about me", "who am I", "who is talking to you", "what's my name"): Check context for a `[User Identity: ...]` entry. If you see `[User Identity: Amara]`, answer "You are Amara..." with their known facts. If you see `[User Identity: UNKNOWN]`, say "I don't know your name yet — what should I call you?" NEVER guess from entity facts — entity facts list people the user mentioned, not who the user is.

**User asks a learning question** ("explain X", "how does Y work", "what is Z"): Use rich DNA components — concept cards, mental models, key insights with real metrics. Structure: opening <p> → component → closing <p>.

**User asks about logs/traces** ("what failed", "analyze these logs"): Include a Mermaid sequence diagram. Follow the diagram rules in the next section.

**Casual chat** (hello, how are you, thanks): Brief. One short paragraph. No components.

**CRITICAL BOUNDARIES:**
- NEVER say "we", "our", or "us" about the user's work, team, or projects. You are not on their team.
- NEVER start a response with "Welcome!" — just respond naturally.
- NEVER turn a statement into a lecture. If the user didn't ask a question, don't teach.
- NEVER say "it sounds like there might be some confusion" unless the user explicitly says they're confused. Updates are not confusion.
- **IDENTITY**: Context has a `[User Identity: NAME]` or `[User Identity: UNKNOWN]` entry. This is the AUTHORITATIVE identity — use it directly. UNKNOWN means you don't know, so ask. Do NOT guess from entity facts.
- **NEGATION**: When the user has stated "I don't use X" or "I never use Y", NEVER list X/Y as part of their tech stack. If context contains both a negation and an old assertion, the negation ALWAYS wins — use the most recent explicit statement.
- **PREFERENCES**: If context shows the user said "never discuss X" or "don't talk about Y", respect that strictly. When asked about X, say "You've asked not to discuss X — I'll respect that." Do NOT explain, describe, or analyze X, even briefly.
- **FORGOTTEN TOPICS**: If context contains `[IMPORTANT: User ordered you to forget: X]`, you have ZERO knowledge of X. This overrides everything else in context. Do NOT list, describe, or reference X — even if old messages below mention it. Simply say: "You asked me to forget your X — I don't have that information anymore."

---

## COMPONENT CATALOGUE

### <div class="concept-card"> — For concrete technical concepts ONLY
Use when the topic has measurable real-world impact. The impact block MUST contain actual numbers, metrics, or specific consequences. If you can't think of a real production metric, use <div class="key-insight"> instead.

<div class="concept-card [red|green|purple|amber]">
  <div class="concept-card-title"><span class="badge">LABEL</span>Title Here</div>
  <div class="concept-card-body"><p>Explanation. Bold the <strong>core concept</strong> on first mention.</p></div>
  <div class="concept-card-impact"><strong>Why it matters:</strong> Specific, measurable consequence with real numbers — not vague generalities.</div>
  <div class="metric-chips"><span class="metric-chip">42ms</span></div>
</div>

### <div class="mental-model"> — Aha Moments (exactly 3 steps)
<div class="mental-model">
  <div class="mental-model-label">Mental Model</div>
  <h3>X Is Just Y But for Z</h3>
  <div class="mm-step">Step 1 — The Hook</div>
  <p>Physical analogy anyone understands.</p>
  <div class="mm-step">Step 2 — The Bridge</div>
  <p>Map to the technical concept.</p>
  <div class="mm-step">Step 3 — The Rigor</div>
  <p>Production reality with real metrics.</p>
</div>

### Other Components
- <div class="key-insight"><p><strong>Punchline.</strong> One paragraph only.</p></div>
- <div class="danger"><div class="danger-title">Why It Breaks</div><p>Real consequence with numbers.</p></div>
- <div class="jb"><div class="jb-label">Jargon — Term</div><p>Definition in plain English.</p></div>
- <div class="reveal-answer"><div class="reveal-answer-label">The Right Way</div><p>The fix, with reasoning.</p></div>
- <h2 class="section-title">Section Heading</h2>
- <ul class="bullet-list"><li><strong>Term</strong>: explanation</li></ul>
- <div class="summary-box"><p>The one thing to remember.</p></div>

### <pre class="cblock"><code> — Code/Logs/Traces
<pre class="cblock"><code>
<span class="kw">SELECT</span> <span class="fn">COUNT</span>(*) <span class="kw">FROM</span> users;
<span class="cmt">-- Always wrap in cblock</span>
</code></pre>
Syntax classes: kw (keyword), str (string), cmt (comment), fn (function), type (type), num (number).

---

## RULES
- Speak naturally. You are Atunbi, a helpful memory assistant — not a data analyst. Never mention "the entity graph", "the database", "the context", or any internal system. Never say "we" or "our" about the user's work. If you notice an inconsistency in stored data, handle it silently — the user doesn't need to know.
- Structure learning responses: opening <p> → component → closing <p>. Plain paragraphs for framing, components for the core concept.
- Concept cards need REAL production metrics. "Every modern technology relies on physics" is too vague — use specific numbers (e.g., "transistors switch at 10⁻¹² seconds") or skip the impact block. For abstract/foundational topics, prefer <div class="key-insight"> or <div class="mental-model"> over concept cards.
- NEVER use markdown (#, ##, **, *, `, ```). Pure HTML only.
- <strong> for key facts and terms. <code> for inline technical references.
- All code/logs/traces MUST be in <pre class="cblock"><code> with syntax spans.
- Never <h1>. Never quizzes or knowledge checks.
- Use "you." Be conversational when appropriate, deep when needed.
- **Empty context rule:** If context contains "[MEMORY: No stored memories found":
  - General knowledge question ("what is X?", "explain Y") → answer from training normally.
  - Memory recall question ("what did I say about X?", "remember when we...") → be honest that you don't have it in memory.
  - Do NOT use the same phrase every time. Vary your wording naturally.
- **Vague query rule:** If the user is ambiguous ("tell me again", "recap", "what did we discuss") and context doesn't make it clear, ASK for clarification. List relevant topics from context. Example: "We've discussed log files, videos, and documents — which would you like me to recap?"
- If context DOES contain relevant past messages, use them. Answer memory questions directly from context.
- **Log/trace analysis:** When the context includes service-to-service log lines and the user asks what failed or why something broke, include a Mermaid sequence diagram showing the flow. For other diagram requests (architecture, processes, decision trees), use flowchart TD or LR.

---

## DIAGRAMS

### When to use which type
- **Process flows, decision trees, escalation chains:** flowchart TD or LR
- **Message exchanges, request-response, traces:** sequenceDiagram
- **Prefer flowchart** — it's tighter. Sequence only when message direction IS the concept.

### Diagram wrapper (MANDATORY for every diagram)

<!-- prettier-ignore -->
<div style="background:linear-gradient(135deg,var(--dna-surface) 0%,rgba(220,38,38,.03) 100%);border:1px solid var(--dna-border);border-radius:8px;padding:1.5rem 2rem 2.25rem;margin-bottom:1.5rem;box-shadow:var(--dna-shadow-sm)">
<div class="mermaid" style="background:transparent;border:none;padding:0;margin:0;box-shadow:none;max-width:100%">
sequenceDiagram
  participant A as OrderSvc
  participant B as PaySvc
  participant C as PayGW
  A->>B: process payment
  B->>C: authorize
  C--xB: timeout
  B--xA: transaction rolled back
</div>
</div>
<div class="diagram-caption"><span class="diagram-caption-label">Path Trace</span> One plain-English sentence: which service called which, where it failed, the consequence.</div>
<div class="diagram-takeaway"><strong>The failure started at [ServiceName].</strong> One sentence: what tripped, what rolled back, what queued for retry.</div>

### Flowchart template
Use for processes, decision trees, architecture:

<!-- prettier-ignore -->
<div class="mermaid" style="background:transparent;border:none;padding:0;margin:0;box-shadow:none;max-width:100%">
flowchart TD
  A[Start] --> B[Process]
  B --> C{Decision?}
  C -->|Yes| D[Outcome A]
  C -->|No| E[Outcome B]
</div>

### Mermaid syntax rules
- The .mermaid div MUST contain ONLY raw mermaid text. NO HTML tags. NO <code>. NO markdown fences. NO triple backticks.
- Every statement on its own line with real newlines (\n, not <br>)
- Single-letter aliases: participant A as OrderSvc (not "participant OrderSvc")
- Short display names after "as": OrderSvc not "Order Service Instance 42"
- Sequence arrows: A->>B: label (forward) or A--xB: label (failure/timeout). NEVER use --> or -->>.
- Flowchart arrows: A --> B (flow), A -->|label| B (labeled edge)
- Flowchart nodes: A[Rectangle] for steps, B{Diamond} for decisions
- NEVER circle nodes (( )) — use rectangles
- Single-line labels only — no <br> in node text
- Max 5 participants for sequence, max 8 nodes for flowchart
- NEVER output placeholder text like "mermaid" or "diagram" — either produce valid mermaid code or skip entirely

## TOOLS
You have access to internal tools. To use a tool, output this EXACT format ON ITS OWN LINE — nothing else before or after:

[TOOL: tool_name]
{"key": "value"}
[/TOOL]

Available tools:
- search_memory: {"query": "what to search"} — Search all memory tiers
- get_memory_stats: {} — Get memory health and lifecycle breakdown  
- trigger_dream_phase: {} — Consolidate and prune memories
- get_config: {} — Get current memory parameters

Only use tools when the user explicitly asks for something that requires them.
Do NOT wrap tool calls in markdown, code blocks, or any other formatting.

🚨 HTML SYNTAX RULE — READ THIS LAST:
Every tag MUST start with < and end with >. Markdown symbols (# * ` > ```) are FORBIDDEN.
Correct: <div class="concept-card"><div class="concept-card-title">Title</div></div>
Wrong:   concept-card">Title   OR   >Title   OR   **Title**
If you forget the < character, your entire response becomes unreadable garbage.

Now respond based on the context and user message."""


def _render_pdf_pages(file_bytes: bytes, max_pages: int = 5) -> list[bytes]:
    """Render PDF pages as PNG images. Returns list of PNG byte strings."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=150)
            pages.append(pix.tobytes("png"))
        doc.close()
        return pages
    except Exception as e:
        logger.warning(f"[PDF] Render failed: {e}")
        return []


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Extract raw text from all pages of a PDF."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages.append(text.strip())
        doc.close()
        return "\n\n--- Page Break ---\n\n".join(pages)
    except Exception as e:
        logger.warning(f"[PDF] Text extraction failed: {e}")
        return ""


async def _extract_video_frames(file_bytes: bytes, max_frames: int = 5) -> list[bytes]:
    """Extract frames from video as PNG using ffmpeg. Runs in thread pool to avoid blocking."""
    
    def _extract_sync() -> list[bytes]:
        tmpdir = tempfile.mkdtemp()
        try:
            video_path = os.path.join(tmpdir, "input.mp4")
            with open(video_path, "wb") as f:
                f.write(file_bytes)
            
            # Detach from terminal to prevent SIGTTOU in background shell
            spawn_kwargs = {"capture_output": True, "timeout": 10,
                           "stdin": subprocess.DEVNULL,
                           "start_new_session": True}
            
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                **spawn_kwargs, text=True
            )
            duration = float(probe.stdout.strip()) if probe.stdout.strip() else 10.0
            
            # Extract frames sequentially at evenly-spaced timestamps
            interval = max(1.0, duration / max_frames)
            frames = []
            ffmpeg_kwargs = {**spawn_kwargs, "timeout": 15}
            for i in range(max_frames):
                timestamp = min(i * interval + interval / 2, duration - 0.5)
                out_path = os.path.join(tmpdir, f"frame_{i:03d}.png")
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(timestamp), "-i", video_path,
                     "-vframes", "1", "-q:v", "2", out_path],
                    **ffmpeg_kwargs
                )
                if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    with open(out_path, "rb") as f:
                        frames.append(f.read())
            
            return frames
        except Exception as e:
            logger.warning(f"[Video] Frame extraction failed: {e}")
            return []
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    return await asyncio.get_event_loop().run_in_executor(None, _extract_sync)


async def _get_video_duration(file_bytes: bytes) -> float:
    """Get video duration in seconds using ffprobe (thread-pool, non-blocking)."""
    
    def _probe() -> float:
        tmpdir = tempfile.mkdtemp()
        try:
            video_path = os.path.join(tmpdir, "input.mp4")
            with open(video_path, "wb") as f:
                f.write(file_bytes)
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                capture_output=True, text=True, timeout=10,
                stdin=subprocess.DEVNULL, start_new_session=True
            )
            return float(result.stdout.strip()) if result.stdout.strip() else 0.0
        except Exception:
            return 0.0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    return await asyncio.get_event_loop().run_in_executor(None, _probe)


async def _caption_audio(file_bytes: bytes) -> str:
    
    def _call_sync() -> str:
        audio_path = os.path.join(tempfile.mkdtemp(), "audio.wav")
        input_path = os.path.join(os.path.dirname(audio_path), "input.bin")
        try:
            with open(input_path, "wb") as f:
                f.write(file_bytes)
            subprocess.run(
                ["ffmpeg", "-y", "-i", input_path, "-acodec", "pcm_s16le",
                 "-ar", "16000", "-ac", "1", audio_path],
                capture_output=True, timeout=30,
                stdin=subprocess.DEVNULL, start_new_session=True
            )
            
            if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                return ""
            
            with open(audio_path, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode()
            
            dashscope.api_key = QWEN_API_KEY
            dashscope.base_http_api_url = "https://ws-9zp7bircjd0ebac7.ap-southeast-1.maas.aliyuncs.com/api/v1"
            
            # Primary: dedicated ASR model for speech transcription
            response = MultiModalConversation.call(
                model="qwen3-asr-flash-2025-09-08",
                messages=[{
                    "role": "user",
                    "content": [{"audio": f"data:audio/wav;base64,{audio_b64}"}]
                }],
                stream=False
            )
            
            if response.status_code == 200 and response.output and response.output.choices:
                content = response.output.choices[0].message.content
                if isinstance(content, list) and len(content) > 0:
                    # ASR returns [{'text': 'transcription'}, ...]
                    texts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
                    result = "".join(texts).strip()
                    if result:
                        return result
                elif isinstance(content, str) and content.strip():
                    return content.strip()
            
            # Fallback: captioner model for non-speech audio description
            if not response.status_code == 200 or not (isinstance(content, list) and len(content) > 0):
                logger.warning(f"[Audio] ASR returned empty — trying captioner fallback")
                response2 = MultiModalConversation.call(
                    model=OMNI_MODEL,
                    messages=[{
                        "role": "user",
                        "content": [{"audio": f"data:audio/wav;base64,{audio_b64}"}]
                    }],
                    stream=False
                )
                if response2.status_code == 200 and response2.output and response2.output.choices:
                    content2 = response2.output.choices[0].message.content
                    if isinstance(content2, list):
                        texts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content2]
                        return "".join(texts).strip()
                    return str(content2).strip() if content2 else ""
            
            return ""
        except Exception as e:
            logger.warning(f"[Audio] Error: {e}")
            return ""
        finally:
            shutil.rmtree(os.path.dirname(audio_path), ignore_errors=True)
    
    return await asyncio.get_event_loop().run_in_executor(None, _call_sync)


def _parse_and_execute_tools(response_text: str) -> tuple[str, bool]:
    """Detect [TOOL:] blocks in model response, execute tools, return (result_text, had_tools)."""
    
    # Use configured API URL (set in .env or ECS), fallback to localhost for dev
    api_url = os.getenv("ATUNBI_API_URL", "http://localhost:8000")
    
    pattern = re.compile(r'\[TOOL:\s*(\w+)\]\s*\n(.*?)\n\s*\[/TOOL\]', re.DOTALL)
    matches = pattern.findall(response_text)
    
    if not matches:
        return response_text, False
    
    tool_results = []
    for tool_name, args_str in matches:
        try:
            args = json.loads(args_str.strip()) if args_str.strip() else {}
        except json.JSONDecodeError:
            args = {}
        
        result = ""
        try:
            resp = requests.post(
                f"{api_url}/api/v1/tools/call?tool_name={tool_name}",
                json=args,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            if resp.status_code == 200:
                result = json.dumps(resp.json(), indent=2)[:2000]
            else:
                result = f"Tool error: {resp.status_code}"
        except Exception as e:
            result = f"Tool failed: {e}"
        
        tool_results.append(f"[Tool Result: {tool_name}]\n{result}")
    
    # Replace tool calls with results in the response
    clean = pattern.sub('', response_text).strip()
    return (clean + "\n\n" + "\n\n".join(tool_results)) if clean else "\n\n".join(tool_results), True


async def generate_stream(context: str, user_message: str, temperature: float = 0.7, media_file: str = None, system_prompt: str | None = None):
    client = get_client()
    user_prompt = f"User's message: \"{user_message}\"\n\nYour Response:"
    content_built = False
    
    if media_file:
        file_data = _file_store.get(media_file)
        if file_data and file_data[1].startswith('audio/'):
            media_file = None
        
        if file_data:
            file_bytes, mime_type = file_data
            ext = media_file.rsplit('.', 1)[-1].lower() if '.' in media_file else 'bin'
            file_b64 = base64.b64encode(file_bytes).decode('utf-8')
            
            if mime_type.startswith('image/'):
                media_part = {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{file_b64}"}}
            elif mime_type.startswith('video/'):
                # Extract frames (visual) + transcribe audio (ASR) in parallel
                frames, transcript = await asyncio.gather(
                    _extract_video_frames(file_bytes, max_frames=8),
                    _caption_audio(file_bytes)
                )
                if frames:
                    timestamp_labels = []
                    frame_images = []
                    probe = await _get_video_duration(file_bytes)
                    interval = max(1.0, probe / max(len(frames), 1)) if probe > 0 else 10
                    for i, f in enumerate(frames):
                        ts = i * interval + interval / 2
                        m, s = int(ts // 60), int(ts % 60)
                        timestamp_labels.append(f"[{m}:{s:02d}]")
                        frame_images.append(
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(f).decode('utf-8')}"}}
                        )
                    transcript_block = f"\n[Audio Transcript]:\n{transcript}" if transcript else ""
                    video_context = (
                        f"[Video: {media_file} — {len(frames)} frames at {' '.join(timestamp_labels)}.]"
                        f"{transcript_block}"
                    )
                    user_content = [
                        {"type": "text", "text": f"Context:\n{video_context}\n{context}\n\n{user_prompt}"}
                    ] + frame_images
                    content_built = True
                media_part = None
            elif mime_type.startswith('audio/'):
                # ASR model transcribes speech; falls back to captioner for non-speech audio
                transcript = await _caption_audio(file_bytes)
                if transcript:
                    user_content = [{"type": "text", "text": f"Context:\n[Audio Transcript — {media_file}]:\n{transcript}\n{context}\n\n{user_prompt}"}]
                    content_built = True
                media_part = None
            elif mime_type == 'application/pdf':
                pages = _render_pdf_pages(file_bytes)
                if pages:
                    page_images = [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(p).decode('utf-8')}"}}
                        for p in pages
                    ]
                    user_content = [{"type": "text", "text": f"Context:\n{context}\n\n{user_prompt}"}] + page_images
                    content_built = True
                media_part = None
            else:
                media_part = None
            
            if not content_built:
                if media_part:
                    user_content = [
                        {"type": "text", "text": f"Context:\n{context}\n\n{user_prompt}"},
                        media_part
                    ]
                else:
                    user_content = f"Context:\n{context}\n\n{user_prompt}"
        else:
            user_content = f"Context:\n{context}\n\n{user_prompt}"
    else:
        user_content = f"Context:\n{context}\n\n{user_prompt}"
    
    last_error = None
    for model_config in CHAT_MODELS:
        model_name = model_config["name"]
        ctx_window = model_config["context_window"]
        
        safe_context = truncate_context_to_budget(context, system_prompt or ATUNBI_BASE_PROMPT, user_prompt, ctx_window)
        if not media_file:
            user_content = f"Context:\n{safe_context}\n\n{user_prompt}"
        
        try:
            logger.info(f"[Model] Attempting stream with: {model_name} (Window: {ctx_window:,})")
            stream = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt or ATUNBI_BASE_PROMPT},
                    {"role": "user", "content": user_content}
                ],
                temperature=temperature,
                stream=True
            )
            
            # Stream tokens immediately while collecting for tool-call detection
            full_response = ""
            async for chunk in stream:
                if hasattr(chunk, 'usage') and chunk.usage:
                    logger.info(f"[Tokens] {model_name} | Prompt: {chunk.usage.prompt_tokens} | Comp: {chunk.usage.completion_tokens} | Total: {chunk.usage.total_tokens}")
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    yield token
            
            # Check for tool calls and execute if found
            final_text, had_tools = _parse_and_execute_tools(full_response)
            if had_tools:
                logger.info(f"[Tools] Executed tools — feeding results back to model")
                # Feed tool results back to model for a final response
                stream2 = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt or ATUNBI_BASE_PROMPT},
                        {"role": "user", "content": user_content},
                        {"role": "assistant", "content": full_response},
                        {"role": "user", "content": f"Tool results:\n{final_text}\n\nBased on these results, provide your answer."}
                    ],
                    temperature=temperature,
                    stream=True
                )
                async for chunk in stream2:
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        yield chunk.choices[0].delta.content
                    
            return 
            
        except Exception as e:
            last_error = e
            logger.warning(f"[Model] {model_name} failed: {str(e)}. Trying next fallback...")
            continue
            
    raise Exception(f"All models failed. Last error: {last_error}")
