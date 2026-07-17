"use client";
import AnimatedSlider from "@/components/ui/AnimatedSlider";
import TimeInput from "@/components/ui/TimeInput";

interface Props {
  config: any;
  onClose: () => void;
  onConfigChange: (key: string, value: number) => void;
  rangeMax: number;
  onRangeMaxChange: (v: number) => void;
}

const PRESETS = [
  { label: "30s", max: 0.008 },
  { label: "5m", max: 0.083 },
  { label: "1h", max: 1 },
  { label: "7d", max: 168 },
];

export default function LifecycleTuningOverlay({ config, onClose, onConfigChange, rangeMax, onRangeMaxChange }: Props) {
  const step = rangeMax / 200;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm animate-[dna-fade-in_0.3s_ease]" onClick={onClose}>
      <div className="bg-white/95 backdrop-blur-xl rounded-2xl shadow-2xl border border-gray-200/60 p-8 max-w-md w-[90%] max-h-[80vh] overflow-y-auto overflow-x-hidden" onClick={e => e.stopPropagation()}>
        <p className="text-[10px] font-semibold text-indigo-500 uppercase tracking-wider mb-4">Lifecycle Tuning</p>
        <p className="text-xs text-gray-400 mb-3">Fine-tune how memories age, decay, and get archived.</p>

        {/* Range scale */}
        <div className="flex items-center gap-2 mb-6 bg-gray-50 rounded-xl p-3">
          <span className="text-[10px] text-gray-400 uppercase tracking-wider shrink-0">Range</span>
          <div className="flex gap-0.5">
            {PRESETS.map(p => (
              <button
                key={p.label}
                onClick={() => onRangeMaxChange(p.max)}
                className={`w-7 h-6 text-[10px] font-semibold rounded-md transition ${
                  rangeMax === p.max
                    ? "bg-indigo-500 text-white"
                    : "bg-white text-gray-400 hover:text-gray-600 hover:bg-gray-100 border border-gray-200"
                }`}
              >{p.label}</button>
            ))}
          </div>
          <div className="flex-1" />
          <TimeInput value={rangeMax} onChange={onRangeMaxChange} />
        </div>

        <div className="space-y-4">
          <div className="bg-amber-50/60 border border-amber-200/50 rounded-xl p-3 -mx-1 space-y-3">
            <div>
              <label className="text-xs text-gray-500 flex justify-between mb-1">
                <span className="font-semibold text-amber-700">Max Memory Life — Hard Ceiling</span>
                <TimeInput value={config.max_working_life_h ?? 168} onChange={(v) => onConfigChange("max_working_life_h", v)} rangeMax={rangeMax} />
              </label>
              <p className="text-[10px] text-gray-400 mb-2">No working memory survives beyond this. Everything above this age is pruned or archived.</p>
              <AnimatedSlider min={0.0167} max={rangeMax} step={step} value={config.max_working_life_h ?? 168} onChange={(v) => onConfigChange("max_working_life_h", v)} />
            </div>
            <div className="border-t border-amber-200/50 pt-3">
              <label className="text-xs text-gray-500 flex justify-between mb-1">
                <span className="font-semibold text-amber-700">Min Memory Life — Hard Floor</span>
                <TimeInput value={config.min_working_life_h ?? 1} onChange={(v) => onConfigChange("min_working_life_h", v)} rangeMax={rangeMax} />
              </label>
              <p className="text-[10px] text-gray-400 mb-2">Even a zero-importance greeting lives at least this long. Prevents pruning mid-conversation.</p>
              <AnimatedSlider min={0.001} max={rangeMax} step={step} value={config.min_working_life_h ?? 1} onChange={(v) => onConfigChange("min_working_life_h", v)} />
            </div>
          </div>

          <SliderRow label="Active Window" keyName="active_window_h" config={config} defaultVal={6} rangeMax={rangeMax} step={step} onChange={onConfigChange} />
          <SliderRow label="Base Lifespan" keyName="base_hours" config={config} defaultVal={24} rangeMax={rangeMax} step={step} onChange={onConfigChange} />
          <SliderRow label="Access Boost" keyName="hours_per_access" config={config} defaultVal={6} rangeMax={rangeMax} step={step} onChange={onConfigChange} min={0} />
          <SliderRow label="Archive Guard" keyName="min_convo_age_to_archive_h" config={config} defaultVal={24} rangeMax={rangeMax} step={step} onChange={onConfigChange} />
        </div>

        <button onClick={onClose} className="mt-6 text-xs text-gray-400 hover:text-gray-600 transition w-full text-center">Close</button>
      </div>
    </div>
  );
}

function SliderRow({ label, keyName, config, defaultVal, rangeMax, step, onChange, min = 0.001 }: {
  label: string; keyName: string; config: any; defaultVal: number; rangeMax: number; step: number; onChange: (k: string, v: number) => void; min?: number;
}) {
  return (
    <div>
      <label className="text-xs text-gray-500 flex justify-between mb-1">
        <span>{label}</span>
        <TimeInput value={config[keyName] ?? defaultVal} onChange={(v) => onChange(keyName, v)} rangeMax={rangeMax} />
      </label>
      <AnimatedSlider min={min} max={rangeMax} step={step} value={config[keyName] ?? defaultVal} onChange={(v) => onChange(keyName, v)} />
    </div>
  );
}
