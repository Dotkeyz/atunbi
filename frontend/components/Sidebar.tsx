"use client";
import { useState, useEffect } from "react";
import { getConversations, deleteConversation } from "@/lib/api";
import { MessageSquare, Clock, Loader2, Plus, Trash2, PanelLeftClose, PanelLeftOpen, FileText, Mic, File } from "lucide-react";

function timeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const seconds = Math.floor((now - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks}w ago`;
  return new Date(dateStr).toLocaleDateString();
}

interface Conversation { id: string; title: string; date: string; message_count?: number; }

function timeGroup(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const hours = (now - then) / (1000 * 60 * 60);
  if (hours < 24) return "Today";
  if (hours < 48) return "Yesterday";
  if (hours < 168) return "This Week";
  if (hours < 720) return "This Month";
  return "Older";
}

// Pick icon based on conversation title patterns
function getConvIcon(title: string) {
  const lower = title.toLowerCase();
  if (lower.includes(".pdf") || lower.startsWith("📄") && lower.includes("pdf")) return FileText;
  if (lower.includes(".txt") || lower.includes(".log") || lower.includes(".md") || lower.includes(".csv")) return FileText;
  if (lower.includes(".mp3") || lower.includes(".wav") || lower.includes(".m4a") || lower.includes("audio")) return Mic;
  if (lower.startsWith("📄")) return FileText;
  return MessageSquare;
}

export default function Sidebar({ 
  onSelectConversation, onNewChat, activeId, isCollapsed, onToggleCollapse, refreshKey
}: { 
  onSelectConversation: (id: string) => void; onNewChat: () => void; activeId?: string; isCollapsed: boolean; onToggleCollapse: () => void; refreshKey: number;
}) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  useEffect(() => { loadHistory(); }, [refreshKey]);
  
  const loadHistory = async () => {
    try { 
      const data = await getConversations(); 
      setConversations(Array.isArray(data) ? data : []);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setDeleteId(id);
  };

  const confirmDelete = async () => {
    if (!deleteId) return;
    onNewChat();
    await deleteConversation(deleteId);
    setDeleteId(null);
    loadHistory();
  };

  // Group conversations by time period
  const grouped = conversations.reduce((acc, conv) => {
    const group = timeGroup(conv.date);
    if (!acc[group]) acc[group] = [];
    acc[group].push(conv);
    return acc;
  }, {} as Record<string, Conversation[]>);
  
  const groupOrder = ["Today", "Yesterday", "This Week", "This Month", "Older"];

  return (
    <>
    <div className={`sidebar-panel bg-[var(--dna-glass)] backdrop-blur-xl border border-[var(--dna-border)] rounded-xl shadow-xl flex flex-col h-full overflow-hidden transition-all duration-300 ease-in-out ${isCollapsed ? "w-16" : "w-72"}`}>
      {isCollapsed ? (
        <div className="flex flex-col items-center py-4 gap-4 h-full">
          <button onClick={onToggleCollapse} className="p-2 rounded-lg hover:bg-[var(--dna-surface2)] text-[var(--dna-muted)] transition"><PanelLeftOpen size={20} /></button>
          <button onClick={onNewChat} className="p-2 rounded-lg bg-[var(--dna-accent-light)] text-[var(--dna-accent)] hover:bg-[var(--dna-accent-light)]/80 transition"><Plus size={20} /></button>
        </div>
      ) : (
        <>
          <div className="p-3 border-b border-[var(--dna-border)] bg-[var(--dna-glass)] flex justify-between items-center">
            <button onClick={onNewChat} className="flex-1 flex items-center justify-center gap-2 bg-[var(--dna-accent)] hover:bg-[var(--dna-accent)]/90 text-white py-2 rounded-lg text-sm font-medium transition shadow-sm">
              <Plus size={16} /> New Chat
            </button>
            <button onClick={onToggleCollapse} className="ml-2 p-1.5 rounded-lg hover:bg-[var(--dna-surface2)] text-[var(--dna-muted)] transition"><PanelLeftClose size={16} /></button>
          </div>
          <div className="p-3 pb-1"><h2 className="text-[11px] font-medium text-[var(--dna-muted)] uppercase tracking-wider flex items-center justify-center gap-2"><Clock size={10} /> Memory Lane</h2></div>
          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-3">
            {loading ? (<div className="flex justify-center p-4"><Loader2 className="animate-spin text-[var(--dna-accent)]" size={16} /></div>) : conversations.length === 0 ? (<p className="text-[11px] text-[var(--dna-muted)] text-center p-4">No past memories yet.</p>) : (
              groupOrder.map(group => {
                const items = grouped[group];
                if (!items || items.length === 0) return null;
                return (
                  <div key={group}>
                    <p className="text-[9px] font-medium text-[var(--dna-muted)] uppercase tracking-wider px-2 mb-1">{group}</p>
                    {items.map((conv) => {
                      const Icon = getConvIcon(conv.title);
                      return (
                      <div key={conv.id} onClick={() => onSelectConversation(conv.id)} className={`group flex items-center gap-2 p-2 rounded-lg cursor-pointer transition ${activeId === conv.id ? "bg-[var(--dna-accent-light)] border border-[var(--dna-accent-border)]" : "hover:bg-[var(--dna-surface2)] border border-transparent"}`}>
                        <Icon size={14} className={`flex-shrink-0 ${activeId === conv.id ? "text-[var(--dna-accent)]" : "text-[var(--dna-muted)]"}`} />
                        <div className="flex-1 overflow-hidden">
                          <p className={`text-xs font-medium truncate ${activeId === conv.id ? "text-[var(--dna-accent)]" : "text-[var(--dna-text2)]"}`}>{conv.title}</p>
                          <p className="text-[9px] text-[var(--dna-muted)]">{conv.message_count && conv.message_count > 2 ? `${conv.message_count} messages` : timeAgo(conv.date)}</p>
                        </div>
                        <button onClick={(e) => handleDelete(e, conv.id)} className="opacity-0 group-hover:opacity-100 text-[var(--dna-muted)] hover:text-red-500 transition p-1"><Trash2 size={12} /></button>
                      </div>
                    );
                    })}
                  </div>
                );
              })
            )}
          </div>
        </>
      )}
    </div>

    {/* Delete confirmation overlay */}
    {deleteId && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm" onClick={() => setDeleteId(null)}>
        <div className="bg-[var(--dna-surface)] rounded-2xl shadow-2xl border border-[var(--dna-border)] p-6 max-w-sm w-[90%]" onClick={e => e.stopPropagation()}>
          <p className="text-sm text-[var(--dna-text)] mb-1 font-medium">Delete this memory thread?</p>
          <p className="text-xs text-[var(--dna-muted)] mb-6">This conversation and all its messages will be permanently removed.</p>
          <div className="flex gap-3 justify-end">
            <button onClick={() => setDeleteId(null)} className="px-4 py-2 text-xs font-medium text-[var(--dna-text2)] bg-[var(--dna-surface2)] hover:bg-[var(--dna-border)] rounded-lg transition">Cancel</button>
            <button onClick={confirmDelete} className="px-4 py-2 text-xs font-medium text-white bg-red-500 hover:bg-red-600 rounded-lg transition">Delete</button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
