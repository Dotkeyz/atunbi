"use client";
import { useState, useRef } from "react";
import { Upload, Loader2, Check, FileAudio } from "lucide-react";

export default function IngestionZone({ onIngested }: { onIngested?: () => void }) {
  const [isUploading, setIsUploading] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const uploadFile = async (file: File) => {
    setIsUploading(true); setLastResult(null);
    try {
      const token = localStorage.getItem("access_token");
      const form = new FormData();
      form.append("file", file);
      
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}/api/v1/ingest`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      
      const data = await res.json();
      if (data.status === "ingested") {
        setLastResult(`✅ ${data.segments} segments from ${file.name}`);
      } else if (data.status === "unsupported") {
        setLastResult(`⚠️ ${file.name}: .${data.extension} not yet supported`);
      } else {
        setLastResult(`📎 ${file.name} processed`);
      }
      if (onIngested) onIngested();
    } catch (e) {
      setLastResult(`❌ Failed to upload ${file.name}`);
    } finally {
      setIsUploading(false);
      setTimeout(() => setLastResult(null), 5000);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); setIsDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  };

  return (
    <div className="relative">
      {/* Upload button — subtle, integrated */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={isUploading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium text-gray-400 hover:text-indigo-500 hover:bg-indigo-50 dark:hover:bg-indigo-500/10 transition border border-dashed border-gray-300 dark:border-gray-600 hover:border-indigo-300 dark:hover:border-indigo-500/30"
        >
          {isUploading ? (
            <Loader2 size={14} className="animate-spin" />
          ) : lastResult ? (
            <Check size={14} className="text-emerald-500" />
          ) : (
            <Upload size={14} />
          )}
          {isUploading ? "Ingesting..." : lastResult ? "Done" : "Upload"}
        </button>
        
        {lastResult && (
          <span className="text-[10px] text-gray-400 animate-[dna-fade-in_0.3s_ease] truncate max-w-[200px]">
            {lastResult}
          </span>
        )}
      </div>

      <input
        ref={fileRef}
        type="file"
        className="hidden"
        accept=".mp3,.wav,.m4a,.ogg,.flac,.webm,.aac,.txt,.md,.csv,.log,.pdf"
        onChange={e => { const f = e.target.files?.[0]; if (f) uploadFile(f); }}
      />
      
      {/* Drag overlay — shows when dragging over the page */}
      {isDragOver && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-indigo-500/10 backdrop-blur-sm"
          onDragOver={e => e.preventDefault()}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
        >
          <div className="bg-white dark:bg-[#1e1e2e] rounded-2xl shadow-2xl border border-indigo-200 dark:border-indigo-500/30 p-10 text-center">
            <FileAudio size={48} className="text-indigo-400 mx-auto mb-4" />
            <p className="text-base font-semibold text-gray-700 dark:text-gray-200">Drop to ingest</p>
            <p className="text-xs text-gray-400 mt-1">Audio, text, or PDF</p>
          </div>
        </div>
      )}
    </div>
  );
}
