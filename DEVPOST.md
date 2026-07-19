## Inspiration

Most AI memory systems are dumping grounds. You throw everything in — every message, every greeting, every "okay" — and nothing ever leaves. The vector database bloats. Retrieval quality degrades. And because nothing gets forgotten, nothing stands out.

The human brain doesn't work this way. It forgets what doesn't matter. It holds on to what does. It detects contradictions. It consolidates during sleep. It earns its memories.

I wanted to know: _can we build a memory system that actually works like the human brain?_

The name **Àtúnbí** is Yoruba for "reborn." Because in this system, every memory gets an opportunity to earn its right to survive — and if it doesn't, it's either reborn into something permanent or let go.

## What It Does

Àtúnbí is a cognitive memory platform that ingests information in any format — voice notes, PDFs, images, text, log files — and builds a self-maintaining knowledge graph that persists across conversations, catches contradictions, and surfaces connections a human would miss.

**The demo shows a doctor tracking two patients.** After each consult, he summarizes into Àtúnbí. The system transcribes his voice, extracts entities (patient names, medications, lab values), connects them in a graph, and — critically — catches a medication dose change. When one patient's labs come back worse and the other shows diabetes risk factors, the system connects them across conversations.

But the architecture is domain-agnostic. The same pipeline that connects diabetic patients also reads server logs and identifies cascading failures.

Key capabilities:

- **Omnichannel ingestion**: voice (ASR), PDFs/images (vision), text, logs
- **Entity extraction with contradiction detection**: catches when a medication dose changes
- **5-tier memory**: Working → Episodic → Semantic → Entity Graph → Structural Gaps
- **Adaptive lifespan**: every memory earns its life via $importance \times 24h + access\_count \times 6h + |emotion| \times 4h$
- **Agentic retrieval loop**: 5-step reasoning — rewrite, hybrid search, graph traversal, gap detection, generation
- **Nightly Dream Phase**: serverless consolidation that prunes noise, archives signal, extracts permanent facts

## How I Built It

**Models.** Five Qwen models, each chosen for a specific cognitive task:

| Model                | Role                                        |
| -------------------- | ------------------------------------------- |
| `qwen3-asr-flash`    | Speech-to-text transcription                |
| `qwen3.5-omni-flash` | PDF and image visual description            |
| `text-embedding-v4`  | 1536-dimensional vector embeddings          |
| `qwen-flash`         | Importance and emotion scoring              |
| `qwen-plus-latest`   | Entity extraction (the hardest NLP task)    |
| `qwen-turbo`         | Query rewriting and cross-encoder reranking |
| `qwen-max`           | Episode summarization (nightly Dream Phase) |

**Backend.** FastAPI (Python 3.11) with async PostgreSQL via SQLModel. Hybrid RRF search across 4 parallel queries (vector on three memory tiers + PostgreSQL full-text keyword), fused at k=60 with recency decay. Cross-encoder reranker for binary relevance filtering with early termination. NetworkX MultiDiGraph for entity relationship traversal with bidirectional BFS.

**Frontend.** Next.js 16 with static export, served by Nginx in the same Docker container. Real-time SSE stats streaming. Click-to-zoom Mermaid diagrams for entity graph visualization. Waveform animation during voice recording.

**Infrastructure.** Single Docker container on Alibaba Cloud ECS. ApsaraDB RDS (PostgreSQL 15 + pgvector). OSS for file storage. Function Compute for the nightly Dream Phase, triggered by EventBridge — costs scale to zero when users sleep.

## Challenges

**Entity extraction was silently failing for two days.** The `extract_entities()` function returns a dict with keys `entities`, `contradictions`, and `needs_clarification` — but the ingestion code was iterating over the dict itself as if it were the entities list. Every entity for every recording was silently discarded. The bug was invisible because the `except: pass` block swallowed the error. Adding structured logging revealed `'str' object has no attribute 'get'` — the code was iterating over dict keys, not entity objects.

**ASR transcripts broke entity validation.** The entity validator required both entity_name and target_name to contain at least one uppercase letter (proper noun filter). ASR transcripts from `qwen3-asr-flash` return lowercase text ("metformin", not "Metformin"). This silently rejected all entities from voice notes. The fix: only enforce the uppercase rule on entity_name, not target_name.

**Mermaid diagrams stopped rendering mid-session.** A find-and-replace operation accidentally duplicated the `style="..."` attribute inside `.mermaid` divs, breaking the HTML structure. Mermaid couldn't find valid diagram code and silently produced zero SVGs. Required DOM inspection to catch the malformed tags.

**Turbopack's `??` vs `||` in production.** The frontend's API URL used `process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"`. An empty string `""` is falsy in JavaScript, causing production requests to fall through to localhost. Changed to the nullish coalescing operator `??` which only falls through on `null` or `undefined`.

## What's Next

- **MCP server integration** for Claude, Cursor, and VS Code
- **Multi-user entity sharing** — what if a team's collective knowledge graph could detect contradictions across members?
- **Streaming Dream Phase UI** — real-time visualization of memory consolidation
- **Configurable domain packs** — pre-tuned lifespan parameters for healthcare, legal, DevOps, and research

## Accomplishments That I'm Proud Of

**The adaptive lifespan formula actually works.** A 0.9-importance identity fact with 12 retrievals earns 93.6 hours of life. A 0.1-importance greeting earns 2.4 hours. That's a 23× gap — and it's not hardcoded. It's three signals multiplied by configurable weights. Move a slider, reshape the entire memory landscape instantly. No migration. No downtime. Derived state is the real deal.

**Entity extraction from voice notes.** Getting `qwen3-asr-flash` to transcribe, then `qwen-plus-latest` to extract structured relationships, then `_validate_entity` to filter properly, then saving to a NetworkX graph — all from a 30-second browser recording — was the hardest integration in the project. Every piece of that pipeline broke at some point. Seeing Ada, metformin, lisinopril, and HbA1c all connected in the entity graph for the first time was the moment I knew it worked.

**5 Qwen models, 5 distinct jobs.** I didn't use a single "God Model." Every cognitive task routes to the most efficient model for that task. ASR goes to a dedicated speech model. Entity extraction uses the most expensive model because a bad entity poisons the entire graph. Scoring uses the cheapest model because it runs on every message. Reranking uses the fastest model because it checks up to 20 candidates per search. This routing discipline is what keeps the system fast and affordable.

**The Dream Phase runs on serverless infrastructure that scales to zero.** EventBridge triggers Function Compute once per night. It evaluates every memory against the lifespan formula, prunes noise, summarizes signal with `qwen-max`, extracts permanent facts with `qwen-flash`, and shuts down. No always-on compute. No idle costs. Just consolidation that happens while users sleep — exactly like the human brain.

## What I Learned

**Silent failures are the most dangerous bugs.** The entity extraction bug — iterating over a dict instead of its `entities` key — was caught by a bare `except: pass`. No error log. No crash. Just five perfectly extracted entities silently discarded every time. I learned to never use bare except blocks, to log at every gate, and to test the full pipeline end-to-end before trusting any intermediate output.

**ASR transcripts and validation rules don't mix.** The entity validator's uppercase requirement was designed for typed chat where users capitalize proper nouns. Voice transcripts are lowercase by default. A single validation rule silently rejected every entity from every recording until we caught it. Domain assumptions that hold for one input modality don't automatically hold for another.

**Mermaid is powerful but fragile.** A single malformed HTML attribute inside a `.mermaid` div silently breaks all diagram rendering with zero console errors. I learned to inspect the DOM directly — SVG count, foreignObject content — rather than trusting visual output. What looks rendered might be a cached screenshot.

**Derived state is worth the complexity.** Computing lifecycle state from the formula on every request, rather than storing a status column, eliminated an entire class of migration problems. Changing the active window from 6 hours to 2 hours is a single config update — not a table scan of 30,000 rows. This pattern will carry forward to every future project.

## What's Next

- **MCP server integration** for Claude, Cursor, and VS Code — Àtúnbí already exposes memory tools via MCP. The next step is full integration with developer workflows.
- **Multi-user entity sharing** — what if a team's collective knowledge graph could detect contradictions across members? "Amara said the deadline is Friday, but Dotun's notes say Wednesday."
- **Streaming Dream Phase UI** — real-time visualization of memory consolidation as it happens, not just a stats counter after the fact.
- **Configurable domain packs** — pre-tuned lifespan parameters and extraction prompts for healthcare, legal, DevOps, and research. Different domains value memories differently.
