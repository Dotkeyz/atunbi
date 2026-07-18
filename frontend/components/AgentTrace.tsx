"use client";
import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  useNodesState,
  useEdgesState,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";

type AgentStep = {
  action: string;
  detail: string;
  variants?: string[];
  entities?: string[];
  snippets?: string[];
  preview?: string[];
  paths?: Array<{ from: string; relation: string; to: string; depth: number }>;
  all_entities?: Array<{ from: string; relation: string; to: string }>;
  mermaid?: string;
};

const TYPE_PALETTE = [
  { bg: "#eef2ff", border: "#818cf8", text: "#3730a3" },
  { bg: "#fef3c7", border: "#f59e0b", text: "#92400e" },
  { bg: "#dcfce7", border: "#86efac", text: "#166534" },
  { bg: "#ede9fe", border: "#c4b5fd", text: "#5b21b6" },
  { bg: "#f0fdf4", border: "#34d399", text: "#065f46" },
  { bg: "#fff1f2", border: "#fda4af", text: "#9f1239" },
  { bg: "#f0f9ff", border: "#38bdf8", text: "#075985" },
  { bg: "#fff7ed", border: "#fdba74", text: "#9a3412" },
  { bg: "#f5f3ff", border: "#a78bfa", text: "#4c1d95" },
  { bg: "#ecfdf5", border: "#6ee7b7", text: "#064e3b" },
];

const STEP_COLORS: Record<string, string> = {
  rewrite: "#94a3b8",
  search: "#5046e5",
  graph: "#16a34a",
  profile: "#7c3aed",
  recent: "#0891b2",
  done: "#ea580c",
  context: "#2563eb",
  insight: "#db2777",
  forget: "#dc2626",
  expand: "#ca8a04",
};

function colorForName(name: string) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0;
  return TYPE_PALETTE[Math.abs(hash) % TYPE_PALETTE.length];
}

function layoutWithDagre(nodes: Node[], edges: Edge[]) {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 60, ranksep: 180, marginx: 40, marginy: 40 });

  nodes.forEach((n) => g.setNode(n.id, { width: 140, height: 48 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 70, y: pos.y - 24 } };
  });
}

export default function AgentTrace({
  steps,
  onClose,
}: {
  steps: AgentStep[];
  onClose: () => void;
}) {
  // Find the graph step with paths — try all graph steps, not just the first
  const allGraphSteps = steps.filter((s) => s.action === "graph");
  const graphStep = allGraphSteps.find((s) => s.paths && (s.paths as any[]).length > 0) 
    || allGraphSteps.find((s) => s.paths)
    || (allGraphSteps.length > 0 ? allGraphSteps[allGraphSteps.length - 1] : undefined);
  const attemptedGraphStep = allGraphSteps.length > 0 ? allGraphSteps[0] : undefined;
  const graphWasAttempted = allGraphSteps.length > 0;
  const graphFailed = graphWasAttempted && (!graphStep || !graphStep.paths || (graphStep.paths as any[]).length === 0);

  // all_entities may be attached to ANY step (usually the last), not just the graph step
  const allEntityData = useMemo(() => {
    const found = [...steps].reverse().find((s: any) => s.all_entities && s.all_entities.length > 0);
    return found?.all_entities || null;
  }, [steps]);

  const contradictions: Array<{entity: string; relation: string; old_target: string; new_target: string}> =
    (graphStep as any)?.contradictions || [];

  // Build nodes and edges from paths — Query tab: only depth-1 (direct connections)
  const { initialNodes, initialEdges } = useMemo(() => {
    if (!graphStep?.paths || graphStep.paths.length === 0) {
      return { initialNodes: [], initialEdges: [] };
    }

    const paths = (graphStep.paths as any[]).filter((p: any) => (p.depth || 0) <= 1);

    const conflictKeys = new Set<string>();
    (contradictions).forEach((c: any) => {
      conflictKeys.add(`${c.entity}|${c.relation}|${c.old_target}`);
    });

    const nodeMap = new Map<string, Node>();
    const edges: Edge[] = [];

    paths.forEach((p, i) => {

      // Add from node
      if (!nodeMap.has(p.from)) {
        const colors = colorForName(p.from);
        nodeMap.set(p.from, {
          id: p.from,
          data: { label: p.from },
          position: { x: 0, y: 0 },
          style: {
            background: colors.bg,
            border: `1.5px solid ${colors.border}`,
            color: colors.text,
            borderRadius: "10px",
            padding: "10px 16px",
            fontSize: "13px",
            fontWeight: 500,
            width: "auto" as any,
          },
        });
      }

      // Add to node
      if (!nodeMap.has(p.to)) {
        const colors = colorForName(p.to);
        nodeMap.set(p.to, {
          id: p.to,
          data: { label: p.to },
          position: { x: 0, y: 0 },
          style: {
            background: colors.bg,
            border: `1.5px solid ${colors.border}`,
            color: colors.text,
            borderRadius: "10px",
            padding: "10px 16px",
            fontSize: "13px",
            fontWeight: 500,
            width: "auto" as any,
          },
        });
      }

      // Check if this edge is part of a contradiction
      const edgeKey = `${p.from}|${p.relation}|${p.to}`;
      const isContradicted = conflictKeys.has(edgeKey);

      // Add edge
      edges.push({
        id: `e-${i}`,
        source: p.from,
        target: p.to,
        label: p.relation,
        animated: !isContradicted,
        style: {
          stroke: isContradicted ? "#ea580c" : "#94a3b8",
          strokeWidth: isContradicted ? 2 : 1.5,
          strokeDasharray: isContradicted ? "4 4" : undefined,
        },
        labelStyle: {
          fill: isContradicted ? "#ea580c" : "#64748b",
          fontSize: 10,
          fontWeight: isContradicted ? 600 : 500,
        },
        labelBgStyle: { fill: isContradicted ? "#fff7ed" : "#fff", fillOpacity: 0.9 },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isContradicted ? "#ea580c" : "#94a3b8",
          width: 14,
          height: 14,
        },
      });
    });

    // Inject conflict edges — consolidate overlapping ones between same nodes
    // Group by (entity, oldTarget) and (entity, newTarget) to avoid duplicate edges
    const oldGroups = new Map<string, string[]>();
    const newGroups = new Map<string, string[]>();
    contradictions.forEach((c: any) => {
      const oldKey = `${c.entity}|||${c.old_target}`;
      const newKey = `${c.entity}|||${c.new_target}`;
      if (!oldGroups.has(oldKey)) oldGroups.set(oldKey, []);
      oldGroups.get(oldKey)!.push(c.relation.replace(/_/g, ' '));
      if (!newGroups.has(newKey)) newGroups.set(newKey, []);
      newGroups.get(newKey)!.push(c.relation.replace(/_/g, ' '));
    });

    // Humanize relation names for graph display — "left" means "was at", etc.
    const humanize = (rel: string, tense: 'was' | 'is'): string => {
      const r = rel.replace(/_/g, ' '); // normalize both "works_at" and "works at"
      if (r === 'left') return tense === 'was' ? 'was at' : 'at';
      if (r === 'works at') return tense === 'was' ? 'was at' : 'at';
      return r;
    };

    // Add old edges (amber dashed)
    oldGroups.forEach((rels, key) => {
      const [entity, oldTarget] = key.split('|||');
      if (!nodeMap.has(entity)) {
        nodeMap.set(entity, { id: entity, data: { label: entity }, position: { x: 0, y: 0 },
          style: { background: "#fff7ed", border: "1.5px solid #fdba74", color: "#9a3412", borderRadius: "10px", padding: "10px 16px", fontSize: "13px", fontWeight: 500, width: "auto" as any } });
      }
      if (!nodeMap.has(oldTarget)) {
        nodeMap.set(oldTarget, { id: oldTarget, data: { label: oldTarget }, position: { x: 0, y: 0 },
          style: { background: "#fff7ed", border: "1.5px solid #fdba74", color: "#9a3412", borderRadius: "10px", padding: "10px 16px", fontSize: "13px", fontWeight: 500, width: "auto" as any } });
      }
      const humanized = [...new Set(rels.map(r => humanize(r, 'was')).filter(Boolean))];
      if (humanized.length === 0) return;
      const label = humanized.length === 1 ? humanized[0] : humanized.join(' / ');
      edges.push({
        id: `conflict-old-${key}`,
        source: entity, target: oldTarget, label,
        animated: false,
        style: { stroke: "#ea580c", strokeWidth: 2.5, strokeDasharray: "6 3" },
        labelStyle: { fill: "#ea580c", fontSize: 9, fontWeight: 600 },
        labelBgStyle: { fill: "#fff7ed", fillOpacity: 0.95 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#ea580c", width: 14, height: 14 },
      });
    });

    // Add new edges (green solid)
    newGroups.forEach((rels, key) => {
      const [entity, newTarget] = key.split('|||');
      if (!nodeMap.has(newTarget)) {
        nodeMap.set(newTarget, { id: newTarget, data: { label: newTarget }, position: { x: 0, y: 0 },
          style: { background: "#dcfce7", border: "1.5px solid #86efac", color: "#166534", borderRadius: "10px", padding: "10px 16px", fontSize: "13px", fontWeight: 500, width: "auto" as any } });
      }
      const humanized = [...new Set(rels.map(r => humanize(r, 'is')).filter(Boolean))];
      if (humanized.length === 0) return;
      const label = humanized.length === 1 ? humanized[0] : humanized.join(' / ');
      edges.push({
        id: `conflict-new-${key}`,
        source: entity, target: newTarget, label,
        animated: true,
        style: { stroke: "#16a34a", strokeWidth: 2 },
        labelStyle: { fill: "#16a34a", fontSize: 9, fontWeight: 600 },
        labelBgStyle: { fill: "#f0fdf4", fillOpacity: 0.95 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#16a34a", width: 14, height: 14 },
      });
    });

    // Apply dagre layout
    const laidOut = layoutWithDagre(Array.from(nodeMap.values()), edges);

    return { initialNodes: laidOut, initialEdges: edges };
  }, [graphStep]);

  // Full graph from all entities (not just query paths)
  const { fullNodes, fullEdges } = useMemo(() => {
    const allEntities = allEntityData;
    if (!allEntities || allEntities.length === 0) return { fullNodes: [], fullEdges: [] };
    
    const nodeMap = new Map<string, Node>();
    const edges: Edge[] = [];
    
    allEntities.forEach((e, i) => {
      if (!nodeMap.has(e.from)) {
        const colors = colorForName(e.from);
        nodeMap.set(e.from, {
          id: e.from, data: { label: e.from }, position: { x: 0, y: 0 },
          style: { background: colors.bg, border: `1.5px solid ${colors.border}`, color: colors.text, borderRadius: "10px", padding: "10px 16px", fontSize: "13px", fontWeight: 500, width: "auto" as any },
        });
      }
      if (!nodeMap.has(e.to)) {
        const colors = colorForName(e.to);
        nodeMap.set(e.to, {
          id: e.to, data: { label: e.to }, position: { x: 0, y: 0 },
          style: { background: colors.bg, border: `1.5px solid ${colors.border}`, color: colors.text, borderRadius: "10px", padding: "10px 16px", fontSize: "13px", fontWeight: 500, width: "auto" as any },
        });
      }
      edges.push({
        id: `full-e-${i}`, source: e.from, target: e.to, label: e.relation,
        animated: false,
        style: { stroke: "#94a3b8", strokeWidth: 1.5 },
        labelStyle: { fill: "#64748b", fontSize: 10, fontWeight: 500 },
        labelBgStyle: { fill: "#fff", fillOpacity: 0.9 },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#94a3b8", width: 14, height: 14 },
      });
    });
    
    const laidOut = layoutWithDagre(Array.from(nodeMap.values()), edges);
    return { fullNodes: laidOut, fullEdges: edges };
  }, [allEntityData]);

  const [showAllContext, setShowAllContext] = useState(false);
  const [focusedNode, setFocusedNode] = useState<string | null>(null);
  const [conflictFocus, setConflictFocus] = useState<Set<string> | null>(null);
  const [showFullGraph, setShowFullGraph] = useState(false);

  const displayNodes = showFullGraph && fullNodes.length > 0 ? fullNodes : initialNodes;
  const displayEdges = showFullGraph && fullEdges.length > 0 ? fullEdges : initialEdges;

  const [nodes, _setNodes, onNodesChange] = useNodesState(displayNodes);
  const [edges, _setEdges, onEdgesChange] = useEdgesState(displayEdges);

  useMemo(() => {
    _setNodes(displayNodes);
    _setEdges(displayEdges);
  }, [displayNodes, displayEdges]);

  const activeFocus = conflictFocus || (focusedNode ? new Set([focusedNode]) : null);

  const styledEdges = useMemo(() => {
    if (!activeFocus) return edges;
    return edges.map((e) => {
      const isConnected = activeFocus.has(e.source) || activeFocus.has(e.target);
      return {
        ...e,
        style: {
          ...e.style,
          stroke: isConnected ? (e.style?.stroke || "#94a3b8") : "#e2e8f0",
          strokeWidth: isConnected ? (e.style?.strokeWidth || 1.5) : 0.5,
        },
        animated: isConnected ? (e.animated !== false) : false,
        labelStyle: {
          ...e.labelStyle,
          fill: isConnected ? (e.labelStyle?.fill || "#64748b") : "#cbd5e1",
        },
      };
    });
  }, [edges, activeFocus]);

  const styledNodes = useMemo(() => {
    if (!activeFocus) return nodes;
    return nodes.map((n) => {
      const isFocused = activeFocus.has(n.id);
      return {
        ...n,
        style: {
          ...n.style,
          opacity: isFocused ? 1 : 0.3,
          transition: "opacity 0.2s",
        },
      };
    });
  }, [nodes, activeFocus]);

  // Group context chips by label prefix
  const contextStep = steps.find((s) => s.action === "context" && s.preview);

  const modal = (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-[dna-fade-in_0.15s_ease]" />
      <div
        className="relative z-10 bg-white rounded-2xl shadow-2xl border border-gray-200 w-full max-w-5xl h-[90vh] flex overflow-hidden animate-[dna-fade-in_0.2s_ease]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Left: Agent steps timeline */}
        <div className="w-72 flex-shrink-0 border-r border-gray-100 bg-gray-50/50 flex flex-col">
          <div className="px-5 py-4 border-b border-gray-100 bg-white">
            <h3 className="text-sm font-semibold text-gray-700">Agent Trace</h3>
            <p className="text-[10px] text-gray-400 mt-0.5">How Atunbi found the answer</p>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
            {steps.map((step, i) => {
              const color = STEP_COLORS[step.action] || "#94a3b8";
              const isLast = i === steps.length - 1;
              return (
              <div key={i} className="relative pl-5 pb-4 last:pb-0">
                <div className="absolute left-0 top-1.5 w-2 h-2 rounded-full ring-2"
                  style={{ backgroundColor: color, boxShadow: `0 0 0 2px white, 0 0 0 3px ${color}40` }} />
                {!isLast && (
                  <div className="absolute left-[3px] top-3.5 w-0.5 h-full"
                    style={{ backgroundColor: `${color}40` }} />
                )}
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] font-semibold text-gray-300 tabular-nums">{i + 1}</span>
                    <span className="text-[10px] font-semibold uppercase tracking-wider"
                      style={{ color }}>
                      {step.action.replace("_", " ")}
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-600 mt-0.5">{step.detail}</p>
                  {step.variants && (
                    <div className="mt-1 space-y-0.5">
                      {step.variants.slice(0, 3).map((v, j) => (
                        <div key={j} className="text-[10px] text-gray-400 font-mono truncate">
                          "{v}"
                        </div>
                      ))}
                    </div>
                  )}
                  {step.snippets && (
                    <div className="mt-1.5 space-y-1">
                      {step.snippets.map((s, j) => (
                        <div key={j} className="text-[9px] text-gray-500 bg-gray-50 border border-gray-100 rounded px-2 py-1 leading-relaxed italic">
                          {s}
                        </div>
                      ))}
                    </div>
                  )}
                  {step.preview && (
                    <div className="mt-1.5 space-y-1">
                      {(showAllContext ? step.preview : step.preview.slice(0, 5)).map((p, j) => (
                        <div key={j} className="text-[9px] text-gray-500 bg-indigo-50/50 border border-indigo-100 rounded px-2 py-1 leading-relaxed truncate">
                          {p.replace(/<[^>]*>/g, '').replace(/&lt;[^&]*&gt;/g, '').replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ')}
                        </div>
                      ))}
                      {step.preview.length > 5 && (
                        <button
                          onClick={(e) => { e.stopPropagation(); setShowAllContext(!showAllContext); }}
                          className="text-[9px] text-indigo-500 hover:text-indigo-600 font-medium mt-0.5"
                        >
                          {showAllContext ? 'Show less' : `Show all ${step.preview.length} memories →`}
                        </button>
                      )}
                    </div>
                  )}
                  {step.entities && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {[...new Set(step.entities)].map((e, idx) => (
                        <span key={idx} className="text-[9px] text-indigo-500 bg-indigo-50 px-1.5 py-0.5 rounded-full">
                          {e}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              );
            })}
          </div>
        </div>

        {/* Right: Graph visualization */}
        <div className="flex-1 flex flex-col">
          <div className="px-5 py-4 border-b border-gray-100 bg-white flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                Entity Graph
                {contradictions.length > 0 && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      // Build set of all conflict-related node IDs
                      const ids = new Set<string>();
                      contradictions.forEach((c: any) => {
                        ids.add(c.entity);
                        ids.add(c.old_target);
                        ids.add(c.new_target);
                      });
                      setConflictFocus(conflictFocus ? null : ids);
                    }}
                    className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border transition-colors ${
                      conflictFocus
                        ? 'bg-amber-100 text-amber-800 border-amber-300'
                        : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
                    }`}
                  >
                    {contradictions.length} conflict{contradictions.length > 1 ? 's' : ''}
                  </button>
                )}
              </h3>
              <p className="text-[10px] text-gray-400 mt-0.5">
                {displayNodes.length} entities · {displayEdges.length} relationships
              </p>
              {allEntityData && allEntityData.length > 0 && (
                <div className="flex items-center gap-0 mt-1.5 bg-gray-100 rounded-md p-0.5 w-fit">
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowFullGraph(false); }}
                    className={`text-[10px] font-medium px-2.5 py-1 rounded transition-colors ${
                      !showFullGraph
                        ? 'bg-white text-gray-700 shadow-sm'
                        : 'text-gray-400 hover:text-gray-600'
                    }`}
                  >
                    Query
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowFullGraph(true); }}
                    className={`text-[10px] font-medium px-2.5 py-1 rounded transition-colors ${
                      showFullGraph
                        ? 'bg-white text-indigo-700 shadow-sm'
                        : 'text-gray-400 hover:text-gray-600'
                    }`}
                  >
                    All Entities
                  </button>
                </div>
              )}
              {contradictions.length > 0 && (
                <div className="flex items-center gap-3 mt-2 text-[10px]">
                  <span className="flex items-center gap-1 text-emerald-600 font-medium">
                    <span className="w-4 h-0.5 bg-emerald-500 rounded-full inline-block"></span>
                    current
                  </span>
                  <span className="flex items-center gap-1 text-amber-600 font-medium">
                    <span className="w-4 h-0.5 border-t-2 border-dashed border-amber-500 rounded-full inline-block"></span>
                    previous
                  </span>
                  <span className="flex items-center gap-1 text-gray-500">
                    <span className="w-4 h-0.5 bg-slate-400 rounded-full inline-block"></span>
                    other
                  </span>
                </div>
              )}
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none px-2">
              ×
            </button>
          </div>
          <div className="flex-1 relative">
            {displayNodes.length > 0 ? (
              <>
              <ReactFlow
                key={showFullGraph ? 'full' : 'query'}
                nodes={styledNodes}
                edges={styledEdges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onNodeClick={(_e, node) => {
                  setConflictFocus(null);
                  setFocusedNode(focusedNode === node.id ? null : node.id);
                }}
                onPaneClick={() => { setFocusedNode(null); setConflictFocus(null); }}
                fitView
                fitViewOptions={{ padding: 0.3 }}
                attributionPosition="bottom-left"
                minZoom={0.3}
                maxZoom={2}
              >
                <Background color="#f1f5f9" gap={20} />
                <Controls
                  className="!rounded-lg !border !border-gray-200 !shadow-sm"
                  position="bottom-right"
                />
                <MiniMap
                  nodeColor={(n) => {
                    const bg = n.style?.background;
                    return typeof bg === "string" ? bg : "#e2e8f0";
                  }}
                  maskColor="rgba(0,0,0,0.05)"
                  className="!rounded-lg !border !border-gray-200"
                />
              </ReactFlow>
              {activeFocus && activeFocus.size > 0 && !(activeFocus.size === 1 && focusedNode) && (
                <div className="absolute top-3 left-1/2 -translate-x-1/2 bg-white border border-amber-200 rounded-lg px-3 py-1.5 shadow-sm text-[11px] text-amber-700 flex items-center gap-2 z-10">
                  <span className="font-medium">{activeFocus.size} conflict nodes</span>
                  <span className="text-amber-300">·</span>
                  <span>{edges.filter(e => activeFocus.has(e.source) || activeFocus.has(e.target)).length} connections</span>
                  <button onClick={() => setConflictFocus(null)} className="ml-1 text-amber-400 hover:text-amber-600">×</button>
                </div>
              )}
              {focusedNode && (
                <div className="absolute top-3 left-1/2 -translate-x-1/2 bg-white border border-gray-200 rounded-lg px-3 py-1.5 shadow-sm text-[11px] text-gray-600 flex items-center gap-2 z-10">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: nodes.find(n => n.id === focusedNode)?.style?.border as string || "#5046e5" }} />
                  <span className="font-medium">{focusedNode}</span>
                  <span className="text-gray-300">·</span>
                  <span>{edges.filter(e => e.source === focusedNode || e.target === focusedNode).length} connections</span>
                  <button onClick={() => setFocusedNode(null)} className="ml-1 text-gray-400 hover:text-gray-600">×</button>
                </div>
              )}
              </>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-gray-400 px-8 text-center">
                <div className="w-12 h-12 rounded-xl bg-gray-50 flex items-center justify-center mb-3">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="1.5" strokeLinecap="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/></svg>
                </div>
                {graphFailed ? (
                  <>
                    <p className="text-sm font-medium text-gray-500 mb-1">Checked "{attemptedGraphStep?.detail || 'graph'}"</p>
                    {graphWasAttempted && attemptedGraphStep?.detail?.includes("new or unlinked") ? (
                      <p className="text-[11px] text-gray-400 leading-relaxed">This entity was just mentioned — it hasn't formed connections to other memories yet. As you share more, relationships will appear here.</p>
                    ) : (
                      <p className="text-[11px] text-gray-400 leading-relaxed">No connections found from this entity. Try mentioning related people, places, or topics to build the graph.</p>
                    )}
                  </>
                ) : (
                  <>
                    <p className="text-sm font-medium text-gray-500 mb-1">No graph traversal in this query</p>
                    <p className="text-[11px] text-gray-400 leading-relaxed">Ask "how is X related to Y" or "what else should I know" to trigger entity graph exploration.</p>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") return null;
  return createPortal(modal, document.body);
}
