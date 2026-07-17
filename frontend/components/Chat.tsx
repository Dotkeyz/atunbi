"use client";
import { useState, useRef, useEffect, memo } from "react";
import { streamChat, getConversationMessages } from "@/lib/api";
import { Send, BrainCircuit, Upload, Loader2, Check, Square, FileText, Image, Video, File } from "lucide-react";
import { API_URL, ACCEPTED_INPUT_TYPES } from "@/lib/constants";
import AgentTrace from "@/components/AgentTrace";

type AgentStep = { action: string; detail: string; count?: number; paths?: Array<{from: string; relation: string; to: string; depth: number}>; mermaid?: string; variants?: string[]; entities?: string[]; snippets?: string[]; preview?: string[] };
type Message = { role: string; content: string; attachment?: FileAttachment; agentSteps?: AgentStep[] };
type FileAttachment = { fileName: string; fileType: string; fileSize: number; objectUrl?: string };

function sanitizeResponse(html: string): string {
  let result = html;
  
  result = result.replace(/```mermaid\s*\n([\s\S]*?)```/g, (_, code: string) => {
    const clean = code.trim();
    if (/^(sequenceDiagram|flowchart|graph|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph|mindmap|timeline)\b/m.test(clean)) {
      return `<div class="mermaid">${clean}</div>`;
    }
    return _;
  });
  
  // Wrap bare mermaid code in .mermaid div
  if (!/<div class="mermaid"/.test(result)) {
    const mermaidMatch = result.match(
      /(sequenceDiagram[\s\S]*?)(?=<div class="diagram-caption"|<div class="diagram-takeaway"|<\/div>\s*<div class="diagram-caption"|$)/m
    );
    if (mermaidMatch) {
      const clean = mermaidMatch[1].trim();
      if (/participant\s+\w+|->>|--x/i.test(clean)) {
        result = result.replace(mermaidMatch[1], `<div class="mermaid">${clean}</div>`);
      }
    }
  }
  
  result = result.replace(/<code>\s*mermaid\s*<\/code>/gi, '');
  
  result = result.replace(/<code>mermaid\s*(sequenceDiagram|flowchart\s*(?:TD|LR|TB|RL|BT)?|graph\s*(?:TD|LR|TB|RL|BT)?|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph|mindmap|timeline)\b([\s\S]*?)<\/code>/gi, (_, type: string, body: string) => {
    const code = (type + body).trim();
    if (/^(sequenceDiagram|flowchart|graph|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph|mindmap|timeline)\b/m.test(code)) {
      return `<div class="mermaid">${code}</div>`;
    }
    return _;
  });
  
  result = result.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  result = result.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  result = result.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  
  return result;
}

export default function Chat({ activeConversationId, resetKey, onMessageSent }: { activeConversationId?: string; resetKey?: number; onMessageSent?: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [username, setUsername] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadingFileName, setUploadingFileName] = useState("");
  const [uploadStatus, setUploadStatus] = useState<"idle" | "uploading" | "success" | "failed">("idle");
  const [uploadResult, setUploadResult] = useState("");
  const [agentStep, setAgentStep] = useState("");
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const stopAction = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setIsLoading(false);
    setStreamingContent("");
  };

  const handleUpload = async (file: File) => {
    setUploadStatus("uploading");
    setUploadingFileName(file.name);
    setUploadResult("");
    
    const ext = file.name.split('.').pop()?.toLowerCase() || '';
    const isImage = ['png','jpg','jpeg','gif','webp','bmp'].includes(ext);
    const isVideo = ['mp4','mov','avi','webm','mkv'].includes(ext);
    const isPdf = ext === 'pdf';
    const fileType = isImage ? 'image' : isVideo ? 'video' : isPdf ? 'pdf' : 'file';
    const attachment: FileAttachment = {
      fileName: file.name,
      fileType,
      fileSize: file.size,
      objectUrl: isImage ? URL.createObjectURL(file) : undefined,
    };
    
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    try {
      const token = localStorage.getItem("access_token");
      const form = new FormData();
      form.append("file", file);
      if (conversationId) form.append("conversation_id", conversationId);
      const res = await fetch(`${API_URL}/api/v1/ingest`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
        signal: abortRef.current.signal,
      });
      if (!res.ok) {
        const errText = await res.text().catch(() => "unknown error");
        throw new Error(`${res.status}: ${errText.slice(0, 100)}`);
      }
      const data = await res.json();
      // Capture the conversation_id so subsequent messages stay in the same thread
      if (data.conversation_id && !conversationId) {
        setConversationId(data.conversation_id);
      }
      let resultText: string;
      if (data.status === "ingested") {
        resultText = `${data.segments} segment${data.segments !== 1 ? "s" : ""} from ${file.name} ingested`;
      } else if (data.status === "unsupported") {
        resultText = `${file.name}: format not supported`;
      } else {
        resultText = `${file.name} processed`;
      }
      setUploadResult(resultText);
      setUploadStatus("success");
      setMessages(prev => [...prev, { role: "user", content: resultText, attachment }]);
      if (onMessageSent) onMessageSent();
    } catch (err: any) {
      if (err?.name === "AbortError") { setUploadStatus("idle"); return; }
      setUploadResult(err.message?.slice(0, 80) || "Network error");
      setUploadStatus("failed");
    } finally {
      // Reset file input so selecting the same file again triggers onChange
      if (fileRef.current) fileRef.current.value = "";
      // Auto-dismiss overlay after showing result
      setTimeout(() => setUploadStatus("idle"), 3000);
    }
  };

  useEffect(() => { const u = localStorage.getItem("username"); if (u) setUsername(u); }, []);
  const formattedName = username ? username.charAt(0).toUpperCase() + username.slice(1) : "there";

  // Persist rich metadata (agent steps, attachments) to localStorage per conversation
  const persistMeta = (convId: string, msgs: Message[]) => {
    const meta: Record<number, any> = {};
    msgs.forEach((m, i) => {
      if (m.agentSteps || m.attachment) {
        meta[i] = {};
        if (m.agentSteps) meta[i].agentSteps = m.agentSteps;
        if (m.attachment) meta[i].attachment = m.attachment;
      }
    });
    localStorage.setItem(`atunbi_meta_${convId}`, JSON.stringify(meta));
  };

  // resetKey change = force clear (used by delete/sidebar new chat)
  useEffect(() => {
    setMessages([]);
    setStreamingContent("");
    setAgentStep("");
    setAgentSteps([]);
    setIsLoading(false);
    setConversationId(null);
  }, [resetKey]);

  useEffect(() => {
    if (activeConversationId === undefined) { setMessages([]); setStreamingContent(""); setConversationId(null); return; }
    if (activeConversationId) {
      setIsLoading(true); setStreamingContent("");
      setConversationId(activeConversationId);
      getConversationMessages(activeConversationId).then((d: any) => {
        const msgs = d.messages || [];
        // Restore agent steps + attachments from localStorage
        try {
          const saved = JSON.parse(localStorage.getItem(`atunbi_meta_${activeConversationId}`) || '{}');
          for (let i = 0; i < msgs.length; i++) {
            if (saved[i]) {
              if (saved[i].agentSteps) msgs[i].agentSteps = saved[i].agentSteps;
              if (saved[i].attachment) msgs[i].attachment = saved[i].attachment;
            }
          }
        } catch {}
        setMessages(msgs);
        setIsLoading(false);
      }).catch(() => setIsLoading(false));
    } else { 
      setMessages([]); setStreamingContent(""); setConversationId(crypto.randomUUID()); 
    }
  }, [activeConversationId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, streamingContent]);

  // Auto-save metadata when messages gain agent steps or attachments
  useEffect(() => {
    if (conversationId && messages.length > 0) {
      const hasMeta = messages.some(m => m.agentSteps || m.attachment);
      if (hasMeta) persistMeta(conversationId, messages);
    }
  }, [messages, conversationId]);

  useEffect(() => {
    let cancelled = false;
    async function loadAndRenderMermaid() {
      if (typeof window === "undefined") return;
      // Load Mermaid dynamically from CDN with startOnLoad: false
      if (!(window as any).mermaid) {
        try {
          await new Promise<void>((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
            script.onload = () => resolve();
            script.onerror = () => reject();
            document.head.appendChild(script);
          });
          if ((window as any).mermaid) {
            (window as any).mermaid.initialize({ startOnLoad: false, suppressErrorRendering: true });
          }
        } catch {
          return; // Mermaid failed to load — skip gracefully
        }
      }
      if (cancelled) return;
      const mermaid = (window as any).mermaid;
      if (!mermaid) return;
      const renderMermaid = (el: Element) => {
        let code = (el.textContent || "").trim();
        code = code.replace(/^```[\s\S]*?\n/, '').replace(/\n```$/, '').trim();
        code = code.replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '');
        // Fix: model sometimes outputs mermaid on one line — split at keywords
        if (code.includes('sequenceDiagram') && !code.includes('\n')) {
          code = code
            .replace(/sequenceDiagram\s*/g, 'sequenceDiagram\n')
            .replace(/\s*(participant\s)/g, '\n$1')
            .replace(/\s*(->>|--x)/g, '\n$1')
            .replace(/\s*(Note\s+over|Note\s+right\s+of|Note\s+left\s+of)/g, '\n$1')
            .replace(/\s*(activate|deactivate|loop|end|alt|else|opt|par|and|rect|end\b)/g, '\n$1');
        }
        // Skip if content is just the word "mermaid" (model placeholder)
        if (!code || code === 'Syntax error in text' || code.toLowerCase() === 'mermaid') {
          (el as HTMLElement).style.display = 'none';
          return;
        }
        if (!/^(sequenceDiagram|flowchart|graph|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph|mindmap|timeline)\b/m.test(code)) {
          (el as HTMLElement).style.display = 'none';
          return;
        }
        try {
          (window as any).mermaid.run({ nodes: [el] });
        } catch {
          (el as HTMLElement).innerHTML = '<span style="color:#94a3b8;font-size:11px;font-style:italic">[diagram omitted]</span>';
        }
      };
      // Convert markdown-fenced mermaid in existing DOM to .mermaid divs
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const textNodes: Text[] = [];
      let node;
      while ((node = walker.nextNode())) textNodes.push(node as Text);
      for (const tn of textNodes) {
        if (tn.textContent && tn.textContent.includes('```mermaid')) {
          const div = document.createElement('div');
          div.className = 'mermaid';
          div.textContent = tn.textContent.replace(/```mermaid\s*\n?/g, '').replace(/```/g, '').trim();
          tn.parentNode?.replaceChild(div, tn);
        }
      }
      // Clean up already-processed mermaid divs that show errors
      document.querySelectorAll(".mermaid[data-processed]").forEach(el => {
        const text = (el.textContent || "").trim().replace(/<[^>]+>/g, '');
        if (text === 'Syntax error in text' || text.toLowerCase() === 'mermaid') {
          (el as HTMLElement).innerHTML = '<span style="color:#94a3b8;font-size:11px;font-style:italic">[diagram omitted]</span>';
          el.removeAttribute('data-processed');
        }
      });
      
      // Retry rendering at increasing intervals — DOM may not be ready at 150ms
      const renderAllMermaid = () => {
        document.querySelectorAll(".mermaid:not([data-processed])").forEach(el => renderMermaid(el));
      };
      [150, 400, 1000, 2000].forEach(ms => {
        setTimeout(() => {
          if (cancelled) return;
          requestAnimationFrame(() => renderAllMermaid());
        }, ms);
      });
    }
    loadAndRenderMermaid();
    return () => { cancelled = true; };
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const msg = input.trim();
    setInput("");
    setMessages(prev => [...prev, { role: "user", content: msg }]);
    setIsLoading(true);
    setStreamingContent("\u200B");
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    let full = "";
    let capturedSteps: AgentStep[] = [];  // local accumulator — avoids React state closure bug
    try {
      setAgentStep("");
      setAgentSteps([]);
      const newConvId = await streamChat(msg, conversationId, token => {
        full += token;
        setStreamingContent(full || "\u200B");
      }, abortRef.current.signal, (step) => {
        const label = step.action === "done" ? `ready · ${step.detail}` : `${step.action.replace("_", " ")} · ${step.detail}`;
        setAgentStep(label);
        setAgentSteps(prev => [...prev, step]);
        capturedSteps.push(step);  // local accumulator for completed message
      });
      if (newConvId && !conversationId) {
        setConversationId(newConvId);
      }
      setStreamingContent("");
      const updatedMessages = [...messages, { role: "assistant", content: sanitizeResponse(full), agentSteps: capturedSteps }];
      setMessages(updatedMessages);
      // Save agent steps immediately — don't wait for deferred useEffect
      if (newConvId || conversationId) {
        persistMeta(newConvId || conversationId!, updatedMessages);
      }
      if (onMessageSent) onMessageSent();
    } catch (err: any) {
      if (err?.name !== "AbortError") console.error(err);
      setStreamingContent("");
    } finally { setIsLoading(false); }
  };

  return (
    <div className="flex flex-col h-full bg-[var(--dna-glass)] backdrop-blur-xl rounded-2xl border border-[var(--dna-border)] shadow-2xl relative">
      {/* Upload Overlay — DNA glass-morphism, three states */}
      {uploadStatus !== "idle" && (
        <div className="absolute inset-0 z-50 flex items-center justify-center rounded-2xl overflow-hidden">
          <div className="absolute inset-0 bg-[var(--dna-bg)]/70 backdrop-blur-md" />
          <div className="relative z-10 bg-[var(--dna-surface)] border border-[var(--dna-border)] rounded-2xl shadow-lg px-10 py-8 flex flex-col items-center gap-4 animate-[dna-fade-in_0.3s_ease] max-w-[320px]">
            {/* Uploading state */}
            {uploadStatus === "uploading" && (
              <>
                <div className="relative">
                  <div className="w-14 h-14 rounded-2xl bg-[var(--dna-accent-light)] flex items-center justify-center">
                    <Loader2 size={28} className="text-[var(--dna-accent)] animate-spin" />
                  </div>
                  <div className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-[var(--dna-accent)] flex items-center justify-center">
                    <Upload size={10} className="text-white" />
                  </div>
                </div>
                <div className="text-center">
                  <p className="text-[15px] font-medium text-[var(--dna-text)]">Ingesting file</p>
                  <p className="text-[13px] text-[var(--dna-muted)] mt-1 max-w-[200px] truncate">{uploadingFileName}</p>
                </div>
                <div className="flex gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-[var(--dna-accent)] animate-bounce" style={{animationDelay:'0ms'}}></span>
                  <span className="w-2 h-2 rounded-full bg-[var(--dna-accent)] animate-bounce" style={{animationDelay:'120ms'}}></span>
                  <span className="w-2 h-2 rounded-full bg-[var(--dna-accent)] animate-bounce" style={{animationDelay:'240ms'}}></span>
                </div>
              </>
            )}
            {/* Success state */}
            {uploadStatus === "success" && (
              <>
                <div className="w-14 h-14 rounded-2xl bg-[rgba(22,163,74,.08)] flex items-center justify-center">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                </div>
                <div className="text-center">
                  <p className="text-[15px] font-medium text-[var(--dna-text)]">Ingested</p>
                  <p className="text-[13px] text-[var(--dna-muted)] mt-1 max-w-[260px] leading-snug">{uploadResult}</p>
                </div>
              </>
            )}
            {/* Failed state */}
            {uploadStatus === "failed" && (
              <>
                <div className="w-14 h-14 rounded-2xl bg-[rgba(220,38,38,.06)] flex items-center justify-center">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#dc2626" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </div>
                <div className="text-center">
                  <p className="text-[15px] font-medium text-[var(--dna-text)]">Upload failed</p>
                  <p className="text-[13px] text-[var(--dna-muted)] mt-1 max-w-[260px] leading-snug">{uploadResult}</p>
                </div>
              </>
            )}
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {messages.length === 0 && !streamingContent && (
          <div className="h-full flex flex-col items-center justify-center text-center px-8 py-12">
            <div className="w-20 h-20 rounded-3xl bg-[var(--dna-accent-light)] flex items-center justify-center mb-6 border border-[var(--dna-accent-border)] shadow-lg"><BrainCircuit size={40} className="text-[var(--dna-accent)]" /></div>
            <h1 className="text-[clamp(1.8rem,4vw,2.6rem)] font-semibold bg-gradient-to-r from-indigo-600 to-violet-600 bg-clip-text text-transparent mb-3">Hey {formattedName} 👋</h1>
            <p className="text-sm text-[var(--dna-muted)] max-w-md leading-relaxed">Share a thought. Atunbi remembers what matters and forgets what doesn't — just like your brain.</p>
            <p className="text-[11px] text-[var(--dna-muted)] mt-4">Upload audio, video, images, PDFs, or text — Atunbi reads, watches, and listens.</p>
          </div>
        )}

        {/* Agent Steps — premium DNA styling, shows between user message and response */}

        {/* Completed messages */}
        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} />
        ))}

        {/* Streaming — polished Thinking with smooth fade */}
        {streamingContent && (
          <div className="flex justify-start transition-opacity duration-300" style={{ opacity: streamingContent === "\u200B" ? 1 : 1 }}>
            <div className="chat-bubble-bot max-w-[95%] p-5 rounded-2xl text-sm bg-white text-gray-800 rounded-bl-md border border-gray-200/60 shadow-sm transition-all duration-300">
              {/* Agent Steps — subtle, shows last 3 during streaming */}
              {agentSteps.length > 0 && (
                <div className="-mx-1 -mt-1 mb-3 rounded-lg px-3 py-2 animate-[dna-fade-in_0.3s_ease]">
                  <div className="text-[10px] text-gray-400 flex items-center gap-1.5 mb-1.5">
                    <span className="text-gray-300">◌</span>
                    <span>{agentSteps.length} step{agentSteps.length > 1 ? 's' : ''}: {agentSteps.map(s => s.action.replace('_', ' ')).join(' → ')}</span>
                  </div>
                  {agentSteps.slice(-3).map((step, i) => (
                    <div key={i} className="text-[10px] text-gray-400 pl-4 border-l border-gray-100" style={{ opacity: i === agentSteps.length - 1 ? 0.8 : 0.4 }}>
                      <span className="font-medium text-gray-500">{step.action.replace('_', ' ')}</span>
                      <span className="mx-1.5 text-gray-300">—</span>
                      <span>{step.detail}</span>
                      {step.action === "graph" && step.mermaid && (
                        <div className="mt-2 mb-1 p-2 rounded-lg bg-white/50 border border-gray-100"
                             ref={(el) => {
                               if (el && !el.querySelector('.mermaid') && (window as any).mermaid) {
                                 const container = document.createElement('div');
                                 container.className = 'mermaid';
                                 container.textContent = step.mermaid || '';
                                 el.appendChild(container);
                                 setTimeout(() => (window as any).mermaid.run({ nodes: [container] }), 50);
                               }
                             }}>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {/* Thinking header — fades out once tokens arrive */}
              <div className={`flex items-center gap-2.5 mb-2 transition-opacity duration-300 ${streamingContent !== "\u200B" && streamingContent.length > 20 ? "opacity-0 h-0 mb-0 overflow-hidden" : "opacity-100"}`}>
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-40"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-[var(--dna-accent)]"></span>
                </span>
                <span className="text-[11px] font-medium text-[var(--dna-muted)] tracking-wide uppercase">Thinking</span>
                <span className="flex gap-1 ml-0.5">
                  <span className="w-1 h-1 rounded-full bg-indigo-300 animate-bounce" style={{animationDelay:'0ms'}}></span>
                  <span className="w-1 h-1 rounded-full bg-indigo-300 animate-bounce" style={{animationDelay:'120ms'}}></span>
                  <span className="w-1 h-1 rounded-full bg-indigo-300 animate-bounce" style={{animationDelay:'240ms'}}></span>
                </span>
              </div>
              {/* Streaming text or shimmer placeholder */}
              {streamingContent === "\u200B" ? (
                <div className="space-y-2 animate-pulse">
                  <div className="h-3 bg-gray-100 dark:bg-white/8 rounded-full w-3/4"></div>
                  <div className="h-3 bg-gray-100 dark:bg-white/8 rounded-full w-1/2"></div>
                </div>
              ) : (
                <div
                  className="leading-relaxed atunbi-response text-sm max-h-[280px] overflow-y-auto scroll-smooth animate-[dna-fade-in_0.4s_ease]"
                  ref={(el) => { if (el) el.scrollTop = el.scrollHeight; }}
                >
                  {/* Strip ALL HTML during streaming — partial tags from token splits break rendering.
                      Final messages use sanitizeResponse for proper HTML. */}
                  {streamingContent.replace(/<[^>]*>/g, '').split('\n').map((line, i) => (
                    <span key={i}>{line}{i < streamingContent.split('\n').length - 1 ? <br/> : null}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
      <div className="p-5 border-t border-[var(--dna-border)] bg-[var(--dna-glass)] backdrop-blur-sm rounded-b-2xl">
        <div className="flex gap-3 items-end">
          <textarea
            value={input}
            onChange={e => {
              setInput(e.target.value);
              // Auto-resize
              const el = e.target;
              el.style.height = 'auto';
              el.style.height = Math.min(el.scrollHeight, 160) + 'px';
            }}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Share a thought or drop a file..."
            rows={1}
            className="flex-1 bg-[var(--dna-surface)] text-[var(--dna-text)] px-5 py-3.5 rounded-xl text-sm border border-[var(--dna-border)] focus:outline-none focus:ring-2 focus:ring-[var(--dna-accent)]/50 focus:border-[var(--dna-accent)] placeholder-[var(--dna-muted)] transition shadow-sm resize-none overflow-y-hidden"
            disabled={isLoading}
          />
          <input ref={fileRef} type="file" className="hidden" accept={ACCEPTED_INPUT_TYPES} onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); }} />
          <button onClick={() => fileRef.current?.click()} disabled={isLoading || uploadStatus === "uploading"} className="p-3.5 rounded-xl text-[var(--dna-muted)] hover:text-[var(--dna-accent)] hover:bg-[var(--dna-accent-light)] border border-dashed border-[var(--dna-border)] hover:border-[var(--dna-accent-border)] transition disabled:opacity-50 flex-shrink-0" title="Upload file">
            {uploadStatus === "uploading" ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
          </button>
          {(isLoading || uploadStatus === "uploading") ? (
            <button onClick={stopAction} className="bg-red-500 hover:bg-red-400 text-white p-3.5 rounded-xl transition shadow-lg hover:shadow-xl hover:scale-105 active:scale-95 flex-shrink-0" title="Stop">
              <Square size={18} />
            </button>
          ) : (
            <button onClick={handleSend} disabled={!input.trim()} className="bg-[var(--dna-accent)] hover:bg-[var(--dna-accent)]/90 text-white px-6 py-3.5 rounded-xl transition disabled:opacity-50 shadow-lg hover:shadow-xl hover:scale-105 active:scale-95 flex-shrink-0"><Send size={18} /></button>
          )}
        </div>
      </div>
    </div>
  );
}

// Memoized message bubble with collapsible agent steps
const MessageBubble = memo(({ msg }: { msg: Message }) => {
  const steps = msg.agentSteps;
  const [stepsOpen, setStepsOpen] = useState(false);
  
  return (
    <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[100%] p-5 rounded-2xl text-sm ${
        msg.role === "user"
          ? "chat-bubble-user bg-[var(--dna-accent-light)] text-[var(--dna-text)] rounded-br-md border border-[var(--dna-accent-border)]"
          : `chat-bubble-bot bg-[var(--dna-surface)] text-[var(--dna-text2)] rounded-bl-md border border-[var(--dna-border)]`
      }`}>
        {msg.attachment && <AttachmentCard a={msg.attachment} />}
        {msg.role === "assistant" ? (
          <>
            {/* Agent steps — minimal trigger, AgentTrace overlay */}
            {steps && steps.length > 0 && (
              <>
                <button
                  onClick={() => setStepsOpen(true)}
                  className="mb-3 text-[10px] text-gray-400 hover:text-gray-600 transition-colors flex items-center gap-1"
                >
                  <span className="w-1 h-1 rounded-full bg-gray-300"></span>
                  <span>{steps.length} step{steps.length > 1 ? 's' : ''}</span>
                </button>
                {stepsOpen && <AgentTrace steps={steps} onClose={() => setStepsOpen(false)} />}
              </>
            )}
            <div
              className="atunbi-response"
              dangerouslySetInnerHTML={{ __html: sanitizeResponse(msg.content) }}
            />
          </>
        ) : <p className="whitespace-pre-wrap">{msg.content}</p>}
      </div>
    </div>
  );
});
MessageBubble.displayName = "MessageBubble";

function AttachmentCard({ a }: { a: FileAttachment }) {
  const sizeStr = a.fileSize < 1024 ? `${a.fileSize}B` :
    a.fileSize < 1048576 ? `${(a.fileSize/1024).toFixed(1)}KB` :
    `${(a.fileSize/1048576).toFixed(1)}MB`;
  
  return (
    <div className="mb-3 flex items-start gap-3 p-3 rounded-xl bg-white/60 dark:bg-white/5 border border-[var(--dna-border)]">
      {a.fileType === 'image' && a.objectUrl ? (
        <img src={a.objectUrl} alt={a.fileName} className="w-16 h-16 rounded-lg object-cover border border-[var(--dna-border)]" />
      ) : a.fileType === 'image' ? (
        <div className="w-16 h-16 rounded-lg bg-[var(--dna-accent-light)] flex items-center justify-center"><Image size={24} className="text-[var(--dna-accent)]" /></div>
      ) : a.fileType === 'video' ? (
        <div className="w-16 h-16 rounded-lg bg-amber-50 dark:bg-amber-500/5 flex items-center justify-center"><Video size={24} className="text-amber-500" /></div>
      ) : a.fileType === 'pdf' ? (
        <div className="w-16 h-16 rounded-lg bg-red-50 dark:bg-red-500/5 flex items-center justify-center"><FileText size={24} className="text-red-500" /></div>
      ) : (
        <div className="w-16 h-16 rounded-lg bg-slate-100 dark:bg-white/5 flex items-center justify-center"><File size={24} className="text-[var(--dna-muted)]" /></div>
      )}
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-medium text-[var(--dna-text)] truncate">{a.fileName}</p>
        <p className="text-[11px] text-[var(--dna-muted)] mt-0.5">{sizeStr} · {a.fileType === 'image' ? 'Image' : a.fileType === 'video' ? 'Video' : a.fileType === 'pdf' ? 'PDF Document' : 'File'}</p>
      </div>
    </div>
  );
}
