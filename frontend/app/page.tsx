"use client";
import { useState, useEffect } from "react";
import { login, register } from "@/lib/api";
import Chat from "@/components/Chat";
import Controls from "@/components/Controls";
import Sidebar from "@/components/Sidebar";
import NeuralBackground from "@/components/NeuralBackground";
import { LogIn, UserPlus, Eye, EyeOff, Loader2, BrainCircuit, LogOut } from "lucide-react";

export default function Home() {
  const [isAuthed, setIsAuthed] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeConversationId, setActiveConversationId] = useState<string | undefined>(() => {
    // Restore last active conversation on page refresh
    if (typeof window !== "undefined") {
      return localStorage.getItem("atunbi_active_conv") || undefined;
    }
    return undefined;
  });

  // Persist active conversation to localStorage so it survives page refresh
  useEffect(() => {
    if (activeConversationId) {
      localStorage.setItem("atunbi_active_conv", activeConversationId);
    } else {
      localStorage.removeItem("atunbi_active_conv");
    }
  }, [activeConversationId]);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0);
  const [resetKey, setResetKey] = useState(0);
  const [controlsWidth, setControlsWidth] = useState(587);
  const [isResizing, setIsResizing] = useState(false);

  // Resize handler for Controls panel
  useEffect(() => {
    if (!isResizing) return;
    const handleMove = (e: MouseEvent) => {
      const newWidth = window.innerWidth - e.clientX;
      setControlsWidth(Math.min(800, Math.max(280, newWidth)));
    };
    const handleUp = () => setIsResizing(false);
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
    return () => {
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
  }, [isResizing]);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    const savedUser = localStorage.getItem("username");
    if (token) { setIsAuthed(true); if (savedUser) setUsername(savedUser); }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) { setError("Username and password are required."); return; }
    setIsLoading(true); setError("");
    try {
      if (isRegistering) await register(username, password); else await login(username, password);
      localStorage.setItem("username", username);
      setIsAuthed(true);
    } catch (err: any) { setError(err.message || "Something went wrong."); } finally { setIsLoading(false); }
  };

  const handleNewChat = () => { 
    setActiveConversationId(undefined); 
    setResetKey(k => k + 1);
    setTimeout(() => {
      setSidebarRefreshKey(prev => prev + 1);
    }, 100);
  };
  
  const handleMessageSent = () => {
    setSidebarRefreshKey(prev => prev + 1);
  };

  if (!isAuthed) {
    return (
      <main className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden bg-gradient-to-br from-indigo-50 via-white to-violet-50">
        <div className="absolute top-1/4 -left-32 w-[500px] h-[500px] rounded-full bg-indigo-300/30 blur-[120px] animate-pulse" />
        <div className="absolute bottom-1/4 -right-32 w-[400px] h-[400px] rounded-full bg-violet-300/25 blur-[100px] animate-pulse [animation-delay:2s]" />
        <NeuralBackground />
        {/* Theme toggle — top right */}
        <button
          onClick={() => {
            const html = document.documentElement;
            const isDark = html.getAttribute('data-theme') === 'dark';
            const next = isDark ? 'light' : 'dark';
            html.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
          }}
          className="fixed top-4 right-4 z-20 w-9 h-9 rounded-lg bg-white/80 backdrop-blur-md border border-gray-200/50 flex items-center justify-center transition hover:bg-gray-100 shadow-sm"
          aria-label="Toggle theme"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="theme-icon-sun text-gray-500"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="theme-icon-moon text-gray-500"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        </button>
        <form onSubmit={handleSubmit} className="relative bg-white/80 backdrop-blur-xl p-8 rounded-2xl border border-gray-200/50 shadow-xl w-full max-w-md space-y-6">
          <div className="flex justify-center"><div className="w-14 h-14 rounded-2xl bg-indigo-600 flex items-center justify-center"><BrainCircuit size={28} className="text-white" /></div></div>
          <div className="text-center"><h1 className="text-3xl font-semibold text-gray-900">Atunbi</h1><p className="text-gray-500 text-sm mt-1">{isRegistering ? "Create your cognitive account" : "Cognitive Architecture Command Center"}</p></div>
          <div className="flex bg-gray-100 rounded-xl p-1">
            <button type="button" onClick={() => { setIsRegistering(false); setError(""); }} className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${!isRegistering ? "bg-white shadow-sm text-gray-900" : "text-gray-500 hover:text-gray-900"}`}><LogIn size={16} className="inline mr-1.5" /> Sign In</button>
            <button type="button" onClick={() => { setIsRegistering(true); setError(""); }} className={`flex-1 py-2 rounded-lg text-sm font-medium transition ${isRegistering ? "bg-white shadow-sm text-gray-900" : "text-gray-500 hover:text-gray-900"}`}><UserPlus size={16} className="inline mr-1.5" /> Register</button>
          </div>
          {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">{error}</div>}
          <div><label className="text-xs text-gray-500 uppercase tracking-wider block mb-1.5">Username</label><input type="text" placeholder="Enter your username" value={username} onChange={(e) => setUsername(e.target.value)} className="w-full bg-white text-gray-900 px-4 py-3 rounded-xl border border-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition placeholder-gray-400" autoFocus /></div>
          <div><label className="text-xs text-gray-500 uppercase tracking-wider block mb-1.5">Password</label><div className="relative"><input type={showPassword ? "text" : "password"} placeholder="Enter your password" value={password} onChange={(e) => setPassword(e.target.value)} className="w-full bg-white text-gray-900 px-4 py-3 pr-12 rounded-xl border border-gray-200 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent transition placeholder-gray-400" /><button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></div>
          <button type="submit" disabled={isLoading} className="w-full bg-indigo-600 hover:bg-indigo-500 text-white py-3 rounded-xl font-medium flex items-center justify-center gap-2 transition disabled:opacity-60">{isLoading ? <Loader2 size={20} className="animate-spin" /> : isRegistering ? <UserPlus size={20} /> : <LogIn size={20} />}{isLoading ? "Connecting..." : isRegistering ? "Create Account" : "Initialize Brain"}</button>
        </form>
      </main>
    );
  }

  return (
    <main className="min-h-screen relative overflow-hidden bg-gradient-to-br from-indigo-50 via-white to-violet-50">
      <div className="fixed top-1/3 -left-48 w-[600px] h-[600px] rounded-full bg-indigo-300/20 blur-[150px] animate-pulse" />
      <div className="fixed bottom-1/3 -right-48 w-[500px] h-[500px] rounded-full bg-violet-300/15 blur-[130px] animate-pulse [animation-delay:3s]" />
      <NeuralBackground />

      <div className="relative z-10 p-4 md:p-6 h-screen flex flex-col">
        <header className="mb-4 flex justify-between items-center bg-white/80 backdrop-blur-md border border-gray-200/50 rounded-xl px-5 py-2.5 shadow-sm flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center"><BrainCircuit size={16} className="text-white" /></div>
            <span className="font-semibold text-gray-900 text-sm">Atunbi</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                const html = document.documentElement;
                const isDark = html.getAttribute('data-theme') === 'dark';
                const next = isDark ? 'light' : 'dark';
                html.setAttribute('data-theme', next);
                localStorage.setItem('theme', next);
              }}
              className="w-9 h-9 rounded-lg hover:bg-gray-100 flex items-center justify-center transition text-gray-500 hover:text-gray-900"
              aria-label="Toggle theme"
              title="Toggle theme"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="theme-icon-sun"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="theme-icon-moon"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
            </button>
            <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center ring-2 ring-indigo-100"><span className="text-[10px] font-semibold text-white">{username ? username.charAt(0).toUpperCase() : "?"}</span></div>
            <button onClick={() => { localStorage.removeItem("access_token"); localStorage.removeItem("username"); setIsAuthed(false); }} className="text-xs text-gray-400 hover:text-red-500 transition flex items-center gap-1.5 px-2 py-1 rounded-lg hover:bg-red-50"><LogOut size={14} /> Sign out</button>
          </div>
        </header>
        
        <div className="flex-1 flex gap-4 min-h-0">
          <div className="flex-shrink-0 h-full">
            <Sidebar 
              onSelectConversation={setActiveConversationId} 
              onNewChat={handleNewChat}
              activeId={activeConversationId}
              isCollapsed={isSidebarCollapsed}
              onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
              refreshKey={sidebarRefreshKey}
            />
          </div>

          <div className="flex-1 h-full min-h-0 min-w-0 flex justify-center">
            <div className="w-full max-w-7xl">
            <Chat
              activeConversationId={activeConversationId}
              resetKey={resetKey}
              onMessageSent={handleMessageSent}
            />
            </div>
          </div>

          <div className="hidden xl:flex flex-col h-full relative" style={{ width: controlsWidth, flexShrink: 0 }}>
            {/* Resize handle */}
            <div
              className="absolute left-0 top-0 bottom-0 w-3 cursor-col-resize hover:bg-indigo-200/30 active:bg-indigo-300/40 transition-colors z-10 flex flex-col items-center justify-center gap-0.5 group"
              onMouseDown={(e) => { e.preventDefault(); setIsResizing(true); }}
            >
              <span className="w-1 h-1 rounded-full bg-gray-300 group-hover:bg-indigo-400 transition-colors" />
              <span className="w-1 h-1 rounded-full bg-gray-300 group-hover:bg-indigo-400 transition-colors" />
              <span className="w-1 h-1 rounded-full bg-gray-300 group-hover:bg-indigo-400 transition-colors" />
            </div>
            <div className="flex-1 min-h-0 pl-2">
              <Controls refreshKey={sidebarRefreshKey} />
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
