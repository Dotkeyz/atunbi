"use client";
import { useState, useEffect, useRef } from "react";
import { getConfig, updateConfig, getStats, streamStats, triggerDreamStream } from "@/lib/api";
import { useDebounce } from "@/hooks/useDebounce";
import { SLIDER_DEBOUNCE_MS } from "@/lib/constants";
import { formatDuration } from "@/lib/utils";
import { Sliders, Moon, Loader2, Sparkles, Info } from "lucide-react";
import Tooltip from "@/components/ui/Tooltip";
import AnimatedSlider from "@/components/ui/AnimatedSlider";
import CognitiveAnalytics from "@/components/CognitiveAnalytics";
import DreamPhaseOverlay from "@/components/overlays/DreamPhaseOverlay";
import LifecycleTuningOverlay from "@/components/overlays/LifecycleTuningOverlay";

export default function Controls({ refreshKey = 0 }: { refreshKey?: number }) {
  const [config, setConfig] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [isDreaming, setIsDreaming] = useState(false);
  const [dreamResult, setDreamResult] = useState<any>(null);
  const [dreamSteps, setDreamSteps] = useState<{step:string,detail:string}[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [animatingStats, setAnimatingStats] = useState(false);
  const [flashedSlider, setFlashedSlider] = useState<string | null>(null);
  const [lifecycleRange, setLifecycleRange] = useState(1); // shared max for lifecycle sliders
  const prevStatsRef = useRef<any>(null);
  const debounce = useDebounce();

  useEffect(() => { loadData(); }, [refreshKey]);

  // SSE — real-time stats push, no polling
  useEffect(() => {
    const stop = streamStats((s) => {
      if (prevStatsRef.current) { setAnimatingStats(true); setTimeout(() => setAnimatingStats(false), 600); }
      prevStatsRef.current = s; setStats(s);
    });
    return stop;
  }, []);

  const loadData = async () => {
    try {
      const c = await getConfig(); const s = await getStats();
      if (prevStatsRef.current) { setAnimatingStats(true); setTimeout(() => setAnimatingStats(false), 600); }
      prevStatsRef.current = s; setConfig(c); setStats(s);
    } catch (e) { console.error(e); }
  };

  const handleSliderChange = (key: string, value: number) => {
    setConfig((prev: any) => ({ ...prev, [key]: value }));
    setFlashedSlider(key);
    setTimeout(() => setFlashedSlider(null), 400);
    debounce(key, () => { updateConfig({ [key]: value }); }, SLIDER_DEBOUNCE_MS);
  };

  const handleDream = async () => {
    setIsDreaming(true); setDreamResult(null); setDreamSteps([]);
    try {
      const result = await triggerDreamStream((step) => {
        setDreamSteps((prev) => [...prev, step]);
      });
      setDreamResult(result);
      await loadData();
    } catch (e) { console.error(e); } finally { setIsDreaming(false); }
  };

  if (!config || !stats) {
    return (
      <div className="text-gray-500 p-4 flex items-center justify-center h-full">
        <Loader2 className="animate-spin" />
      </div>
    );
  }

  return (
    <>
      <div className="bg-white/80 backdrop-blur-xl rounded-xl border border-gray-300 p-5 space-y-5 shadow-xl h-full overflow-y-auto overflow-x-hidden">
        <CognitiveAnalytics stats={stats} animatingStats={animatingStats} />

        <div>
          <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2 mb-3">
            <Sliders className="text-amber-500" size={18} /> Controls
          </h2>
          <div className="space-y-4">
            <SliderControl
              label="Recency Half-Life"
              tip="How fast old memories fade in search results. Lower = faster forgetting."
              flashKey="recency_half_life_days"
              value={config.recency_half_life_days ?? 7.0}
              onChange={(v) => handleSliderChange("recency_half_life_days", v)}
              min={lifecycleRange / 480} max={lifecycleRange * 0.25} step={lifecycleRange / 2400}
              flashedSlider={flashedSlider}
              unit="days"
              rangeDriven={lifecycleRange}
            />

            <SliderControl
              label="Max Agent Steps"
              tip="How many tool-calling iterations the agentic loop can make per query. Higher = more thorough but slower."
              flashKey="max_agent_steps"
              value={config.max_agent_steps ?? 5}
              onChange={(v) => handleSliderChange("max_agent_steps", Math.round(v))}
              min={1} max={10} step={1}
              flashedSlider={flashedSlider}
              unit="number"
            />

            <SliderControl
              label="Save Threshold"
              tip="Messages scoring below this importance are discarded immediately. Higher = cleaner memory, lower = capture more."
              flashKey="save_threshold"
              value={config.save_threshold ?? 0.1}
              onChange={(v) => handleSliderChange("save_threshold", v)}
              min={0.0} max={0.5} step={0.05}
              flashedSlider={flashedSlider}
              unit="number"
            />

            <button
              onClick={() => setShowAdvanced(true)}
              className="w-full bg-indigo-50 hover:bg-indigo-100 text-indigo-600 py-2 rounded-lg text-xs font-medium flex items-center justify-center gap-2 transition-all duration-300 border border-indigo-200 hover:border-indigo-300 active:scale-[0.98]"
            >
              <Sliders size={14} /> Fine Tuning
            </button>

            {/* Dream progress steps */}
            {isDreaming && dreamSteps.length > 0 && (
              <div className="bg-indigo-50/80 backdrop-blur rounded-lg border border-indigo-200 p-3 space-y-1.5 max-h-32 overflow-y-auto transition-all">
                {dreamSteps.map((s, i) => (
                  <div key={i} className="flex items-start gap-2 text-[11px]">
                    <span className={`mt-0.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                      s.step === "done" ? "bg-green-500" :
                      s.step === "error" ? "bg-red-500" :
                      s.step === "summarize" ? "bg-amber-500 animate-pulse" :
                      s.step === "facts" ? "bg-purple-500 animate-pulse" :
                      "bg-indigo-400"
                    }`} />
                    <span className={s.step === "done" ? "text-green-700 font-medium" : s.step === "error" ? "text-red-600" : "text-gray-600"}>
                      {s.detail}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <button
              onClick={handleDream}
              disabled={isDreaming}
              className="w-full bg-indigo-600 hover:bg-indigo-500 text-white py-2 rounded-lg text-xs font-medium flex items-center justify-center gap-2 transition-all duration-300 disabled:opacity-50 hover:shadow-lg hover:shadow-indigo-500/20 active:scale-[0.98] border border-transparent"
            >
              {isDreaming
                ? (<><Sparkles size={14} className="animate-spin" /> Consolidating...</>)
                : (<><Moon size={14} /> Trigger Dream Phase</>)}
            </button>
          </div>
        </div>
      </div>

      {dreamResult && (
        <DreamPhaseOverlay result={dreamResult} onClose={() => setDreamResult(null)} />
      )}

      {showAdvanced && (
        <LifecycleTuningOverlay
          config={config}
          onClose={() => setShowAdvanced(false)}
          onConfigChange={handleSliderChange}
          rangeMax={lifecycleRange}
          onRangeMaxChange={setLifecycleRange}
        />
      )}
    </>
  );
}

function SliderControl({ label, tip, flashKey, value, onChange, min, max, step, flashedSlider, unit, rangeDriven }: {
  label: string; tip: string; flashKey: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step: number; flashedSlider: string | null; unit?: "time" | "days" | "number"; rangeDriven?: number;
}) {
  // If rangeDriven is set, pick format based on the current range scale.
  // Lifecycle values are in hours; recency is in days — convert as needed.
  const display = rangeDriven
    ? formatDuration(unit === "days" ? value * 24 : value, rangeDriven)
    : unit === "time" ? formatDuration(value) : unit === "days" ? `${value.toFixed(1)}d` : value.toFixed(2);
  return (
    <div className="relative group">
      <label className="text-xs text-gray-500 flex justify-between mb-1">
        <span className="flex items-center gap-1">
          {label} <Info size={10} className="text-gray-400" />
        </span>
        <span className={`font-mono text-[10px] transition-all duration-300 rounded px-1 ${
          flashedSlider === flashKey ? "bg-indigo-100 text-indigo-700 scale-110" : "text-gray-900"
        }`}>
          {display}
        </span>
      </label>
      <Tooltip text={tip} />
      <AnimatedSlider min={min} max={max} step={step} value={value} onChange={onChange} />
    </div>
  );
}
