"use client";
import { Brain } from "lucide-react";

interface Props {
  stats: any;
  animatingStats: boolean;
}

const TIER_CARDS = [
  { label: "Working", key: "working_memory", sub: "active", color: "text-blue-600", bg: "bg-blue-50" },
  { label: "Episodic", key: "episodic_memory", sub: "episodes", color: "text-indigo-600", bg: "bg-indigo-50" },
  { label: "Semantic", key: "semantic_memory", sub: "facts", color: "text-green-600", bg: "bg-green-50" },
  { label: "Entities", key: "entity_graph", sub: "graph", color: "text-amber-600", bg: "bg-amber-50" },
  { label: "Procedural", key: "procedural_memory", sub: "rules", color: "text-purple-600", bg: "bg-purple-50" },
  { label: "Conversations", key: "conversations", sub: "threads", color: "text-violet-600", bg: "bg-violet-50" },
];

const LIFECYCLE_SEGMENTS = [
  { key: "active", color: "bg-blue-500", label: "Active" },
  { key: "inactive", color: "bg-slate-400", label: "Inactive" },
  { key: "prune_candidates", color: "bg-amber-400", label: "Prune" },
  { key: "archive_ready", color: "bg-purple-400", label: "Archive" },
];

export default function CognitiveAnalytics({ stats, animatingStats }: Props) {
  return (
    <div>
      <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2 mb-3">
        <Brain className="text-indigo-500" size={18} /> Cognitive Analytics
      </h2>

      {/* Tier cards */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        {TIER_CARDS.map((card) => (
          <div key={card.label} className={`${card.bg} border border-gray-100 p-2.5 rounded-lg transition-all duration-500 ease-out ${animatingStats ? "scale-105 opacity-80" : "scale-100 opacity-100"}`}>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-0.5">{card.label}</p>
            <p className={`text-lg font-semibold ${card.color} transition-all duration-300`}>{stats[card.key]}</p>
            <p className="text-[9px] text-gray-400 -mt-0.5">{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Memory Lifecycle bar */}
      <div className="bg-gray-50 border border-gray-100 rounded-lg p-3 mb-3">
        <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-2">Memory Lifecycle</p>
        <div className="flex h-5 rounded-full overflow-hidden bg-gray-200 mb-2">
          {stats.lifecycle && stats.total > 0 && LIFECYCLE_SEGMENTS.map(seg => (
            <div
              key={seg.key}
              className={`${seg.color} transition-all duration-500`}
              style={{ width: `${(stats.lifecycle[seg.key] / stats.total) * 100}%` }}
              title={`${seg.label}: ${stats.lifecycle[seg.key]}`}
            />
          ))}
        </div>
        <div className="flex justify-between text-[9px] text-gray-400">
          {LIFECYCLE_SEGMENTS.map(seg => (
            <span key={seg.key} className="flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${seg.color} inline-block`} />
              {seg.label} {stats.lifecycle?.[seg.key] || 0}
            </span>
          ))}
        </div>
      </div>

      {/* Retention health */}
      <RetentionHealth stats={stats} />

      {/* Token Savings — demonstrates context window efficiency */}
      {stats.token_savings && (
        <div className="mt-3 bg-emerald-50 border border-emerald-100 rounded-lg p-3">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-2">Token Budget</p>
          <div className="flex justify-between text-[11px] mb-1">
            <span className="text-gray-400">Without memory</span>
            <span className="font-mono text-gray-600">{stats.token_savings.naive_tokens?.toLocaleString() || 0}</span>
          </div>
          <div className="flex justify-between text-[11px] mb-2">
            <span className="text-gray-400">With Atunbi</span>
            <span className="font-mono text-emerald-700 font-semibold">{stats.token_savings.actual_tokens?.toLocaleString() || 0}</span>
          </div>
          <div className="h-2 bg-gray-200 rounded-full overflow-hidden mb-1">
            <div
              className="h-full bg-emerald-500 rounded-full transition-all duration-700"
              style={{ width: `${Math.min(stats.token_savings.savings_pct || 0, 100)}%` }}
            />
          </div>
          <p className="text-[10px] text-emerald-700 font-semibold text-right">
            {stats.token_savings.savings_pct || 0}% saved
          </p>
        </div>
      )}
    </div>
  );
}

function RetentionHealth({ stats }: { stats: any }) {
  const items = [
    { label: "Avg Imp", value: stats.average_importance, max: 1, color: "bg-indigo-500" },
    { label: "Avg Access", value: (stats.average_access || 0) / 10, max: 1, color: "bg-blue-500" },
    { label: "At Risk", value: stats.at_risk > 0 ? Math.min(stats.at_risk / Math.max(stats.total, 1), 1) : 0, max: 1, color: stats.at_risk > 0 ? "bg-red-400" : "bg-emerald-400" },
  ];

  return (
    <div className="grid grid-cols-3 gap-2">
      {items.map((item) => (
        <div key={item.label} className="text-center">
          <p className="text-[9px] text-gray-400 uppercase mb-1">{item.label}</p>
          <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden mb-0.5">
            <div className={`h-full ${item.color} rounded-full transition-all duration-500`} style={{ width: `${Math.min(item.value * 100, 100)}%` }} />
          </div>
          <p className="text-[10px] font-mono text-gray-600">
            {typeof item.value === 'number' ? (item.value * 100).toFixed(0) + '%' : item.value}
          </p>
        </div>
      ))}
    </div>
  );
}
