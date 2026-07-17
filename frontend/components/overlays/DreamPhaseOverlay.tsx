"use client";
import { Sparkles } from "lucide-react";

interface DreamResult {
  pruned?: number;
  retained?: number;
  episodes_created?: number;
  facts_extracted?: number;
}

export default function DreamPhaseOverlay({ result, onClose }: { result: DreamResult; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm animate-[dna-fade-in_0.3s_ease]" onClick={onClose}>
      <div className="bg-white/95 backdrop-blur-xl rounded-2xl shadow-2xl border border-gray-200/60 p-8 max-w-sm w-[90%] text-center" onClick={e => e.stopPropagation()}>
        <p className="text-[10px] font-semibold text-indigo-500 uppercase tracking-wider mb-4">Dream Phase Complete</p>
        <div className="w-12 h-12 rounded-xl bg-indigo-100 flex items-center justify-center mx-auto mb-4">
          <Sparkles size={22} className="text-indigo-500" />
        </div>
        <p className="text-xs text-gray-400 mb-6">Memories consolidated, noise pruned, facts extracted.</p>
        <div className="grid grid-cols-2 gap-3 mb-6">
          <StatCard label="Pruned" value={result.pruned || 0} color="text-red-500" bg="bg-red-50" />
          <StatCard label="Retained" value={result.retained || 0} color="text-emerald-500" bg="bg-emerald-50" />
          <StatCard label="Episodes" value={result.episodes_created || 0} color="text-indigo-500" bg="bg-indigo-50" />
          <StatCard label="Facts" value={result.facts_extracted || 0} color="text-amber-500" bg="bg-amber-50" />
        </div>
        <button onClick={onClose} className="w-full text-xs text-gray-400 hover:text-gray-600 transition">Close</button>
      </div>
    </div>
  );
}

function StatCard({ label, value, color, bg }: { label: string; value: number; color: string; bg: string }) {
  return (
    <div className={`${bg} rounded-xl p-3`}>
      <p className={`text-xl font-medium ${color}`}>{value}</p>
      <p className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</p>
    </div>
  );
}
