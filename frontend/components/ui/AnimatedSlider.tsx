"use client";
import { useState, useEffect, useRef, useCallback } from "react";

export default function AnimatedSlider({ value, min, max, step, onChange }: {
  value: number; min: number; max: number; step: number; onChange: (v: number) => void;
}) {
  const [localValue, setLocalValue] = useState(value);
  const trackRef = useRef<HTMLDivElement>(null);
  useEffect(() => { setLocalValue(value); }, [value]);
  useEffect(() => { setLocalValue((prev: number) => Math.min(Math.max(prev, min), max)); }, [min, max]);
  const pct = ((localValue - min) / (max - min)) * 100;
  const handlePointer = useCallback((clientX: number) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    const x = Math.min(Math.max(clientX - rect.left, 0), rect.width);
    const raw = min + (x / rect.width) * (max - min);
    const stepped = Math.round(raw / step) * step;
    const clamped = Math.min(Math.max(stepped, min), max);
    setLocalValue(clamped); onChange(clamped);
  }, [min, max, step, onChange]);

  return (
    <div ref={trackRef} className="relative h-6 cursor-pointer group" onPointerDown={(e) => {
      e.preventDefault(); handlePointer(e.clientX);
      const onMove = (e: PointerEvent) => handlePointer(e.clientX);
      const onUp = () => { document.removeEventListener("pointermove", onMove); document.removeEventListener("pointerup", onUp); };
      document.addEventListener("pointermove", onMove); document.addEventListener("pointerup", onUp);
    }}>
      <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div className="h-full bg-indigo-500 rounded-full transition-[width] duration-150 ease-out" style={{ width: `${pct}%` }} />
      </div>
      <div className="absolute top-1/2 -translate-y-1/2 w-4 h-4 bg-white border-2 border-indigo-500 rounded-full shadow-sm transition-transform duration-150 group-hover:scale-125" style={{ left: `calc(${pct}% - 8px)` }} />
    </div>
  );
}
